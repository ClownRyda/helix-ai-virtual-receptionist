"""
ARI Agent — core call handler.

Flow:
  1. Asterisk fires StasisStart → we create a mixing bridge + ExternalMedia channel
  2. Raw slin16 RTP flows bidirectionally between Asterisk and our UDP socket
  3. We buffer audio, run Silero VAD for speech detection, send chunks to Whisper
  4. Transcript → Ollama intent detection
  5. Ollama generates spoken response → Piper TTS → RTP back to caller
  6. Based on intent:
     - "schedule" → query Google Calendar, offer slots, book appointment
     - "transfer" → look up routing rules, redirect call via ARI

v1.2 additions:
  - Business hours / holiday gate before greeting
  - After-hours behavior: callback message, voicemail, schedule flow, or emergency transfer
  - VIP caller detection → direct to operator
  - DTMF fallback menu (gated by DTMF_ENABLED)
  - Retry / timeout / unknown-intent recovery with proper prompts
  - Max-retries → operator fallback
  - Structured call-path logging (stored in CallLog.notes as JSON)
  - Optional call summary via LLM (stored in CallLog.summary)
"""
import asyncio
import json
import socket
import struct
import time
import aiohttp
import structlog
from datetime import datetime, date
from zoneinfo import ZoneInfo

from config import settings
from stt.whisper_engine import transcribe_pcm
from tts.piper_engine import synthesize_pcm
from llm.intent_engine import (
    detect_intent, generate_response, generate_call_summary, ConversationState
)
from llm.translate_engine import ensure_english
from calendar.gcal import get_available_slots, book_appointment, slots_to_speech, parse_slot_choice
from routing.router import get_route_for_intent, get_vip_route, get_after_hours_route
from database import AsyncSessionLocal, CallLog, Holiday, VoicemailMessage
from vad import SileroVADEngine

log = structlog.get_logger(__name__)

# RTP constants
RTP_HEADER_SIZE = 12
SAMPLE_RATE = 16000           # slin16
FRAME_MS = 20                 # 20ms frames
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000  # 320
BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2             # 640 bytes (PCM16)
MAX_UTTERANCE_SECONDS = 15   # Max recording per turn


# ── Business hours helpers ────────────────────────────────────────────────────

def _is_business_hours() -> bool:
    """
    Return True if the current local time is within business hours on a weekday.
    Timezone is determined by BUSINESS_TIMEZONE.
    Does NOT check holidays — use _is_holiday() for that.
    """
    tz = ZoneInfo(settings.business_timezone)
    now = datetime.now(tz)
    if now.weekday() >= 5:       # Saturday=5, Sunday=6
        return False
    hour = now.hour
    return settings.business_hours_start <= hour < settings.business_hours_end


def _today_is_config_holiday() -> bool:
    """
    Check if today is in the comma-separated HOLIDAY_DATES env var.
    Format: "2026-12-25,2027-01-01"
    """
    if not settings.holiday_dates:
        return False
    tz = ZoneInfo(settings.business_timezone)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    dates = [d.strip() for d in settings.holiday_dates.split(",") if d.strip()]
    return today_str in dates


async def _today_is_db_holiday() -> bool:
    """Check if today is in the Holiday database table."""
    tz = ZoneInfo(settings.business_timezone)
    today = datetime.now(tz).date()
    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Holiday).where(
                    Holiday.date == today,
                    Holiday.active == True,
                )
            )
            return result.scalars().first() is not None
    except Exception as e:
        log.warning("Holiday DB check failed", error=str(e))
        return False


async def _is_open() -> bool:
    """Combined check: returns True only if within hours AND not a holiday."""
    if not _is_business_hours():
        return False
    if _today_is_config_holiday():
        return False
    if await _today_is_db_holiday():
        return False
    return True


# ── DTMF helpers ──────────────────────────────────────────────────────────────

def _parse_dtmf_map() -> dict[str, str]:
    """Parse DTMF_MAP JSON string into a digit→extension dict."""
    try:
        return json.loads(settings.dtmf_map)
    except Exception:
        log.warning("Invalid DTMF_MAP — using default", dtmf_map=settings.dtmf_map)
        return {"0": settings.operator_extension}


# ── Call-path logger ──────────────────────────────────────────────────────────

class CallPath:
    """
    Records structured call-path events for diagnostics.
    Serialized to JSON and stored in CallLog.notes at call end.
    """

    def __init__(self, call_id: str):
        self.call_id = call_id
        self.events: list[dict] = []

    def record(self, event: str, **kwargs):
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "event": event,
            **kwargs,
        }
        self.events.append(entry)
        log.debug("Call path event", call_id=self.call_id, **entry)

    def to_json(self) -> str:
        return json.dumps(self.events, default=str)


# ── RTP Socket ───────────────────────────────────────────────────────────────

class RTPSocket:
    """Manages a UDP socket for RTP audio exchange with Asterisk ExternalMedia."""

    def __init__(self, listen_host: str, listen_port: int):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((listen_host, listen_port))
        self.sock.setblocking(False)
        self.asterisk_addr: tuple | None = None
        self._seq = 0
        self._ssrc = int(time.time()) & 0xFFFFFFFF
        self._timestamp = 0

    def _make_rtp_header(self, payload_len: int) -> bytes:
        header = struct.pack(
            "!BBHII",
            0x80,
            11,
            self._seq & 0xFFFF,
            self._timestamp,
            self._ssrc,
        )
        self._seq += 1
        self._timestamp += SAMPLES_PER_FRAME
        return header

    def send_pcm(self, pcm_bytes: bytes):
        if not self.asterisk_addr:
            return
        for i in range(0, len(pcm_bytes), BYTES_PER_FRAME):
            chunk = pcm_bytes[i:i + BYTES_PER_FRAME]
            if len(chunk) < BYTES_PER_FRAME:
                chunk += b"\x00" * (BYTES_PER_FRAME - len(chunk))
            header = self._make_rtp_header(len(chunk))
            packet = header + chunk
            try:
                self.sock.sendto(packet, self.asterisk_addr)
            except OSError:
                pass

    def close(self):
        self.sock.close()


