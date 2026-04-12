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
"""
import asyncio
import socket
import struct
import time
import aiohttp
import structlog
from datetime import datetime

from config import settings
from stt.whisper_engine import transcribe_pcm
from tts.piper_engine import synthesize_pcm
from llm.intent_engine import detect_intent, generate_response, ConversationState
from llm.translate_engine import ensure_english
from calendar.gcal import get_available_slots, book_appointment, slots_to_speech, parse_slot_choice
from routing.router import get_extension_for_intent
from database import AsyncSessionLocal, CallLog
from vad import SileroVADEngine

log = structlog.get_logger(__name__)

# RTP constants
RTP_HEADER_SIZE = 12
SAMPLE_RATE = 16000           # slin16
FRAME_MS = 20                 # 20ms frames
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000  # 320
BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2             # 640 bytes (PCM16)
MAX_UTTERANCE_SECONDS = 15   # Max recording per turn


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
        """Build a minimal RTP header (RFC 3550)."""
        # V=2, P=0, X=0, CC=0, M=0, PT=11 (L16 mono)
        header = struct.pack(
            "!BBHII",
            0x80,               # V=2, no padding, no extension, CC=0
            11,                 # Payload type 11 = L16/16000
            self._seq & 0xFFFF,
            self._timestamp,
            self._ssrc,
        )
        self._seq += 1
        self._timestamp += SAMPLES_PER_FRAME
        return header

    def send_pcm(self, pcm_bytes: bytes):
        """Packetize PCM16 into RTP frames and send to Asterisk."""
        if not self.asterisk_addr:
            return
        loop = asyncio.get_event_loop()
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
        """Transfer caller to an extension via PJSIP."""
        await self.post(f"/channels/{channel_id}/redirect", json={"endpoint": endpoint})

    async def hangup(self, channel_id: str, reason: str = "normal"):
        await self.delete(f"/channels/{channel_id}?reason={reason}")

    async def play_silence(self, channel_id: str, duration_ms: int = 500):
        await self.post(f"/channels/{channel_id}/play", json={
            "media": f"tone:silence/{duration_ms}"
        })


class CallHandler:
    """
    Handles a single inbound call end-to-end.
    Spawned per call from the main ARI event loop.
    """

    def __init__(self, ari: ARIClient, channel_id: str, caller_id: str, called_number: str):
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
        self.vad = SileroVADEngine(
            threshold=settings.vad_threshold,
            min_silence_ms=settings.vad_min_silence_ms,
            speech_pad_ms=settings.vad_speech_pad_ms,
        )

    async def run(self):
        log.info("Call started", call_id=self.call_id, caller=self.caller_id)
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
            await self._greet()
            await self._conversation_loop()
        except asyncio.CancelledError:
            log.info("Call cancelled", call_id=self.call_id)
        except Exception as e:
            log.error("Call handler error", call_id=self.call_id, error=str(e), exc_info=True)
        finally:
            await self._teardown()

    async def _setup_media(self):
        """Create bridge + ExternalMedia channel, get RTP port."""
        # Allocate a UDP port
        self.rtp_port = _allocate_rtp_port()
        self.rtp_sock = RTPSocket(settings.agent_rtp_host, self.rtp_port)

        # Create mixing bridge
        bridge = await self.ari.create_bridge()
        self.bridge_id = bridge["id"]

        # Add caller to bridge
        await self.ari.add_to_bridge(self.bridge_id, self.channel_id)

        # Create ExternalMedia channel pointing to our RTP socket.
        # Use advertise host if set (needed for Docker bridge mode where
        # bind address 0.0.0.0 can't be used as a routable destination).
        rtp_advertise = settings.agent_rtp_advertise_host or settings.agent_rtp_host
        ext_host = f"{rtp_advertise}:{self.rtp_port}"
        ext_media = await self.ari.create_external_media(settings.asterisk_app_name, ext_host)
        self.ext_media_id = ext_media["id"]

        # Get Asterisk's RTP address/port for this ExternalMedia channel
        ast_rtp_addr = await self.ari.get_channel_var(self.ext_media_id, "UNICASTRTP_LOCAL_ADDRESS")
        ast_rtp_port = await self.ari.get_channel_var(self.ext_media_id, "UNICASTRTP_LOCAL_PORT")

        if ast_rtp_addr and ast_rtp_port:
            self.rtp_sock.asterisk_addr = (ast_rtp_addr, int(ast_rtp_port))
            log.info("RTP bridge established",
                     our_port=self.rtp_port,
                     asterisk_addr=self.rtp_sock.asterisk_addr)

        # Add ExternalMedia to bridge
        await self.ari.add_to_bridge(self.bridge_id, self.ext_media_id)

    async def _greet(self):
        # Bilingual greeting — spoken in both English and Spanish so the
        # caller hears their language right away, before we detect it.
        greeting_en = (
            f"Thank you for calling {settings.business_name}. "
            f"This is {settings.agent_name}. How can I help you today?"
        )
        greeting_es = (
            f"Gracias por llamar a {settings.business_name}. "
            f"Le habla {settings.agent_name}. \u00bfEn qu\u00e9 le puedo ayudar?"
        )
        await self._speak(greeting_en, language="en")
        await self._speak(greeting_es, language="es")

    async def _conversation_loop(self):
        """Main conversation loop — listen, transcribe, respond, route."""
        max_turns = 10
        while self.state.turn_count < max_turns:
            # Listen for caller utterance
            listen_result = await self._listen()
            if not listen_result:
                if self.state.turn_count == 0:
                    lang = self.state.caller_lang
                    sorry = "Lo siento, no le escuché. ¿Puede repetir?" if lang == "es" else "I\'m sorry, I didn\'t catch that. Could you repeat?"
                    await self._speak(sorry, language=lang)
                    continue
                break

            utterance, detected_lang = listen_result

            # Track caller language — lock in after 2 consistent turns
            if not self.state.lang_confirmed:
                self.state.caller_lang = detected_lang
                if self.state.turn_count >= 1:
                    self.state.lang_confirmed = True
                    log.info("Caller language confirmed", lang=detected_lang, call_id=self.call_id)

            self.transcript_log.append(f"Caller [{detected_lang}]: {utterance}")

            # First pass: detect intent (utterance is already in English)
            if not self.state.intent or self.state.intent == "unknown":
                intent_result = await detect_intent(utterance, self.state)
            else:
                intent_result = {"intent": self.state.intent, "department": self.state.department}

            intent = self.state.intent

            # ── Schedule flow ────────────────────────────────────────
            if intent == "schedule":
                if not self.available_slots:
                    self.available_slots = await get_available_slots(num_slots=3)
                    slots_speech = slots_to_speech(self.available_slots)

                    # Also try to get caller name
                    if not self.state.caller_name:
                        name_prompt = f"I'd be happy to schedule a callback. Could I get your name and the best number to reach you at? {slots_speech}"
                        await self._speak(name_prompt, language=self.state.caller_lang)
                    else:
                        await self._speak(slots_speech, language=self.state.caller_lang)
                    continue

                # Try to match what they said to a slot
                chosen_slot = parse_slot_choice(utterance, self.available_slots)

                if chosen_slot and self.state.caller_name:
                    event_id = await book_appointment(
                        caller_name=self.state.caller_name,
                        caller_phone=self.state.caller_phone,
                        start=chosen_slot["start"],
                        reason=self.state.reason or "",
                        call_id=self.call_id,
                    )
                    confirm_msg = (
                        f"Perfect! I've scheduled your callback for {chosen_slot['label']}. "
                        f"We'll call you at {self.state.caller_phone}. "
                        f"Is there anything else I can help you with?"
                    )
                    await self._speak(confirm_msg, language=self.state.caller_lang)

                    async with AsyncSessionLocal() as db:
                        from sqlalchemy import select
                        result = await db.execute(
                            select(CallLog).where(CallLog.call_id == self.call_id)
                        )
                        cl = result.scalars().first()
                        if cl:
                            cl.appointment_id = event_id
                            cl.disposition = "scheduled"
                            await db.commit()
                    break
                else:
                    # Collect more info via LLM
                    context = f"Available slots: {[s['label'] for s in self.available_slots]}"
                    response = await generate_response(utterance, self.state, context)
                    await self._speak(response, language=self.state.caller_lang)

            # ── Transfer flow ────────────────────────────────────────
            elif intent == "transfer":
                async with AsyncSessionLocal() as db:
                    extension = await get_extension_for_intent(
                        self.state.department, intent, db
                    )

                dept_name = self.state.department or "the right person"
                transfer_en = f"Of course! Let me transfer you to {dept_name} right now. Please hold."
                await self._speak(transfer_en, language=self.state.caller_lang)
                await asyncio.sleep(1)

                # Start translation relay if caller speaks a different language
                if self.state.caller_lang != "en":
                    relay = TranslationRelay(
                        ari=self.ari,
                        channel_id=self.channel_id,
                        bridge_id=self.bridge_id,
                        caller_lang=self.state.caller_lang,
                        rtp_sock=self.rtp_sock,
                    )
                    asyncio.create_task(relay.run())
                    log.info("Translation relay started", caller_lang=self.state.caller_lang)

                # Transfer the caller to the target extension
                await self.ari.redirect_channel(
                    self.channel_id, f"PJSIP/{extension}"
                )

                async with AsyncSessionLocal() as db:
                    from sqlalchemy import select
                    result = await db.execute(
                        select(CallLog).where(CallLog.call_id == self.call_id)
                    )
                    cl = result.scalars().first()
                    if cl:
                        cl.disposition = "transferred"
                        cl.transferred_to = extension
                        cl.intent = "transfer"
                        cl.intent_detail = self.state.department
                        await db.commit()
                return  # Done — call is transferred

            # ── General conversation ─────────────────────────────────
            else:
                response = await generate_response(utterance, self.state)
                self.transcript_log.append(f"Agent [{self.state.caller_lang}]: {response}")
                await self._speak(response, language=self.state.caller_lang)

            # Natural end-of-call detection
            farewell_words = ["goodbye", "bye", "thank you", "that's all",
                              "adiós", "adios", "gracias", "hasta luego"]
            if any(word in utterance.lower() for word in farewell_words):
                farewell = ("¡Gracias por llamar. Que tenga un buen día!"
                            if self.state.caller_lang == "es"
                            else "Thank you for calling. Have a great day!")
                await self._speak(farewell, language=self.state.caller_lang)
                break

        # Save final transcript
        full_transcript = "\n".join(self.transcript_log)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(CallLog).where(CallLog.call_id == self.call_id)
            )
            cl = result.scalars().first()
            if cl:
                cl.transcript = full_transcript
                cl.intent = self.state.intent
                cl.intent_detail = self.state.department
                if not cl.disposition:
                    cl.disposition = "hangup"
                await db.commit()

    async def _listen(self) -> str:
        """
        Read audio from the RTP socket until Silero VAD detects end-of-speech.

        Flow:
          1. Receive RTP packets, strip header, accumulate PCM payload.
          2. Feed each payload chunk to SileroVADEngine.process_chunk().
          3. On {"start": ...}  → caller began speaking; start recording.
          4. On {"end": ...}   → caller stopped; break and transcribe.
          5. Safety valve: MAX_UTTERANCE_SECONDS hard cap.

        Returns transcribed text, or "" if nothing was captured.
        """
        audio_buffer = bytearray()
        speech_started = False
        max_frames = int(MAX_UTTERANCE_SECONDS * 1000 / FRAME_MS)
        total_frames = 0
        no_data_count = 0
        # Allow up to 5 seconds of pure silence before giving up
        # (caller may have hung up or isn't speaking yet).
        max_initial_silence_frames = int(5000 / FRAME_MS)  # 250 frames @ 20ms
        loop = asyncio.get_event_loop()

        # Reset VAD state for this new listening turn
        self.vad.reset()

        while total_frames < max_frames:
            try:
                data = await loop.run_in_executor(
                    None,
                    lambda: _recv_nonblocking(self.rtp_sock.sock, 2048)
                )
                if data and len(data) > RTP_HEADER_SIZE:
                    payload = data[RTP_HEADER_SIZE:]
                    no_data_count = 0

                    # Feed to Silero VAD
                    vad_event = self.vad.process_chunk(payload)

                    if vad_event and "start" in vad_event:
                        speech_started = True
                        log.debug("VAD: speech start", call_id=self.call_id)

                    # Only record audio once speech has been detected
                    if speech_started:
                        audio_buffer.extend(payload)

                    if vad_event and "end" in vad_event and speech_started:
                        log.debug("VAD: speech end", call_id=self.call_id,
                                  audio_bytes=len(audio_buffer))
                        break
                else:
                    await asyncio.sleep(0.02)
                    no_data_count += 1
                    # If we never got speech and silence is long, give up
                    if not speech_started and no_data_count >= max_initial_silence_frames:
                        break

            except Exception:
                await asyncio.sleep(0.02)

            total_frames += 1

        # Need a minimum amount of audio to attempt transcription
        if len(audio_buffer) < BYTES_PER_FRAME * 5:
            return ""

        # Whisper transcription with language auto-detection
        result = await asyncio.get_event_loop().run_in_executor(
            None, transcribe_pcm, bytes(audio_buffer), SAMPLE_RATE, 1, None
        )

        if not result.text:
            return None

        detected_lang = result.language
        english_text = result.text

        # Translate to English for intent detection if needed
        if detected_lang != "en":
            english_text, _ = await ensure_english(result.text, detected_lang)
            log.info("Translated caller utterance",
                     original=result.text[:60],
                     translated=english_text[:60],
                     lang=detected_lang)

        return english_text, detected_lang

    async def _speak(self, text: str, language: str = "en"):
        """Synthesize text with Piper TTS and inject audio back into the call."""
        log.info("Speaking", text=text[:80], lang=language, call_id=self.call_id)
        self.transcript_log.append(f"Agent [{language}]: {text}")

        loop = asyncio.get_event_loop()
        pcm = await loop.run_in_executor(None, synthesize_pcm, text, language)

        if pcm and self.rtp_sock:
            self.rtp_sock.send_pcm(pcm)
            # Wait for audio to play before listening again
            duration_seconds = len(pcm) / (SAMPLE_RATE * 2)
            await asyncio.sleep(duration_seconds + 0.2)

    async def _teardown(self):
        """Clean up Asterisk channels and local resources."""
        ended_at = datetime.utcnow()
        duration = (ended_at - self.started_at).total_seconds()

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(CallLog).where(CallLog.call_id == self.call_id)
            )
            cl = result.scalars().first()
            if cl:
                cl.ended_at = ended_at
                cl.duration_seconds = duration
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
    """
    ari = ARIClient()
    await ari.start()

    ws_url = (
        f"ws://{settings.asterisk_host}:{settings.asterisk_ari_port}"
        f"/ari/events?api_key={settings.asterisk_ari_user}:{settings.asterisk_ari_password}"
        f"&app={settings.asterisk_app_name}&subscribeAll=false"
    )

    active_calls: dict[str, asyncio.Task] = {}

    log.info("Connecting to Asterisk ARI", url=ws_url)

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            log.info("ARI WebSocket connected")

            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue

                import json
                event = json.loads(msg.data)
                event_type = event.get("type")

                if event_type == "StasisStart":
                    channel = event["channel"]
                    channel_id = channel["id"]
                    caller_id = channel.get("caller", {}).get("number", "unknown")
                    args = event.get("args", [])
                    called_number = args[1] if len(args) > 1 else "unknown"

                    log.info("StasisStart", channel_id=channel_id, caller=caller_id)

                    handler = CallHandler(ari, channel_id, caller_id, called_number)
                    task = asyncio.create_task(handler.run())
                    active_calls[channel_id] = task

                elif event_type == "StasisEnd":
                    channel_id = event.get("channel", {}).get("id")
                    if channel_id in active_calls:
                        active_calls[channel_id].cancel()
                        del active_calls[channel_id]
                        log.info("StasisEnd", channel_id=channel_id)

                elif event_type == "ChannelHangupRequest":
                    channel_id = event.get("channel", {}).get("id")
                    if channel_id in active_calls:
                        active_calls[channel_id].cancel()

    await ari.stop()