# ── ARI Client ────────────────────────────────────────────────────────────────

class ARIClient:
    """Minimal async ARI REST + WebSocket client."""

    def __init__(self):
        self.base_url = (
            f"http://{settings.asterisk_host}:{settings.asterisk_ari_port}/ari"
        )
        self.auth = aiohttp.BasicAuth(
            settings.asterisk_ari_user, settings.asterisk_ari_password
        )
        self._session: aiohttp.ClientSession | None = None

    async def start(self):
        self._session = aiohttp.ClientSession(auth=self.auth)

    async def stop(self):
        if self._session:
            await self._session.close()

    async def get(self, path: str) -> dict:
        async with self._session.get(f"{self.base_url}{path}") as r:
            r.raise_for_status()
            return await r.json()

    async def post(self, path: str, **kwargs) -> dict | None:
        async with self._session.post(f"{self.base_url}{path}", **kwargs) as r:
            if r.status in (200, 201):
                return await r.json()
            return None

    async def delete(self, path: str):
        async with self._session.delete(f"{self.base_url}{path}") as r:
            return r.status

    async def create_bridge(self, bridge_type: str = "mixing") -> dict:
        return await self.post(f"/bridges", json={"type": bridge_type})

    async def add_to_bridge(self, bridge_id: str, channel_id: str):
        await self.post(f"/bridges/{bridge_id}/addChannel", json={"channel": channel_id})

    async def create_external_media(
        self, app: str, external_host: str, format: str = "slin16"
    ) -> dict:
        return await self.post(
            "/channels/externalMedia",
            json={
                "app": app,
                "external_host": external_host,
                "format": format,
                "direction": "both",
            },
        )

    async def get_channel_var(self, channel_id: str, var: str) -> str:
        result = await self.get(f"/channels/{channel_id}/variable?variable={var}")
        return result.get("value", "")

    async def continue_dialplan(self, channel_id: str, context: str = "fallback", exten: str = "s", priority: int = 1):
        await self.post(f"/channels/{channel_id}/continue", json={
            "context": context, "extension": exten, "priority": priority
        })

    async def redirect_channel(self, channel_id: str, endpoint: str):
        await self.post(f"/channels/{channel_id}/redirect", json={"endpoint": endpoint})

    async def dial_to_bridge(self, endpoint: str, bridge_id: str, app: str) -> dict | None:
        return await self.post("/channels", json={
            "endpoint": f"PJSIP/{endpoint}",
            "app": app,
            "appArgs": f"relay,{bridge_id}",
            "originator": "",
            "callerId": "Helix AI Transfer",
        })

    async def snoop_channel(
        self, channel_id: str, app: str, spy: str = "in", whisper: str = "none"
    ) -> dict | None:
        return await self.post(
            f"/channels/{channel_id}/snoop",
            json={"app": app, "spy": spy, "whisper": whisper},
        )

    async def hangup(self, channel_id: str, reason: str = "normal"):
        await self.delete(f"/channels/{channel_id}?reason={reason}")

    async def play_silence(self, channel_id: str, duration_ms: int = 500):
        await self.post(f"/channels/{channel_id}/play", json={
            "media": f"tone:silence/{duration_ms}"
        })

    async def subscribe_dtmf(self, channel_id: str):
        """No-op placeholder — DTMF events arrive via the WebSocket automatically."""
        pass


# ── Call Handler ──────────────────────────────────────────────────────────────

class CallHandler:
    """
    Handles a single inbound call end-to-end.
    Spawned per call from the main ARI event loop.
    """

    def __init__(self, ari: ARIClient, channel_id: str, caller_id: str, called_number: str,
                 dtmf_queue: asyncio.Queue | None = None):
        self.ari = ari
        self.channel_id = channel_id
        self.caller_id = caller_id
        self.called_number = called_number
        self.call_id = f"call-{channel_id[:8]}"
        self.state = ConversationState(self.call_id, caller_id)
        self.bridge_id: str | None = None
        self.ext_media_id: str | None = None
        self.rtp_sock: RTPSocket | None = None
        self.rtp_port: int = 0
        self.transcript_log: list[str] = []
        self.available_slots: list[dict] = []
        self.started_at = datetime.utcnow()
        self.call_path = CallPath(self.call_id)
        # DTMF events from the main ARI loop are pushed into this queue
        self.dtmf_queue: asyncio.Queue = dtmf_queue or asyncio.Queue()
        self.vad = SileroVADEngine(
            threshold=settings.vad_threshold,
            min_silence_ms=settings.vad_min_silence_ms,
            speech_pad_ms=settings.vad_speech_pad_ms,
        )

    async def run(self):
        log.info("Call started", call_id=self.call_id, caller=self.caller_id)
        self.call_path.record("call_start", caller_id=self.caller_id, called=self.called_number)

        async with AsyncSessionLocal() as db:
            call_log = CallLog(
                call_id=self.call_id,
                caller_id=self.caller_id,
                called_number=self.called_number,
                started_at=self.started_at,
            )
            db.add(call_log)
            await db.commit()

        try:
            await self._setup_media()

            # ── VIP check ────────────────────────────────────────────
            vip_route = get_vip_route(self.caller_id)
            if vip_route:
                self.call_path.record("vip_detected", extension=vip_route.extension)
                msg_en = f"Welcome back. Connecting you to our team right away."
                await self._speak(msg_en, language="en")
                await asyncio.sleep(0.5)
                await self.ari.redirect_channel(self.channel_id, f"PJSIP/{vip_route.extension}")
                await self._save_call(disposition="transferred", transferred_to=vip_route.extension)
                return

            # ── Business hours / holiday gate ────────────────────────
            is_open = await _is_open()
            if not is_open:
                self.call_path.record("after_hours", mode=settings.after_hours_mode)
                await self._handle_after_hours()
                return

            # ── Normal call flow ─────────────────────────────────────
            await self._greet()
            await self._conversation_loop()

        except asyncio.CancelledError:
            log.info("Call cancelled", call_id=self.call_id)
            self.call_path.record("cancelled")
        except Exception as e:
            log.error("Call handler error", call_id=self.call_id, error=str(e), exc_info=True)
            self.call_path.record("error", error=str(e))
        finally:
            await self._teardown()

    # ── After-hours handler ───────────────────────────────────────────────────

    async def _handle_after_hours(self):
        """
        Called when the business is closed.
        Speaks a closed message, then branches on AFTER_HOURS_MODE.
        """
        tz = ZoneInfo(settings.business_timezone)
        now = datetime.now(tz)
        # Use a friendly hours description
        start_h = settings.business_hours_start
        end_h = settings.business_hours_end
        hours_str_en = f"{start_h}:00 AM to {end_h - 12 if end_h > 12 else end_h}:00 {'PM' if end_h >= 12 else 'AM'}"
        hours_str_es = f"{start_h}:00 AM a {end_h - 12 if end_h > 12 else end_h}:00 {'PM' if end_h >= 12 else 'AM'}"

        msg_en = (
            f"Thank you for calling {settings.business_name}. "
            f"Our office is currently closed. "
            f"Our business hours are Monday through Friday, {hours_str_en}."
        )
        msg_es = (
            f"Gracias por llamar a {settings.business_name}. "
            f"Nuestra oficina está cerrada en este momento. "
            f"Nuestro horario de atención es de lunes a viernes, de {hours_str_es}."
        )

        mode = settings.after_hours_mode
        lang = "en"  # default — we haven't detected caller lang yet

        if mode == "emergency":
            route = get_after_hours_route()
            msg_en += " If this is an emergency, please hold while I connect you."
            await self._speak(msg_en, language="en")
            await asyncio.sleep(1)
            await self.ari.redirect_channel(self.channel_id, f"PJSIP/{route.extension}")
            await self._save_call(disposition="after_hours", transferred_to=route.extension)

        elif mode == "voicemail":
            if settings.voicemail_enabled:
                msg_en += " Please leave a message after the tone and we will call you back next business day."
                await self._speak(msg_en, language="en")
                await self._record_voicemail()
            else:
                msg_en += " Please call back during business hours."
                await self._speak(msg_en, language="en")
                await self._save_call(disposition="after_hours")

        elif mode == "schedule":
            # Let the caller book a callback slot — enter the normal greeting flow
            msg_en += " You can schedule a callback appointment with me now."
            await self._speak(msg_en, language="en")
            await self._greet(after_hours=True)
            await self._conversation_loop(after_hours=True)

        else:  # callback (default)
            msg_en += " Please call back during our business hours or visit our website."
            await self._speak(msg_en, language="en")
            await self._save_call(disposition="after_hours")

    # ── Voicemail recording ───────────────────────────────────────────────────

    async def _record_voicemail(self):
        """
        Record caller audio for up to 120 seconds as a voicemail.
        Optionally transcribes with Whisper.
        Saves a VoicemailMessage record to the database.
        """
        import os
        import wave
        vm_dir = settings.voicemail_dir
        os.makedirs(vm_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"vm_{self.call_id}_{ts}.wav"
        filepath = os.path.join(vm_dir, filename)

        self.call_path.record("voicemail_start", path=filepath)
        await self._speak("Please leave your message now.", language="en")
        await asyncio.sleep(0.5)

        # Record up to 120 seconds
        audio_buffer = bytearray()
        loop = asyncio.get_event_loop()
        max_frames = int(120 * 1000 / FRAME_MS)
        no_data_count = 0
        max_silence = int(10_000 / FRAME_MS)  # 10 seconds trailing silence = end

        self.vad.reset()
        speech_started = False
        silence_after_speech = 0

        for _ in range(max_frames):
            data = await loop.run_in_executor(
                None, lambda: _recv_nonblocking(self.rtp_sock.sock, 2048)
            )
            if data and len(data) > RTP_HEADER_SIZE:
                payload = data[RTP_HEADER_SIZE:]
                no_data_count = 0
                vad_event = self.vad.process_chunk(payload)
                if vad_event and "start" in vad_event:
                    speech_started = True
                    silence_after_speech = 0
                if speech_started:
                    audio_buffer.extend(payload)
                if vad_event and "end" in vad_event and speech_started:
                    silence_after_speech += 1
                    if silence_after_speech > int(3000 / FRAME_MS):  # 3s silence after message
                        break
            else:
                await asyncio.sleep(0.02)
                no_data_count += 1
                if no_data_count >= max_silence:
                    break

        duration = len(audio_buffer) / (SAMPLE_RATE * 2)
        transcript = ""

        # Save as WAV
        try:
            with wave.open(filepath, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(bytes(audio_buffer))
        except Exception as e:
            log.error("Voicemail WAV write failed", error=str(e))
            filepath = None

        # Transcribe if enabled
        if settings.voicemail_transcribe and len(audio_buffer) >= BYTES_PER_FRAME * 5:
            try:
                result = await loop.run_in_executor(
                    None, transcribe_pcm, bytes(audio_buffer), SAMPLE_RATE, 1, None
                )
                transcript = result.text or ""
            except Exception as e:
                log.warning("Voicemail transcription failed", error=str(e))

        # Save to DB
        async with AsyncSessionLocal() as db:
            vm = VoicemailMessage(
                call_id=self.call_id,
                caller_id=self.caller_id,
                recorded_at=datetime.utcnow(),
                duration_sec=duration,
                audio_path=filepath,
                transcript=transcript,
                status="unread",
            )
            db.add(vm)
            await db.commit()

        await self._speak("Thank you. We will call you back next business day.", language="en")
        await self._save_call(disposition="voicemail")
        self.call_path.record("voicemail_saved", duration=duration, transcript=bool(transcript))

    # ── Greeting ──────────────────────────────────────────────────────────────

    async def _greet(self, after_hours: bool = False):
        """
        Greet in English first. After the caller responds, if they spoke
        Spanish we replay the greeting in Spanish and lock the call language.
        """
        greeting = self._build_greeting("en", after_hours=after_hours)
        await self._speak(greeting, language="en")

        # DTMF menu announcement (if enabled)
        if settings.dtmf_enabled and not after_hours:
            dtmf_map = _parse_dtmf_map()
            menu_parts = []
            if "1" in dtmf_map:
                menu_parts.append("press 1 for sales")
            if "2" in dtmf_map:
                menu_parts.append("press 2 for support")
            if "0" in dtmf_map:
                menu_parts.append("press 0 for the operator")
            if menu_parts:
                dtmf_msg = "Or if you prefer, " + ", or ".join(menu_parts) + "."
                await self._speak(dtmf_msg, language="en")

        self.call_path.record("greeted", lang="en", after_hours=after_hours)

        # Listen for the first response
        listen_result = await self._listen()

        if not listen_result:
            self.state.retry_count += 1
            self.call_path.record("no_speech_on_greeting")
            await self._speak("I'm sorry, I didn't catch that. How can I help you today?", language="en")
            return

        utterance, detected_lang = listen_result
        self.state.caller_lang = detected_lang
        self.state.lang_confirmed = True
        self.state.retry_count = 0

        log.info("Caller language detected", lang=detected_lang, call_id=self.call_id)
        self.call_path.record("language_detected", lang=detected_lang)

        if detected_lang != "en":
            greeting_localized = self._build_greeting(detected_lang, after_hours=after_hours)
            await self._speak(greeting_localized, language=detected_lang)

        self._first_utterance = (utterance, detected_lang)

    def _build_greeting(self, lang: str, after_hours: bool = False) -> str:
        if after_hours:
            greetings = {
                "en": (
                    f"I can schedule a callback appointment for you. "
                    f"There are no buttons to press — just speak to me naturally. "
                    f"What is your name and the reason for your call?"
                ),
                "es": (
                    f"Puedo programar una cita de devolución de llamada para usted. "
                    f"No hay botones que presionar — hableme con naturalidad. "
                    f"¿Cuál es su nombre y el motivo de su llamada?"
                ),
            }
        else:
            greetings = {
                "en": (
                    f"Thank you for calling {settings.business_name}, we are excited to speak with you. "
                    f"This is {settings.agent_name}, your virtual assistant. "
                    f"There are no buttons to press — just speak to me naturally and I will take care of you. "
                    f"How can I help you today?"
                ),
                "es": (
                    f"Gracias por llamar a {settings.business_name}, estamos muy contentos de hablar con usted. "
                    f"Le habla {settings.agent_name}, su asistente virtual. "
                    f"No hay botones que presionar — hábleme con naturalidad y yo me encargaré de usted. "
                    f"¿En qué le puedo ayudar hoy?"
                ),
            }
        return greetings.get(lang, greetings["en"])

    # ── Conversation loop ─────────────────────────────────────────────────────

    async def _conversation_loop(self, after_hours: bool = False):
        """Main conversation loop — listen, transcribe, respond, route."""
        max_turns = 10
        max_retries = settings.max_retries
        lang = self.state.caller_lang

        while self.state.turn_count < max_turns:

            # On the first turn, consume the utterance captured in _greet()
            if self.state.turn_count == 0 and hasattr(self, "_first_utterance"):
                listen_result = self._first_utterance
                del self._first_utterance
            else:
                # Check for DTMF digit before listening (non-blocking peek)
                if settings.dtmf_enabled:
                    digit = await self._check_dtmf()
                    if digit:
                        await self._handle_dtmf(digit)
                        return

                listen_result = await self._listen()

            # ── No speech handling ────────────────────────────────────
            if not listen_result:
                self.state.retry_count += 1
                self.call_path.record("no_speech", retry=self.state.retry_count)

                if self.state.retry_count >= max_retries:
                    # Max retries — transfer to operator
                    await self._operator_fallback("max_retries")
                    return

                # Retry prompt (bilingual)
                if self.state.turn_count == 0:
                    sorry = (
                        "Lo siento, no le escuché. ¿Puede repetir?" if lang == "es"
                        else "I'm sorry, I didn't catch that. Could you repeat?"
                    )
                else:
                    sorry = (
                        "Disculpe, no le escuché bien. ¿Puede intentarlo de nuevo?" if lang == "es"
                        else "I'm sorry, I didn't catch that. Could you try again?"
                    )
                await self._speak(sorry, language=lang)
                continue

            utterance, detected_lang = listen_result
            self.state.retry_count = 0  # Reset on successful speech

            # Language lock
            if not self.state.lang_confirmed:
                self.state.caller_lang = detected_lang
                lang = detected_lang
                if self.state.turn_count >= 1:
                    self.state.lang_confirmed = True

            self.transcript_log.append(f"Caller [{detected_lang}]: {utterance}")
            self.call_path.record("utterance", turn=self.state.turn_count, lang=detected_lang, text=utterance[:60])

            # ── Intent detection ──────────────────────────────────────
            if not self.state.intent or self.state.intent == "unknown":
                await detect_intent(utterance, self.state)

            # ── Unknown intent handling ───────────────────────────────
            if self.state.intent == "unknown":
                self.call_path.record("unknown_intent", consecutive=self.state.unknown_count)

                if self.state.unknown_count >= 2:
                    # Two unknowns in a row → operator
                    await self._operator_fallback("unknown_intent")
                    return

                # Reprompt
                rephrase = (
                    "No entendí del todo. ¿Puede decirme si desea hablar con alguien, "
                    "programar una cita o tiene una pregunta?" if lang == "es"
                    else "I didn't quite catch that. Are you looking to speak with someone, "
                         "schedule an appointment, or do you have a question?"
                )
                await self._speak(rephrase, language=lang)
                continue

            intent = self.state.intent

            # ── Schedule flow ─────────────────────────────────────────
            if intent == "schedule":
                self.call_path.record("intent_schedule")
                if not self.available_slots:
                    self.available_slots = await get_available_slots(num_slots=3)
                    slots_speech = slots_to_speech(self.available_slots)
                    if not self.state.caller_name:
                        prompt = (
                            f"Me encantaría programar una devolución de llamada. "
                            f"¿Puede darme su nombre y el mejor número para contactarle? {slots_speech}"
                            if lang == "es"
                            else f"I'd be happy to schedule a callback. "
                                 f"Could I get your name and the best number to reach you at? {slots_speech}"
                        )
                    else:
                        prompt = slots_speech
                    await self._speak(prompt, language=lang)
                    continue

                chosen_slot = parse_slot_choice(utterance, self.available_slots)
                if chosen_slot and self.state.caller_name:
                    event_id = await book_appointment(
                        caller_name=self.state.caller_name,
                        caller_phone=self.state.caller_phone,
                        start=chosen_slot["start"],
                        reason=self.state.reason or "",
                        call_id=self.call_id,
                    )
                    confirm = (
                        f"Perfecto. He programado su llamada para {chosen_slot['label']}. "
                        f"Le llamaremos al {self.state.caller_phone}. ¿Hay algo más en lo que pueda ayudarle?"
                        if lang == "es"
                        else f"Perfect! I've scheduled your callback for {chosen_slot['label']}. "
                             f"We'll call you at {self.state.caller_phone}. Is there anything else?"
                    )
                    await self._speak(confirm, language=lang)
                    await self._save_call(disposition="scheduled", appointment_id=event_id)
                    self.call_path.record("scheduled", slot=chosen_slot["label"])
                    break
                else:
                    context = f"Available slots: {[s['label'] for s in self.available_slots]}"
                    response = await generate_response(utterance, self.state, context)
                    await self._speak(response, language=lang)

            # ── Transfer flow ─────────────────────────────────────────
            elif intent == "transfer":
                async with AsyncSessionLocal() as db:
                    route = await get_route_for_intent(self.state.department, intent, db)

                extension = route.extension
                agent_lang = route.agent_lang
                self.call_path.record(
                    "transfer",
                    extension=extension,
                    department=self.state.department,
                    match_source=route.match_source,
                    caller_lang=lang,
                    agent_lang=agent_lang,
                )

                dept_name = self.state.department or "the right person"
                transfer_msg = (
                    f"Por supuesto. Le voy a comunicar con {dept_name} ahora mismo. Por favor espere."
                    if lang == "es"
                    else f"Of course! Let me transfer you to {dept_name} right now. Please hold."
                )
                await self._speak(transfer_msg, language=lang)
                await asyncio.sleep(1)

                need_relay = lang != agent_lang

                if need_relay:
                    agent_chan = await self.ari.dial_to_bridge(
                        extension, self.bridge_id, settings.asterisk_app_name
                    )
                    agent_channel_id = agent_chan["id"] if agent_chan else None
                    if agent_channel_id:
                        await asyncio.sleep(2)
                        relay = TranslationRelay(
                            ari=self.ari,
                            caller_channel_id=self.channel_id,
                            agent_channel_id=agent_channel_id,
                            bridge_id=self.bridge_id,
                            caller_lang=lang,
                            agent_lang=agent_lang,
                        )
                        asyncio.create_task(relay.run())
                        log.info("Translation relay started",
                                 caller_lang=lang, agent_lang=agent_lang, extension=extension)
                    else:
                        log.warning("dial_to_bridge failed, falling back to redirect")
                        await self.ari.redirect_channel(self.channel_id, f"PJSIP/{extension}")
                else:
                    await self.ari.redirect_channel(self.channel_id, f"PJSIP/{extension}")

                await self._save_call(disposition="transferred", transferred_to=extension)
                return

            # ── General conversation ──────────────────────────────────
            else:
                response = await generate_response(utterance, self.state)
                self.transcript_log.append(f"Agent [{lang}]: {response}")
                self.call_path.record("general_response", intent=intent, turn=self.state.turn_count)
                await self._speak(response, language=lang)

            # Natural farewell detection
            farewell_words = ["goodbye", "bye", "thank you", "that's all",
                              "adiós", "adios", "gracias", "hasta luego", "hasta pronto"]
            if any(word in utterance.lower() for word in farewell_words):
                farewell = (
                    "¡Gracias por llamar. Que tenga un buen día!"
                    if lang == "es"
                    else "Thank you for calling. Have a great day!"
                )
                await self._speak(farewell, language=lang)
                self.call_path.record("farewell")
                break

        await self._finalize_transcript()

    # ── DTMF helpers ──────────────────────────────────────────────────────────

    async def _check_dtmf(self) -> str | None:
        """Non-blocking check for a queued DTMF digit."""
        try:
            return self.dtmf_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def _handle_dtmf(self, digit: str):
        """Route the caller based on a DTMF keypress."""
        dtmf_map = _parse_dtmf_map()
        extension = dtmf_map.get(digit)
        lang = self.state.caller_lang

        self.call_path.record("dtmf", digit=digit, extension=extension)

        if not extension:
            await self._speak(
                "Esa opción no es válida. Le paso al operador." if lang == "es"
                else "That option isn't valid. Connecting you to the operator.",
                language=lang,
            )
            extension = settings.operator_extension

        await self._speak(
            f"Un momento, le comunico ahora mismo." if lang == "es"
            else "One moment, connecting you now.",
            language=lang,
        )
        await asyncio.sleep(0.5)
        await self.ari.redirect_channel(self.channel_id, f"PJSIP/{extension}")
        await self._save_call(disposition="transferred", transferred_to=extension)
        log.info("DTMF transfer", digit=digit, extension=extension)

    # ── Operator fallback ─────────────────────────────────────────────────────

    async def _operator_fallback(self, reason: str):
        """Transfer caller to operator after retries or intent failures."""
        lang = self.state.caller_lang
        self.call_path.record("operator_fallback", reason=reason)
        log.info("Operator fallback", call_id=self.call_id, reason=reason)

        msg = (
            "Permítame conectarle con un miembro de nuestro equipo que podrá ayudarle."
            if lang == "es"
            else "Let me connect you with a team member who can assist you better."
        )
        await self._speak(msg, language=lang)
        await asyncio.sleep(0.5)

        ext = settings.operator_extension
        await self.ari.redirect_channel(self.channel_id, f"PJSIP/{ext}")
        await self._save_call(disposition="transferred", transferred_to=ext)

    # ── Listen ────────────────────────────────────────────────────────────────

    async def _listen(self) -> tuple[str, str] | None:
        """
        Read audio from RTP until Silero VAD detects end-of-speech.
        Returns (english_transcript, detected_lang) or None on silence/timeout.
        """
        audio_buffer = bytearray()
        speech_started = False
        max_frames = int(MAX_UTTERANCE_SECONDS * 1000 / FRAME_MS)
        total_frames = 0
        no_data_count = 0
        # Use configured silence timeout
        max_initial_silence_frames = int(settings.silence_timeout_sec * 1000 / FRAME_MS)
        loop = asyncio.get_event_loop()

        self.vad.reset()

        while total_frames < max_frames:
            try:
                data = await loop.run_in_executor(
                    None, lambda: _recv_nonblocking(self.rtp_sock.sock, 2048)
                )
                if data and len(data) > RTP_HEADER_SIZE:
                    payload = data[RTP_HEADER_SIZE:]
                    no_data_count = 0
                    vad_event = self.vad.process_chunk(payload)

                    if vad_event and "start" in vad_event:
                        speech_started = True
                        log.debug("VAD: speech start", call_id=self.call_id)

                    if speech_started:
                        audio_buffer.extend(payload)

                    if vad_event and "end" in vad_event and speech_started:
                        log.debug("VAD: speech end", call_id=self.call_id,
                                  audio_bytes=len(audio_buffer))
                        break
                else:
                    await asyncio.sleep(0.02)
                    no_data_count += 1
                    if not speech_started and no_data_count >= max_initial_silence_frames:
                        break
            except Exception:
                await asyncio.sleep(0.02)

            total_frames += 1

        if len(audio_buffer) < BYTES_PER_FRAME * 5:
            return None

        result = await asyncio.get_event_loop().run_in_executor(
            None, transcribe_pcm, bytes(audio_buffer), SAMPLE_RATE, 1, None
        )

        if not result or not result.text:
            return None

        detected_lang = result.language
        english_text = result.text

        if detected_lang != "en":
            english_text, _ = await ensure_english(result.text, detected_lang)
            log.info("Translated caller utterance",
                     original=result.text[:60],
                     translated=english_text[:60],
                     lang=detected_lang)

        return english_text, detected_lang

    # ── Speak ─────────────────────────────────────────────────────────────────

    async def _speak(self, text: str, language: str = "en"):
        log.info("Speaking", text=text[:80], lang=language, call_id=self.call_id)
        self.transcript_log.append(f"Agent [{language}]: {text}")
        loop = asyncio.get_event_loop()
        pcm = await loop.run_in_executor(None, synthesize_pcm, text, language)
        if pcm and self.rtp_sock:
            self.rtp_sock.send_pcm(pcm)
            duration_seconds = len(pcm) / (SAMPLE_RATE * 2)
            await asyncio.sleep(duration_seconds + 0.2)

    # ── Media setup ───────────────────────────────────────────────────────────

    async def _setup_media(self):
        self.rtp_port = _allocate_rtp_port()
        self.rtp_sock = RTPSocket(settings.agent_rtp_host, self.rtp_port)

        bridge = await self.ari.create_bridge()
        self.bridge_id = bridge["id"]
        await self.ari.add_to_bridge(self.bridge_id, self.channel_id)

        rtp_advertise = settings.agent_rtp_advertise_host or settings.agent_rtp_host
        ext_host = f"{rtp_advertise}:{self.rtp_port}"
        ext_media = await self.ari.create_external_media(settings.asterisk_app_name, ext_host)
        self.ext_media_id = ext_media["id"]

        ast_rtp_addr = await self.ari.get_channel_var(self.ext_media_id, "UNICASTRTP_LOCAL_ADDRESS")
        ast_rtp_port = await self.ari.get_channel_var(self.ext_media_id, "UNICASTRTP_LOCAL_PORT")

        if ast_rtp_addr and ast_rtp_port:
            self.rtp_sock.asterisk_addr = (ast_rtp_addr, int(ast_rtp_port))
            log.info("RTP bridge established",
                     our_port=self.rtp_port,
                     asterisk_addr=self.rtp_sock.asterisk_addr)

        await self.ari.add_to_bridge(self.bridge_id, self.ext_media_id)
        self.call_path.record("media_ready", rtp_port=self.rtp_port)

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _save_call(self, disposition: str, transferred_to: str | None = None,
                          appointment_id: str | None = None):
        """Update the CallLog record with final state."""
        full_transcript = "\n".join(self.transcript_log)
        summary = await generate_call_summary(self.state, full_transcript)

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(select(CallLog).where(CallLog.call_id == self.call_id))
            cl = result.scalars().first()
            if cl:
                cl.transcript = full_transcript
                cl.intent = self.state.intent
                cl.intent_detail = self.state.department
                cl.disposition = disposition
                if transferred_to:
                    cl.transferred_to = transferred_to
                if appointment_id:
                    cl.appointment_id = appointment_id
                cl.notes = self.call_path.to_json()
                if summary:
                    cl.summary = summary
                await db.commit()

    async def _finalize_transcript(self):
        """Save transcript + call path for calls that ended in the conversation loop."""
        full_transcript = "\n".join(self.transcript_log)
        summary = await generate_call_summary(self.state, full_transcript)

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(select(CallLog).where(CallLog.call_id == self.call_id))
            cl = result.scalars().first()
            if cl:
                cl.transcript = full_transcript
                cl.intent = self.state.intent
                cl.intent_detail = self.state.department
                if not cl.disposition:
                    cl.disposition = "hangup"
                cl.notes = self.call_path.to_json()
                if summary:
                    cl.summary = summary
                await db.commit()

    # ── Teardown ──────────────────────────────────────────────────────────────

    async def _teardown(self):
        ended_at = datetime.utcnow()
        duration = (ended_at - self.started_at).total_seconds()
        self.call_path.record("teardown", duration=duration)

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(select(CallLog).where(CallLog.call_id == self.call_id))
            cl = result.scalars().first()
            if cl:
                cl.ended_at = ended_at
                cl.duration_seconds = duration
                # Persist call path if not already saved
                if not cl.notes:
                    cl.notes = self.call_path.to_json()
                await db.commit()

        if self.ext_media_id:
            try:
                await self.ari.hangup(self.ext_media_id)
            except Exception:
                pass

        if self.bridge_id:
            try:
                await self.ari.delete(f"/bridges/{self.bridge_id}")
            except Exception:
                pass

        if self.rtp_sock:
            self.rtp_sock.close()
            _release_rtp_port(self.rtp_port)

        log.info("Call ended", call_id=self.call_id, duration=duration)


# ── Port pool ────────────────────────────────────────────────────────────────

_port_pool: set[int] = set()
_port_lock = asyncio.Lock()


def _allocate_rtp_port() -> int:
    for port in range(settings.agent_rtp_port_start, settings.agent_rtp_port_end, 2):
        if port not in _port_pool:
            _port_pool.add(port)
            return port
    raise RuntimeError("No RTP ports available")


def _release_rtp_port(port: int):
    _port_pool.discard(port)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _recv_nonblocking(sock: socket.socket, size: int) -> bytes | None:
    try:
        data, addr = sock.recvfrom(size)
        return data
    except BlockingIOError:
        return None


# ── Main ARI event loop ───────────────────────────────────────────────────────

async def run_ari_agent():
    """
    Connect to Asterisk ARI via WebSocket and handle StasisStart events.
    Each call spawns a CallHandler in its own asyncio task.
    v1.2: also routes ChannelDtmfReceived events into per-call DTMF queues.
    """
    ari = ARIClient()
    await ari.start()

    ws_url = (
        f"ws://{settings.asterisk_host}:{settings.asterisk_ari_port}"
        f"/ari/events?api_key={settings.asterisk_ari_user}:{settings.asterisk_ari_password}"
        f"&app={settings.asterisk_app_name}&subscribeAll=false"
    )

    # channel_id → (CallHandler, asyncio.Task)
    active_calls: dict[str, tuple[CallHandler, asyncio.Task]] = {}

    log.info("Connecting to Asterisk ARI", url=ws_url)

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            log.info("ARI WebSocket connected")

            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue

                event = json.loads(msg.data)
                event_type = event.get("type")

                if event_type == "StasisStart":
                    channel = event["channel"]
                    channel_id = channel["id"]
                    caller_id = channel.get("caller", {}).get("number", "unknown")
                    args = event.get("args", [])
                    called_number = args[1] if len(args) > 1 else "unknown"

                    log.info("StasisStart", channel_id=channel_id, caller=caller_id)

                    dtmf_queue: asyncio.Queue = asyncio.Queue()
                    handler = CallHandler(ari, channel_id, caller_id, called_number, dtmf_queue)
                    task = asyncio.create_task(handler.run())
                    active_calls[channel_id] = (handler, task)

                elif event_type == "ChannelDtmfReceived":
                    # Route DTMF digit to the correct call's handler
                    channel_id = event.get("channel", {}).get("id")
                    digit = event.get("digit", "")
                    if channel_id in active_calls and digit:
                        handler, _ = active_calls[channel_id]
                        await handler.dtmf_queue.put(digit)
                        log.info("DTMF received", channel_id=channel_id, digit=digit)

                elif event_type == "StasisEnd":
                    channel_id = event.get("channel", {}).get("id")
                    if channel_id in active_calls:
                        _, task = active_calls[channel_id]
                        task.cancel()
                        del active_calls[channel_id]
                        log.info("StasisEnd", channel_id=channel_id)

                elif event_type == "ChannelHangupRequest":
                    channel_id = event.get("channel", {}).get("id")
                    if channel_id in active_calls:
                        _, task = active_calls[channel_id]
                        task.cancel()

    await ari.stop()


# ── Translation Relay ─────────────────────────────────────────────────────────

class TranslationRelay:
    """
    Real-time bidirectional translation relay for transferred calls.
    (Unchanged from v1.1 — see original docstring for full architecture notes.)
    """

    def __init__(
        self,
        ari: ARIClient,
        caller_channel_id: str,
        agent_channel_id: str,
        bridge_id: str,
        caller_lang: str,
        agent_lang: str = "en",
    ):
        self.ari              = ari
        self.caller_channel_id = caller_channel_id
        self.agent_channel_id  = agent_channel_id
        self.bridge_id         = bridge_id
        self.caller_lang       = caller_lang
        self.agent_lang        = agent_lang
        self._running          = True
        self._caller_snoop_id: str | None = None
        self._agent_snoop_id:  str | None = None
        self._caller_sock: RTPSocket | None = None
        self._agent_sock:  RTPSocket | None = None

    async def run(self):
        log.info("TranslationRelay starting",
                 caller_lang=self.caller_lang, agent_lang=self.agent_lang)
        try:
            caller_snoop = await self.ari.snoop_channel(
                self.caller_channel_id, app=settings.asterisk_app_name, spy="in", whisper="none"
            )
            agent_snoop = await self.ari.snoop_channel(
                self.agent_channel_id, app=settings.asterisk_app_name, spy="in", whisper="none"
            )

            if not caller_snoop or not agent_snoop:
                log.error("Failed to create snoop channels — relay aborted")
                return

            self._caller_snoop_id = caller_snoop["id"]
            self._agent_snoop_id  = agent_snoop["id"]

            caller_port = _allocate_rtp_port()
            agent_port  = _allocate_rtp_port()
            self._caller_sock = RTPSocket(settings.agent_rtp_host, caller_port)
            self._agent_sock  = RTPSocket(settings.agent_rtp_host, agent_port)
            rtp_advertise = settings.agent_rtp_advertise_host or settings.agent_rtp_host

            caller_ext = await self.ari.create_external_media(
                settings.asterisk_app_name, f"{rtp_advertise}:{caller_port}"
            )
            agent_ext = await self.ari.create_external_media(
                settings.asterisk_app_name, f"{rtp_advertise}:{agent_port}"
            )

            if caller_ext:
                await self.ari.add_to_bridge(self.bridge_id, caller_ext["id"])
                ast_addr = await self.ari.get_channel_var(caller_ext["id"], "UNICASTRTP_LOCAL_ADDRESS")
                ast_port = await self.ari.get_channel_var(caller_ext["id"], "UNICASTRTP_LOCAL_PORT")
                if ast_addr and ast_port:
                    self._caller_sock.asterisk_addr = (ast_addr, int(ast_port))

            if agent_ext:
                await self.ari.add_to_bridge(self.bridge_id, agent_ext["id"])
                ast_addr = await self.ari.get_channel_var(agent_ext["id"], "UNICASTRTP_LOCAL_ADDRESS")
                ast_port = await self.ari.get_channel_var(agent_ext["id"], "UNICASTRTP_LOCAL_PORT")
                if ast_addr and ast_port:
                    self._agent_sock.asterisk_addr = (ast_addr, int(ast_port))

            log.info("TranslationRelay sockets ready",
                     caller_port=caller_port, agent_port=agent_port)

            await asyncio.gather(
                self._translate_loop(
                    sock=self._caller_sock,
                    src_lang=self.caller_lang,
                    tgt_lang=self.agent_lang,
                    output_sock=self._agent_sock,
                    label="caller→agent",
                ),
                self._translate_loop(
                    sock=self._agent_sock,
                    src_lang=self.agent_lang,
                    tgt_lang=self.caller_lang,
                    output_sock=self._caller_sock,
                    label="agent→caller",
                ),
            )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("TranslationRelay.run error", error=str(e), exc_info=True)
        finally:
            await self._cleanup()

    async def _translate_loop(self, sock, src_lang, tgt_lang, output_sock, label):
        from llm.translate_engine import translate as do_translate

        vad = SileroVADEngine(
            threshold=settings.vad_threshold,
            min_silence_ms=settings.vad_min_silence_ms,
            speech_pad_ms=settings.vad_speech_pad_ms,
        )
        loop = asyncio.get_event_loop()
        log.info("Translation loop started", direction=label, src=src_lang, tgt=tgt_lang)

        while self._running:
            try:
                audio_buffer = bytearray()
                speech_started = False
                no_data_count = 0
                total_frames = 0
                max_frames = int(MAX_UTTERANCE_SECONDS * 1000 / FRAME_MS)
                max_silence = int(5000 / FRAME_MS)
                vad.reset()

                while total_frames < max_frames:
                    data = await loop.run_in_executor(
                        None, lambda: _recv_nonblocking(sock.sock, 2048)
                    )
                    if data and len(data) > RTP_HEADER_SIZE:
                        payload = data[RTP_HEADER_SIZE:]
                        no_data_count = 0
                        vad_event = vad.process_chunk(payload)
                        if vad_event and "start" in vad_event:
                            speech_started = True
                        if speech_started:
                            audio_buffer.extend(payload)
                        if vad_event and "end" in vad_event and speech_started:
                            break
                    else:
                        await asyncio.sleep(0.02)
                        no_data_count += 1
                        if not speech_started and no_data_count >= max_silence:
                            break
                    total_frames += 1

                if len(audio_buffer) < BYTES_PER_FRAME * 5:
                    await asyncio.sleep(0.1)
                    continue

                result = await loop.run_in_executor(
                    None, transcribe_pcm, bytes(audio_buffer), SAMPLE_RATE, 1, src_lang
                )
                if not result.text:
                    continue

                log.info("Relay transcribed", direction=label, lang=result.language, text=result.text[:60])

                translated = await do_translate(result.text, tgt_lang, source_lang=src_lang)
                pcm = await loop.run_in_executor(None, synthesize_pcm, translated, tgt_lang)
                if pcm and output_sock:
                    output_sock.send_pcm(pcm)
                    log.info("Relay played translation", direction=label, tgt=tgt_lang, text=translated[:60])

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("TranslationRelay._translate_loop error", direction=label, error=str(e))
                await asyncio.sleep(0.5)

        log.info("Translation loop stopped", direction=label)

    async def _cleanup(self):
        for snoop_id in [self._caller_snoop_id, self._agent_snoop_id]:
            if snoop_id:
                try:
                    await self.ari.hangup(snoop_id)
                except Exception:
                    pass
        for sock, port in [
            (self._caller_sock, getattr(self._caller_sock, "listen_port", None)),
            (self._agent_sock,  getattr(self._agent_sock,  "listen_port", None)),
        ]:
            if sock:
                sock.close()
            if port:
                _release_rtp_port(port)
        log.info("TranslationRelay cleaned up")

    def stop(self):
        self._running = False