# ── Translation Relay ─────────────────────────────────────────────────────────

class TranslationRelay:
    """
    Real-time bidirectional translation relay for transferred calls.

    When a Spanish-speaking caller is transferred to an English-speaking
    call taker, this relay intercepts the RTP audio in both directions:

      Caller  (ES audio) → Whisper → translate ES→EN → Piper EN → Call taker
      Call taker (EN audio) → Whisper → translate EN→ES → Piper ES → Caller

    Both parties hear their own language. The relay runs as a background
    asyncio task until the call ends (StasisEnd / channel hangup).
    """

    def __init__(
        self,
        ari: ARIClient,
        channel_id: str,
        bridge_id: str,
        caller_lang: str,
        rtp_sock: RTPSocket,
        agent_lang: str = "en",
    ):
        self.ari = ari
        self.channel_id = channel_id
        self.bridge_id = bridge_id
        self.caller_lang = caller_lang
        self.agent_lang = agent_lang
        self.rtp_sock = rtp_sock
        self._running = True

    async def run(self):
        """
        Main relay loop. Runs concurrently with the transferred call.
        Listens on the existing RTP socket (which stays open after transfer),
        translates each utterance, and plays the translation back into the bridge.
        """
        log.info("TranslationRelay running",
                 caller_lang=self.caller_lang,
                 agent_lang=self.agent_lang)

        vad = SileroVADEngine(
            threshold=settings.vad_threshold,
            min_silence_ms=settings.vad_min_silence_ms,
            speech_pad_ms=settings.vad_speech_pad_ms,
        )

        while self._running:
            try:
                audio_buffer = bytearray()
                speech_started = False
                no_data_count = 0
                total_frames = 0
                max_frames = int(MAX_UTTERANCE_SECONDS * 1000 / FRAME_MS)
                max_silence = int(5000 / FRAME_MS)
                loop = asyncio.get_event_loop()
                vad.reset()

                # ── Listen for one utterance ──────────────────────────
                while total_frames < max_frames:
                    data = await loop.run_in_executor(
                        None,
                        lambda: _recv_nonblocking(self.rtp_sock.sock, 2048)
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

                # ── Transcribe with language detection ────────────────
                result = await loop.run_in_executor(
                    None, transcribe_pcm, bytes(audio_buffer), SAMPLE_RATE, 1, None
                )

                if not result.text:
                    continue

                src_lang = result.language
                src_text = result.text

                # Determine translation direction based on who spoke
                if src_lang == self.caller_lang:
                    # Caller spoke — translate to agent language for the call taker
                    tgt_lang = self.agent_lang
                elif src_lang == self.agent_lang:
                    # Call taker spoke — translate to caller language
                    tgt_lang = self.caller_lang
                else:
                    # Unknown speaker — skip
                    continue

                log.info("Relay translating",
                         src_lang=src_lang,
                         tgt_lang=tgt_lang,
                         text=src_text[:60])

                # ── Translate ─────────────────────────────────────────
                from llm.translate_engine import translate
                translated = await translate(src_text, tgt_lang, source_lang=src_lang)

                # ── Synthesize and play into the bridge ───────────────
                pcm = await loop.run_in_executor(
                    None, synthesize_pcm, translated, tgt_lang
                )
                if pcm and self.rtp_sock:
                    self.rtp_sock.send_pcm(pcm)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("TranslationRelay error", error=str(e))
                await asyncio.sleep(0.5)

        log.info("TranslationRelay stopped")

    def stop(self):
        self._running = False
