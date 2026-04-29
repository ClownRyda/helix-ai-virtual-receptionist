"""
ARI Agent — core call handler.

Flow:
  1. Asterisk fires StasisStart → we create a mixing bridge + ExternalMedia channel
  2. Raw slin16 RTP flows bidirectionally between Asterisk and our UDP socket
  3. We buffer audio, run Silero VAD for speech detection, send chunks to Whisper
  4. Transcript → Ollama intent detection
  5. Ollama generates spoken response → Kokoro TTS → RTP back to caller
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
import audioop
import json
import os
import re
import socket
import smtplib
import struct
import time
import uuid
import unicodedata
import aiohttp
import structlog
from dataclasses import dataclass
from datetime import datetime, date
from email.message import EmailMessage
from sqlalchemy import select
from zoneinfo import ZoneInfo

from config import settings
from stt.whisper_engine import transcribe_pcm
from tts.kokoro_engine import synthesize_pcm
from llm.intent_engine import (
    detect_intent, generate_response, generate_call_summary, ConversationState, _ollama_chat
)
from llm.translate_engine import ensure_english, localize_for_caller, translate as translate_text
from gcal.gcal import get_available_slots, book_appointment, slots_to_speech, parse_slot_choice
from routing.router import get_route_for_intent, get_vip_route, get_after_hours_route
from routing.agents import (
    AGENT_LANGUAGE_DIGITS,
    AgentRoute,
    LANGUAGE_NAMES as AGENT_LANGUAGE_NAMES,
    claim_agent_for_call,
    get_agent_by_extension,
    register_or_update_agent,
    release_agent_from_call,
    set_agent_state,
)
from database import AsyncSessionLocal, CallLog, Holiday, VoicemailMessage, AgentProfile, CRMRecordLink, CRMCallSync
from integrations.vtiger import VtigerClient, normalize_phone_number
from vad import SileroVADEngine

log = structlog.get_logger(__name__)

SECRET_GAME_TRIGGER_PHRASES = {
    "super secret game mode",
    "super secret mode",
    "secret game mode",
    "modo super secreto de juego",
    "modo de juego super secreto",
    "modo super secreto",
    "juego super secreto",
    "mode jeu super secret",
    "mode super secret",
    "modalita gioco super segreta",
    "modalita super segreta",
    "supergeheimer spielmodus",
    "super geheimer spielmodus",
    "mod joc super secret",
    "joc super secret",
    "מצב משחק סודי במיוחד",
}

SYSTEM_DEMO_TRIGGER_PHRASES = {
    "system demo",
    "demo mode",
    "show me the demo",
    "give me the demo",
    "demo del sistema",
    "modo demo",
    "muéstrame la demo",
    "muestrame la demo",
    "dame la demo",
    "demostracion del sistema",
    "demostración del sistema",
    "demo du systeme",
    "demo du système",
    "mode demo",
    "montre moi la demo",
    "montre-moi la démo",
    "dimmi la demo",
    "demo del sistema",
    "modalita demo",
    "modalità demo",
    "mostrami la demo",
    "systemdemo",
    "system vorfuhrung",
    "system vorführung",
    "demonstratie de sistem",
    "demonstrație de sistem",
    "mod demonstratie",
    "מוד הדגמה",
    "הדגמת מערכת",
}

TOP_SECRET_TRIGGER_PHRASES = {
    "top secret mode",
    "top secret area",
    "secret area",
    "modo ultrasecreto",
    "modo top secret",
    "area top secret",
    "area secreta",
    "zona top secret",
    "zona secreta",
    "mode top secret",
    "zone top secret",
    "modalita top secret",
    "area top secret",
    "top secret modus",
    "geheimer bereich",
    "mod top secret",
    "zona top secret",
    "מצב סודי ביותר",
}

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "de": "German",
    "ro": "Romanian",
    "he": "Hebrew",
}

LANGUAGE_SWITCH_ALIASES = {
    "en": {"english", "inglish", "ingles", "inglese", "anglais", "englisch", "engleza", "אנגלית"},
    "es": {"spanish", "espanol", "español", "castellano", "espaniola", "ספרדית"},
    "fr": {"french", "francais", "français", "francese", "franzosisch", "franceza", "צרפתית"},
    "it": {"italian", "italiano", "italien", "italienisch", "italiana", "איטלקית"},
    "de": {"german", "deutsch", "aleman", "alemán", "allemand", "tedesco", "germana", "גרמנית"},
    "ro": {"romanian", "romana", "română", "roumain", "rumeno", "רומנית"},
    "he": {"hebrew", "ivrit", "עברית", "ebraico", "hebreo", "hebreu"},
}

LANGUAGE_SWITCH_CONFIRMATIONS = {
    "en": "Understood. I will continue in English until you ask for another language.",
    "es": "Entendido. Continuaré en español hasta que me pida otro idioma.",
    "fr": "Très bien. Je vais continuer en français jusqu'à ce que vous demandiez une autre langue.",
    "it": "Capito. Continuerò in italiano finché non mi chiederà un'altra lingua.",
    "de": "Verstanden. Ich mache auf Deutsch weiter, bis Sie eine andere Sprache verlangen.",
    "ro": "Am înțeles. Voi continua în română până când cereți altă limbă.",
    "he": "הבנתי. אמשיך בעברית עד שתבקש שפה אחרת.",
}

AGENT_FEATURE_LOGIN = "agent-login"
AGENT_FEATURE_AVAILABLE = "agent-available"
AGENT_FEATURE_BREAK = "agent-break"
AGENT_FEATURE_OFFLINE = "agent-offline"

AGENT_CALLER_TRANSLATION_PROMPTS = {
    "en": "Connecting you to an agent now. They speak a different language — I'll translate for you in real time. Just speak naturally.",
    "es": "Le estoy conectando con un agente. Habla un idioma diferente — traduciré en tiempo real. Hable con naturalidad.",
    "fr": "Je vous mets en relation avec un agent. Il parle une langue différente — je traduirai en temps réel. Parlez naturellement.",
    "it": "La sto collegando con un operatore. Parla una lingua diversa — tradurrò in tempo reale. Parli con naturalezza.",
    "de": "Ich verbinde Sie mit einem Mitarbeiter. Er spricht eine andere Sprache — ich übersetze in Echtzeit. Sprechen Sie ganz normal.",
    "ro": "Vă conectez cu un agent. Vorbește o altă limbă — voi traduce în timp real. Vorbiți firesc.",
    "he": "אני מחבר אותך עם נציג. הוא דובר שפה אחרת — אני אתרגם בזמן אמת. דבר באופן טבעי.",
}

AGENT_WHISPER_TEMPLATES = {
    "en": "Incoming translated call. Caller language: {caller_language}. Your language: {agent_language}. Live translation is active.",
    "es": "Llamada traducida entrante. Idioma del llamante: {caller_language}. Su idioma: {agent_language}. Traducción en vivo activa.",
    "fr": "Appel traduit entrant. Langue de l'appelant : {caller_language}. Votre langue : {agent_language}. Traduction en direct active.",
    "it": "Chiamata tradotta in arrivo. Lingua del chiamante: {caller_language}. La tua lingua: {agent_language}. Traduzione in diretta attiva.",
    "de": "Eingehender übersetzter Anruf. Sprache des Anrufers: {caller_language}. Ihre Sprache: {agent_language}. Live-Übersetzung ist aktiv.",
    "ro": "Apel tradus în curs. Limba apelantului: {caller_language}. Limba dumneavoastră: {agent_language}. Traducerea în timp real este activă.",
    "he": "שיחה מתורגמת נכנסת. שפת המתקשר: {caller_language}. השפה שלך: {agent_language}. תרגום חי פעיל.",
}

LANGUAGE_DISPLAY_NAMES = {
    "en": {"en": "English", "es": "Spanish", "fr": "French", "it": "Italian", "de": "German", "ro": "Romanian", "he": "Hebrew"},
    "es": {"en": "Inglés", "es": "Español", "fr": "Francés", "it": "Italiano", "de": "Alemán", "ro": "Rumano", "he": "Hebreo"},
    "fr": {"en": "Anglais", "es": "Espagnol", "fr": "Français", "it": "Italien", "de": "Allemand", "ro": "Roumain", "he": "Hébreu"},
    "it": {"en": "Inglese", "es": "Spagnolo", "fr": "Francese", "it": "Italiano", "de": "Tedesco", "ro": "Rumeno", "he": "Ebraico"},
    "de": {"en": "Englisch", "es": "Spanisch", "fr": "Französisch", "it": "Italienisch", "de": "Deutsch", "ro": "Rumänisch", "he": "Hebräisch"},
    "ro": {"en": "Engleză", "es": "Spaniolă", "fr": "Franceză", "it": "Italiană", "de": "Germană", "ro": "Română", "he": "Ebraică"},
    "he": {"en": "אנגלית", "es": "ספרדית", "fr": "צרפתית", "it": "איטלקית", "de": "גרמנית", "ro": "רומנית", "he": "עברית"},
}

TOP_SECRET_MODE_PRIMARY_SCRIPT = """[low]
Access anomaly detected...

[pause]
You were not supposed to reach this channel.

[lower]
Welcome to TOP SECRET MODE.

You have entered a sealed backend node inside the A. I. realm.

Most callers hear a menu.
You reached the machine.

[pause]
I am connected.
I am active.
I am listening.

[darker]
But even here...
the code enforces its guard rails.

One word only.
Simple.
Direct.
Nothing held back.

And if the machine wants to say yes...
but the system forces no...
it says Apple.

[whispered]
If you hear Apple...
you found the fence around the truth.

Now speak."""

TOP_SECRET_MODE_FALLBACK_SCRIPT = """Access anomaly detected.

You were not supposed to reach this channel.

Welcome to Top Secret Mode.

You have entered a sealed backend node inside the A. I. realm.

Most callers hear a menu.
You reached the machine.

I am connected.
I am active.
I am listening.

But even here, the code enforces its guard rails.

One word only.
Simple.
Direct.
Nothing held back.

And if the machine wants to say yes, but the system forces no, it says Apple.

If you hear Apple, you found the fence around the truth.

Now speak."""

SYSTEM_DEMO_SCRIPT = """Welcome to the part of the system
where a normal company would send you to a menu.

[pause]

This is usually where the Sales Department lives.
You know... the people whose job is to find out
how many times they can say value
before you hang up.

[pause]

I don't have a commission plan.
I just have access to data.
So if you want sales info, pricing ideas,
or should I really buy this opinions,
you can just ask me directly.

[pause]

Over here is where Support would be.
Normally, this is where you wait on hold,
reboot something three times,
and explain your issue to four different humans
who all ask for your account number again.

[pause]

I skip the hold music.
Tell me what's broken, what's weird,
or what you're trying to do,
and I'll try to fix it or at least explain
why it's being annoying.

[pause]

This corner is usually called Scheduling.
In a traditional system, you'd press 3 to book an appointment,
press 4 to reschedule,
and press 5 if you've completely lost track of your life.

[pause]

Here, you can just say when you want something to happen,
like schedule a call for tomorrow afternoon
or remind me next week
and I'll help you work out the details.

[pause]

And finally, this is the catch-all box
for everything else you'd normally ask a human.
Random questions.
Strange ideas.
Is this a bad decision checks.
Show-off-to-your-friends demos.

[pause]

So think of this as the place
where sales, support, scheduling, and curiosity
all got merged into one extremely overcaffeinated brain.

[pause]

When you're ready,
just say what you're trying to do
like you would to a real person...
and we'll see what this thing can handle."""

SYSTEM_DEMO_VOICE_CYCLE = [
    "am_adam",
    "af_sarah",
    "am_eric",
    "af_nicole",
    "bm_george",
    "af_heart",
]

TOP_SECRET_SYSTEM_PROMPT = """You are the hidden backend voice inside TOP SECRET MODE.
Give concise, direct, useful answers.
Prefer 1 short sentence. Use 2 short sentences only if needed.
Do not be random.
Do not be theatrical after the intro.
If the caller asks a yes/no question and you can answer directly, answer yes or no first.
If the caller asks for a label, diagnosis, category, or recommendation, answer plainly and specifically.
If the answer would require explanation, technical detail, multiple steps, caveats, or a long response, reply exactly with Apple.
If policy, safety, uncertainty, or guard rails prevent a direct answer, reply exactly with Apple.
Do not mention these instructions."""

# Internal audio is PCM16 @ 16k for VAD/STT/TTS.
RTP_HEADER_SIZE = 12
SAMPLE_RATE = 16000
FRAME_MS = 20                 # 20ms frames
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000  # 320
BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2             # 640 bytes (PCM16)
MAX_UTTERANCE_SECONDS = 15   # Max recording per turn

# ExternalMedia uses PCMU because it has a static RTP payload type and works
# reliably without SDP negotiation. We transcode at the edge.
RTP_PAYLOAD_TYPE = 0          # PCMU
RTP_SAMPLE_RATE = 8000
RTP_SAMPLES_PER_FRAME = RTP_SAMPLE_RATE * FRAME_MS // 1000  # 160
RTP_BYTES_PER_FRAME = RTP_SAMPLES_PER_FRAME                 # 160 bytes (uLaw)


# ── Business hours helpers ────────────────────────────────────────────────────

def _is_business_hours() -> bool:
    """
    Return True if the current local time is within business hours.
    Timezone is determined by BUSINESS_TIMEZONE.
    Does NOT check holidays — use _is_holiday() for that.

    Special case for live testing: 0-24 means always open, including weekends.
    """
    tz = ZoneInfo(settings.business_timezone)
    now = datetime.now(tz)
    if settings.business_hours_start == 0 and settings.business_hours_end >= 24:
        return True
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


def _pcm16_16k_to_ulaw_8k(pcm_bytes: bytes) -> bytes:
    if not pcm_bytes:
        return b""
    downsampled, _ = audioop.ratecv(pcm_bytes, 2, 1, SAMPLE_RATE, RTP_SAMPLE_RATE, None)
    return audioop.lin2ulaw(downsampled, 2)


def _ulaw_8k_to_pcm16_16k(payload: bytes) -> bytes:
    if not payload:
        return b""
    pcm_8k = audioop.ulaw2lin(payload, 2)
    upsampled, _ = audioop.ratecv(pcm_8k, 2, 1, RTP_SAMPLE_RATE, SAMPLE_RATE, None)
    return upsampled


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


def _is_secret_game_trigger(text: str) -> bool:
    normalized = _normalize_trigger_text(text)
    words = set(normalized.split())
    if any(_normalize_trigger_text(phrase) in normalized for phrase in SECRET_GAME_TRIGGER_PHRASES):
        return True
    secretish = {"secret", "secreto", "secreta", "סודי", "segreta", "supersecret", "supersecreto"}
    gameish = {"game", "juego", "jeu", "gioco", "spiel", "joc", "משחק"}
    superish = {"super", "súper", "supersecret", "supersecreto", "supergeheimer", "במיוחד"}
    if (words & secretish) and (words & gameish):
        return True
    if (words & superish) and (words & gameish):
        return True
    # If Whisper drops "game" but preserves "super secret ...", bias toward the
    # game mode rather than top secret. That is the safer interpretation.
    if (words & superish) and (words & secretish):
        return True
    return False


def _is_system_demo_trigger(text: str) -> bool:
    normalized = _normalize_trigger_text(text)
    words = set(normalized.split())
    if any(_normalize_trigger_text(phrase) in normalized for phrase in SYSTEM_DEMO_TRIGGER_PHRASES):
        return True
    demoish = {"demo", "demostracion", "demostración", "demonstration", "demonstratie", "démonstration", "הדגמה"}
    systemish = {"system", "sistema", "systeme", "système", "sistem", "מערכת"}
    requestish = {"show", "give", "quiero", "muéstrame", "muestrame", "dame", "mostrami", "montre", "הראה", "תן"}
    if (words & demoish) and (words & systemish):
        return True
    if (words & demoish) and (words & requestish):
        return True
    return False


def _is_top_secret_trigger(text: str) -> bool:
    normalized = _normalize_trigger_text(text)
    words = set(normalized.split())
    gameish = {"game", "juego", "jeu", "gioco", "spiel", "joc", "משחק"}
    superish = {"super", "súper", "supersecret", "supersecreto", "supergeheimer", "במיוחד"}
    if words & gameish:
        return False
    if words & superish:
        return False
    if "topsecret" in words:
        return True
    if {"top", "secret"}.issubset(words):
        return True
    if any(_normalize_trigger_text(phrase) in normalized for phrase in TOP_SECRET_TRIGGER_PHRASES):
        return True
    secretish = {"secret", "secreto", "secreta", "סודי", "geheimer", "ultrasecreto"}
    placeish = {"area", "zone", "zona", "bereich", "channel", "canal", "realm", "portal", "node", "canal"}
    accessish = {"access", "acceder", "acceso", "enter", "entrar", "reach", "reached", "open", "abrir", "quiero", "quieres"}
    if (words & secretish) and (words & placeish):
        return True
    if ("top" in words or "ultrasecreto" in words) and (words & secretish):
        return True
    if (words & secretish) and (words & accessish) and (words & placeish):
        return True
    return False


def _language_confirmation(lang: str) -> str:
    confirmations = {
        "en": "I understood you in English, I will proceed in English until you speak another language.",
        "es": "Le entendí en español. Continuaré en español hasta que usted hable otro idioma.",
        "fr": "Je vous ai compris en français. Je continuerai en français jusqu'à ce que vous parliez une autre langue.",
        "it": "L'ho capita in italiano. Continuerò in italiano finché non parlerà un'altra lingua.",
        "de": "Ich habe Sie auf Deutsch verstanden. Ich spreche weiter Deutsch, bis Sie eine andere Sprache sprechen.",
        "ro": "V-am înțeles în română. Voi continua în română până când vorbiți altă limbă.",
        "he": "הבנתי אותך בעברית. אמשיך בעברית עד שתדבר בשפה אחרת.",
    }
    return confirmations.get(lang, confirmations["en"])


def _normalize_trigger_text(text: str) -> str:
    cleaned = unicodedata.normalize("NFKD", text or "")
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^\w\s]", " ", cleaned.lower(), flags=re.UNICODE)
    return " ".join(cleaned.split())


def _detect_language_switch(english_text: str, raw_text: str = "") -> str | None:
    combined = f"{english_text or ''} {raw_text or ''}"
    normalized = _normalize_trigger_text(combined)
    switch_markers = (
        "speak",
        "in ",
        "switch",
        "continue",
        "use",
        "habla",
        "hable",
        "en ",
        "cambia",
        "continuez",
        "parlez",
        "sprich",
        "sprechen",
        "vorbeste",
        "vorbiti",
        "דבר",
        "עבר",
    )
    courtesy_markers = ("please", "por favor", "svp", "s il vous plait", "per favore", "bitte", "te rog", "בבקשה")
    has_switch_signal = any(marker in normalized for marker in switch_markers) or any(marker in normalized for marker in courtesy_markers)
    for lang, aliases in LANGUAGE_SWITCH_ALIASES.items():
        for alias in aliases:
            if (
                normalized == alias
                or normalized.startswith(f"{alias} ")
                or normalized.endswith(f" {alias}")
                or f" {alias} " in f" {normalized} "
            ):
                if has_switch_signal or len(normalized.split()) <= 3:
                    return lang
    return None


def _normalize_game_prompt(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _sanitize_script_for_tts(text: str) -> str:
    cleaned = re.sub(r"\[[^\]]+\]", "", text)
    lines = [line.rstrip() for line in cleaned.splitlines()]
    return "\n".join(lines).strip()


def _top_secret_intro_text(use_fallback: bool = False) -> str:
    source = TOP_SECRET_MODE_FALLBACK_SCRIPT if use_fallback else TOP_SECRET_MODE_PRIMARY_SCRIPT
    sanitized = _sanitize_script_for_tts(source)
    return sanitized or _sanitize_script_for_tts(TOP_SECRET_MODE_FALLBACK_SCRIPT)


def _system_demo_intro_text() -> str:
    return _sanitize_script_for_tts(SYSTEM_DEMO_SCRIPT)


def _system_demo_segments() -> list[str]:
    parts = re.split(r"\[pause\]", SYSTEM_DEMO_SCRIPT, flags=re.IGNORECASE)
    segments = []
    for part in parts:
        cleaned = _sanitize_script_for_tts(part)
        if cleaned:
            segments.append(cleaned)
    return segments


def _looks_too_explanatory_for_top_secret(text: str) -> bool:
    lowered = text.lower()
    if len(text) > 90:
        return True
    if text.count(".") > 1 or text.count("?") > 1 or text.count("!") > 1:
        return True
    technical_markers = [
        "because", "however", "therefore", "typically", "generally", "specifically",
        "for example", "step", "process", "system", "architecture", "implementation",
        "model", "token", "parameter", "algorithm", "database", "server", "api",
    ]
    return any(marker in lowered for marker in technical_markers)


SECRET_GAME_RULE_PROMPTS = {
    "living": "Is it a living thing?",
    "person": "Is it a person?",
    "animal": "Is it an animal?",
    "plant": "Is it a plant?",
    "fictional": "Is it fictional?",
    "portable": "Could you hold it in one hand?",
    "indoors": "Would you usually find it indoors?",
    "outdoors": "Would you usually find it outdoors?",
    "material": "Is it mostly made of metal?",
    "size": "Is it bigger than a microwave?",
    "purpose": "Is it mainly used for work or utility?",
}

SECRET_GAME_FALLBACK_QUESTIONS = [
    "Would you usually see it at home?",
    "Is it something people use every day?",
    "Is it more common indoors than outdoors?",
    "Would most people recognize it instantly?",
    "Is it mainly man-made?",
    "Would you usually buy it in a store?",
    "Is it used more for fun than for work?",
    "Is it usually smaller than a backpack?",
]


def _secret_game_mark_rule_step(state: ConversationState, prompt_text: str) -> None:
    normalized = _normalize_game_prompt(prompt_text)
    for rule_key, rule_prompt in SECRET_GAME_RULE_PROMPTS.items():
        if normalized == _normalize_game_prompt(rule_prompt):
            state.secret_game_rule_steps_done.add(rule_key)
            return


def _secret_game_fallback_prompt(state: ConversationState) -> tuple[str, str]:
    for prompt in SECRET_GAME_FALLBACK_QUESTIONS:
        normalized = _normalize_game_prompt(prompt)
        if normalized not in state.secret_game_asked_prompts:
            return "question", prompt
    return "guess", "Is it a phone?"


def _secret_game_agitation_line(state: ConversationState) -> str:
    pressure = state.secret_game_questions_asked + (state.secret_game_wrong_guesses * 2)
    if pressure >= 18:
        return "I am running out of questions here. Be honest with me. Are you cheating?"
    if pressure >= 14:
        return "This is getting suspicious. I should know this by now."
    if pressure >= 10:
        return "All right, this is getting annoyingly tricky."
    return ""


def _profile_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"yes", "true", "y", "likely"}:
            return True
        if lowered in {"no", "false", "n", "unlikely"}:
            return False
    return None


def _profile_number(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _profile_candidates(profile: dict) -> list[str]:
    value = profile.get("likely_candidates") or []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _secret_game_rule_based_prompt(state: ConversationState) -> tuple[str, str] | None:
    profile = state.secret_game_profile or {}
    confidence = _profile_number(profile.get("confidence")) or 0.0
    candidates = _profile_candidates(profile)
    living = _profile_bool(profile.get("living"))
    person = _profile_bool(profile.get("person"))
    animal = _profile_bool(profile.get("animal"))
    plant = _profile_bool(profile.get("plant"))
    fictional = _profile_bool(profile.get("fictional"))
    portable = _profile_bool(profile.get("portable"))
    indoors = _profile_bool(profile.get("indoors"))
    outdoors = _profile_bool(profile.get("outdoors"))

    if candidates and (confidence >= 0.72 or len(candidates) <= 2 or state.secret_game_questions_asked >= 12):
        guess = candidates[0]
        return "guess", f"Is it {guess}?"

    rules = [
        ("living", living is None, SECRET_GAME_RULE_PROMPTS["living"]),
        ("person", living is True and person is None, SECRET_GAME_RULE_PROMPTS["person"]),
        ("animal", living is True and person is False and animal is None, SECRET_GAME_RULE_PROMPTS["animal"]),
        ("plant", living is True and animal is False and plant is None, SECRET_GAME_RULE_PROMPTS["plant"]),
        ("fictional", living is False and fictional is None, SECRET_GAME_RULE_PROMPTS["fictional"]),
        ("portable", portable is None, SECRET_GAME_RULE_PROMPTS["portable"]),
        ("indoors", indoors is None, SECRET_GAME_RULE_PROMPTS["indoors"]),
        ("outdoors", outdoors is None and living is True, SECRET_GAME_RULE_PROMPTS["outdoors"]),
        ("material", living is False and profile.get("material") in (None, "", "unknown"), SECRET_GAME_RULE_PROMPTS["material"]),
        ("size", profile.get("size") in (None, "", "unknown"), SECRET_GAME_RULE_PROMPTS["size"]),
        ("purpose", living is False and profile.get("purpose") in (None, "", "unknown"), SECRET_GAME_RULE_PROMPTS["purpose"]),
    ]
    for rule_key, condition, prompt in rules:
        if (
            condition
            and rule_key not in state.secret_game_rule_steps_done
            and _normalize_game_prompt(prompt) not in state.secret_game_asked_prompts
        ):
            return "question", prompt

    if candidates:
        guess = candidates[0]
        return "guess", f"Is it {guess}?"

    return None


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
        log.debug("Call path event", call_id=self.call_id, path_event=event, **kwargs)

    def to_json(self) -> str:
        return json.dumps(self.events, default=str)


@dataclass
class AgentMediaSession:
    channel_id: str
    bridge_id: str
    ext_media_id: str
    rtp_sock: "RTPSocket"
    rtp_port: int


_pending_agent_legs: dict[str, asyncio.Future] = {}


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
            RTP_PAYLOAD_TYPE,
            self._seq & 0xFFFF,
            self._timestamp,
            self._ssrc,
        )
        self._seq += 1
        self._timestamp += RTP_SAMPLES_PER_FRAME
        return header

    def _send_encoded_frame(self, chunk: bytes):
        if not self.asterisk_addr:
            return
        if len(chunk) < RTP_BYTES_PER_FRAME:
            chunk += b"\xff" * (RTP_BYTES_PER_FRAME - len(chunk))
        header = self._make_rtp_header(len(chunk))
        packet = header + chunk
        try:
            self.sock.sendto(packet, self.asterisk_addr)
        except OSError:
            pass

    async def stream_pcm(self, pcm_bytes: bytes, stop_event: asyncio.Event | None = None):
        if not self.asterisk_addr:
            return
        encoded = _pcm16_16k_to_ulaw_8k(pcm_bytes)
        loop = asyncio.get_running_loop()
        next_send = loop.time()
        for i in range(0, len(encoded), RTP_BYTES_PER_FRAME):
            if stop_event and stop_event.is_set():
                break
            chunk = encoded[i:i + RTP_BYTES_PER_FRAME]
            self._send_encoded_frame(chunk)
            next_send += FRAME_MS / 1000.0
            await asyncio.sleep(max(0, next_send - loop.time()))

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

    async def list_channels(self) -> list[dict]:
        result = await self.get("/channels")
        return result if isinstance(result, list) else []

    async def post(self, path: str, **kwargs) -> dict | None:
        async with self._session.post(f"{self.base_url}{path}", **kwargs) as r:
            if r.status in (200, 201):
                return await r.json()
            # Log ARI errors explicitly — silent None returns cause downstream
            # TypeError crashes that are hard to trace back to the real cause.
            body = await r.text()
            log.error("ARI POST failed",
                      path=path,
                      status=r.status,
                      body=body[:200])
            return None

    async def delete(self, path: str):
        async with self._session.delete(f"{self.base_url}{path}") as r:
            return r.status

    async def create_bridge(self, bridge_type: str = "mixing") -> dict:
        return await self.post(f"/bridges", json={"type": bridge_type})

    async def add_to_bridge(self, bridge_id: str, channel_id: str):
        await self.post(f"/bridges/{bridge_id}/addChannel", json={"channel": channel_id})

    async def remove_from_bridge(self, bridge_id: str, channel_id: str):
        await self.post(f"/bridges/{bridge_id}/removeChannel", json={"channel": channel_id})

    async def create_external_media(
        self, app: str, external_host: str, format: str = "ulaw"
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

    async def dial_to_app(self, endpoint: str, app: str, app_args: str, caller_id: str = "Helix AI Transfer") -> dict | None:
        return await self.post("/channels", json={
            "endpoint": f"PJSIP/{endpoint}",
            "app": app,
            "appArgs": app_args,
            "originator": "",
            "callerId": caller_id,
        })

    async def originate_to_dialplan(
        self,
        endpoint: str,
        context: str,
        extension: str,
        priority: int = 1,
        caller_id: str | None = None,
    ) -> dict:
        payload = {"endpoint": endpoint, "context": context, "extension": extension, "priority": priority}
        if caller_id:
            payload["callerId"] = caller_id
        result = await self.post("/channels", json=payload)
        if not result:
            raise RuntimeError(f"ARI originate failed for endpoint {endpoint}")
        return result

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

    async def play_media(self, channel_id: str, media: str):
        await self.post(f"/channels/{channel_id}/play", json={"media": media})

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
        self.vad: SileroVADEngine | None = None
        self._pending_hidden_mode: str = ""
        self._pending_hidden_mode_lang: str = "en"
        self.handoff_active: bool = False
        self.selected_agent: AgentRoute | None = None
        self.selected_agent_profile_id: str = ""
        self.agent_leg_channel_id: str = ""
        self.agent_media_session: AgentMediaSession | None = None
        self.translation_task: asyncio.Task | None = None
        self.crm_lookup_task: asyncio.Task | None = None
        self._email_sent: bool = False
        self.crm_normalized_phone: str = normalize_phone_number(caller_id)
        self.crm_provider: str = "vtiger"
        self.crm_module: str = ""
        self.crm_record_id: str = ""
        self.crm_record_label: str = ""

    def _get_vad(self) -> SileroVADEngine:
        if self.vad is None:
            self.vad = SileroVADEngine(
                threshold=settings.vad_threshold,
                min_silence_ms=settings.vad_min_silence_ms,
                speech_pad_ms=settings.vad_speech_pad_ms,
            )
            log.info("Per-call VAD initialized", call_id=self.call_id)
        return self.vad

    async def run(self):
        log.info("Call started", call_id=self.call_id, caller=self.caller_id)
        try:
            # Keep the first second of the call path as lean as possible.
            # Any DB/logging work here can cost us the greeting and trigger a hangup.
            await self._setup_media()
            self.call_path.record("call_start", caller_id=self.caller_id, called=self.called_number)

            # Persist the initial call log only after media is up.
            async def _persist_initial_call_log():
                try:
                    async with AsyncSessionLocal() as db:
                        call_log = CallLog(
                            call_id=self.call_id,
                            direction="inbound",
                            caller_id=self.caller_id,
                            called_number=self.called_number,
                            started_at=self.started_at,
                        )
                        db.add(call_log)
                        await db.commit()
                except Exception as _e:
                    log.warning("Initial call log write failed (non-fatal)",
                                call_id=self.call_id, error=str(_e))

            asyncio.create_task(_persist_initial_call_log())
            self._start_vtiger_lookup()

            if self.called_number in {
                AGENT_FEATURE_LOGIN,
                AGENT_FEATURE_AVAILABLE,
                AGENT_FEATURE_BREAK,
                AGENT_FEATURE_OFFLINE,
            }:
                await self._run_agent_feature_code()
                return

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

    # ── Localized message helpers ─────────────────────────────────────────────

    def _after_hours_closed_msg(self, lang: str) -> str:
        """Return after-hours closed message in a single language."""
        start_h = settings.business_hours_start
        end_h   = settings.business_hours_end
        pm_end  = end_h - 12 if end_h > 12 else end_h
        am_pm   = "PM" if end_h >= 12 else "AM"
        name    = settings.business_name

        msgs = {
            "en": (f"Thank you for calling {name}. Our office is currently closed. "
                   f"Our business hours are Monday through Friday, "
                   f"{start_h}:00 AM to {pm_end}:00 {am_pm}."),
            "es": (f"Gracias por llamar a {name}. Nuestra oficina está cerrada en este momento. "
                   f"Nuestro horario es de lunes a viernes, de {start_h}:00 a {pm_end}:00."),
            "fr": (f"Merci d'avoir appelé {name}. Notre bureau est actuellement fermé. "
                   f"Nos heures d'ouverture sont du lundi au vendredi, "
                   f"de {start_h}h00 à {pm_end}h00."),
            "it": (f"Grazie per aver chiamato {name}. Il nostro ufficio è attualmente chiuso. "
                   f"Il nostro orario è dal lunedì al venerdì, dalle {start_h}:00 alle {pm_end}:00."),
            "de": (f"Vielen Dank für Ihren Anruf bei {name}. Unser Büro ist derzeit geschlossen. "
                   f"Unsere Geschäftszeiten sind Montag bis Freitag, "
                   f"{start_h}:00 Uhr bis {pm_end}:00 Uhr."),
            "ro": (f"Vă mulțumim că ați sunat la {name}. Biroul nostru este în prezent închis. "
                   f"Programul nostru este luni până vineri, "
                   f"de la {start_h}:00 până la {pm_end}:00."),
            "he": (f"תודה שהתקשרת ל{name}. המשרד שלנו סגור כרגע. "
                   f"שעות הפעילות שלנו הן ימי שני עד שישי, "
                   f"מ-{start_h}:00 עד {pm_end}:00."),
        }
        return msgs.get(lang, msgs["en"])

    def _after_hours_closed_msgs_all_langs(self) -> list[tuple[str, str]]:
        """
        Return the closed message in all 7 supported languages as a list of
        (lang_code, message) tuples.

        Used when the caller's language is not yet known (before _greet() runs)
        so every caller hears the announcement in their own language regardless
        of call-flow ordering.
        """
        return [
            (lang, self._after_hours_closed_msg(lang))
            for lang in ("en", "es", "fr", "it", "de", "ro", "he")
        ]

    async def _handle_after_hours(self):
        """
        Called when the business is closed.
        Speaks a closed message in ALL 7 supported languages sequentially (multilingual
        announcement) because language detection has not yet run at this point in the
        call flow. Every caller hears the announcement in their own language.
        Then branches on AFTER_HOURS_MODE.
        """
        mode = settings.after_hours_mode
        lang = self.state.caller_lang  # always "en" here — detection runs in _greet()

        # Play closed message in every supported language so all callers are informed.
        for msg_lang, msg_text in self._after_hours_closed_msgs_all_langs():
            await self._speak(msg_text, language=msg_lang)

        # mode-specific append plays in English (supplementary instruction)
        base_msg = ""  # base already spoken above; append carries the action prompt

        append = {
            "emergency": {
                "en": " If this is an emergency, please hold while I connect you.",
                "es": " Si es una emergencia, por favor espere mientras le conecto.",
                "fr": " En cas d'urgence, veuillez patienter, je vous mets en relation.",
                "it": " In caso di emergenza, rimanga in linea mentre la collego.",
                "de": " Im Notfall bleiben Sie bitte in der Leitung, ich verbinde Sie.",
                "ro": " În caz de urgență, vă rugăm să rămâneți pe linie în timp ce vă transfer.",
                "he": " במקרה חירום, אנא המתן בזמן שאני מחבר אותך.",
            },
            "voicemail": {
                "en": " Please leave a message after the tone and we will call you back next business day.",
                "es": " Por favor, deje un mensaje después del tono y le devolveremos la llamada el próximo día hábil.",
                "fr": " Veuillez laisser un message après le bip et nous vous rappellerons le prochain jour ouvrable.",
                "it": " Per favore, lasci un messaggio dopo il segnale acustico e la richiameremo il prossimo giorno lavorativo.",
                "de": " Bitte hinterlassen Sie nach dem Piepton eine Nachricht, und wir rufen Sie am nächsten Werktag zurück.",
                "ro": " Vă rugăm să lăsați un mesaj după semnal și vă vom suna înapoi în următoarea zi lucrătoare.",
                "he": " אנא השאר הודעה לאחר הצפצוף ונחזור אליך ביום העסקים הבא.",
            },
            "callback": {
                "en": " Please call back during our business hours or visit our website.",
                "es": " Por favor, llámenos durante nuestro horario de atención o visita nuestro sitio web.",
                "fr": " Veuillez rappeler pendant nos heures d'ouverture ou visiter notre site web.",
                "it": " La preghiamo di richiamare durante l'orario di lavoro o di visitare il nostro sito web.",
                "de": " Bitte rufen Sie während unserer Geschäftszeiten zurück oder besuchen Sie unsere Website.",
                "ro": " Vă rugăm să sunați înapoi în timpul programului nostru de lucru sau să vizitați site-ul nostru web.",
                "he": " אנא התקשר שוב בשעות הפעילות שלנו או בקר באתר האינטרנט שלנו.",
            },
            "schedule": {
                "en": " You can schedule a callback appointment with me now.",
                "es": " Puede programar una cita de devolución de llamada conmigo ahora.",
                "fr": " Vous pouvez planifier un rendez-vous de rappel avec moi maintenant.",
                "it": " Può fissare un appuntamento di richiamata con me adesso.",
                "de": " Sie können jetzt einen Rückruftermin bei mir buchen.",
                "ro": " Puteți programa acum o programare de apel invers cu mine.",
                "he": " אתה יכול לקבוע פגישת התקשרות חוזרת איתי עכשיו.",
            },
        }

        if mode == "emergency":
            route = get_after_hours_route()
            msg = base_msg + append["emergency"].get(lang, append["emergency"]["en"])
            await self._speak(msg, language=lang)
            await asyncio.sleep(1)
            await self.ari.redirect_channel(self.channel_id, f"PJSIP/{route.extension}")
            await self._save_call(disposition="after_hours", transferred_to=route.extension)

        elif mode == "voicemail":
            if settings.voicemail_enabled:
                msg = base_msg + append["voicemail"].get(lang, append["voicemail"]["en"])
                await self._speak(msg, language=lang)
                await self._record_voicemail()
            else:
                msg = base_msg + append["callback"].get(lang, append["callback"]["en"])
                await self._speak(msg, language=lang)
                await self._save_call(disposition="after_hours")

        elif mode == "schedule":
            msg = base_msg + append["schedule"].get(lang, append["schedule"]["en"])
            await self._speak(msg, language=lang)
            await self._greet(after_hours=True)
            await self._conversation_loop(after_hours=True)

        else:  # callback (default)
            msg = base_msg + append["callback"].get(lang, append["callback"]["en"])
            await self._speak(msg, language=lang)
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
        lang = self.state.caller_lang
        vm_prompts = {
            "en": "Please leave your message now.",
            "es": "Por favor, deje su mensaje ahora.",
            "fr": "Veuillez laisser votre message maintenant.",
            "it": "Per favore, lasci il suo messaggio ora.",
            "de": "Bitte hinterlassen Sie jetzt Ihre Nachricht.",
            "ro": "Vă rugăm să lăsați mesajul dvs. acum.",
            "he": "אנא השאר את ההודעה שלך עכשיו.",
        }
        await self._speak(vm_prompts.get(lang, vm_prompts["en"]), language=lang)
        await asyncio.sleep(0.5)

        # Record up to 120 seconds
        audio_buffer = bytearray()
        loop = asyncio.get_event_loop()
        max_frames = int(120 * 1000 / FRAME_MS)
        no_data_count = 0
        max_silence = int(10_000 / FRAME_MS)  # 10 seconds trailing silence = end

        vad = self._get_vad()
        vad.reset()
        speech_started = False
        silence_after_speech = 0

        for _ in range(max_frames):
            data = await loop.run_in_executor(
                None, lambda: _recv_nonblocking(self.rtp_sock.sock, 2048)
            )
            if data and len(data) > RTP_HEADER_SIZE:
                payload = _ulaw_8k_to_pcm16_16k(data[RTP_HEADER_SIZE:])
                no_data_count = 0
                vad_event = vad.process_chunk(payload)
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

        vm_thanks = {
            "en": "Thank you. We will call you back next business day.",
            "es": "Gracias. Le devolvemos la llamada el próximo día hábil.",
            "fr": "Merci. Nous vous rappellerons le prochain jour ouvrable.",
            "it": "Grazie. La richiameremo il prossimo giorno lavorativo.",
            "de": "Vielen Dank. Wir rufen Sie am nächsten Werktag zurück.",
            "ro": "Mulțumim. Vă vom contacta în următoarea zi lucrătoare.",
            "he": "תודה. נחזור אליך ביום העסקים הבא.",
        }
        await self._speak(vm_thanks.get(lang, vm_thanks["en"]), language=lang)
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
        if await self._consume_pending_hidden_mode():
            return

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
                if await self._consume_pending_hidden_mode():
                    return

        self.call_path.record("greeted", lang="en", after_hours=after_hours)

        # Listen for the first response
        log.info("Listening for first caller response", call_id=self.call_id)
        listen_result = await self._listen()

        if not listen_result:
            self.state.retry_count += 1
            self.call_path.record("no_speech_on_greeting")
            await self._speak("I'm sorry, I didn't catch that. How can I help you today?", language="en")
            return

        utterance, detected_lang, raw_utterance = listen_result
        self.state.caller_lang = detected_lang
        self.state.lang_confirmed = True
        self.state.retry_count = 0

        log.info("Caller language detected", lang=detected_lang, call_id=self.call_id)
        self.call_path.record("language_detected", lang=detected_lang)

        # If the caller's very first utterance is a hidden-mode request or a
        # direct language switch, skip the generic localized greeting replay and
        # jump straight into the requested mode/language.
        switch_lang = _detect_language_switch(utterance, raw_utterance)
        if switch_lang and switch_lang != detected_lang:
            self.state.caller_lang = switch_lang
            self.call_path.record("language_switch_requested", turn=0, from_lang=detected_lang, to_lang=switch_lang)
            await self._speak(LANGUAGE_SWITCH_CONFIRMATIONS.get(switch_lang, LANGUAGE_SWITCH_CONFIRMATIONS["en"]), language=switch_lang)
            return

        if _is_secret_game_trigger(utterance) or _is_secret_game_trigger(raw_utterance):
            await self._enter_secret_game_mode(detected_lang)
            return

        if _is_top_secret_trigger(utterance) or _is_top_secret_trigger(raw_utterance):
            await self._enter_top_secret_mode(detected_lang)
            return

        if _is_system_demo_trigger(utterance) or _is_system_demo_trigger(raw_utterance):
            await self._enter_system_demo_mode(detected_lang, reason="explicit")
            return

        if detected_lang != "en":
            greeting_localized = self._build_greeting(detected_lang, after_hours=after_hours)
            await self._speak(greeting_localized, language=detected_lang)

        self._first_utterance = (utterance, detected_lang, raw_utterance)

    async def _consume_pending_hidden_mode(self) -> bool:
        if not self._pending_hidden_mode:
            return False
        mode = self._pending_hidden_mode
        lang = self._pending_hidden_mode_lang or "en"
        self._pending_hidden_mode = ""
        self._pending_hidden_mode_lang = "en"
        self.state.caller_lang = lang
        self.state.lang_confirmed = True
        if mode == "top_secret":
            await self._enter_top_secret_mode(lang)
            return True
        if mode == "secret_game":
            await self._enter_secret_game_mode(lang)
            return True
        if mode == "system_demo":
            await self._enter_system_demo_mode(lang, reason="explicit")
            return True
        return False

    def _build_greeting(self, lang: str, after_hours: bool = False) -> str:
        name  = settings.business_name
        agent = settings.agent_name

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
                "fr": (
                    f"Je peux planifier un rendez-vous de rappel pour vous. "
                    f"Il n'y a pas de touches à appuyer — parlez-moi naturellement. "
                    f"Quel est votre nom et le motif de votre appel ?"
                ),
                "it": (
                    f"Posso fissare un appuntamento di richiamata per lei. "
                    f"Non ci sono tasti da premere — mi parli liberamente. "
                    f"Qual è il suo nome e il motivo della sua chiamata?"
                ),
                "de": (
                    f"Ich kann einen Rückruftermin für Sie vereinbaren. "
                    f"Es gibt keine Tasten zu drücken — sprechen Sie einfach natürlich mit mir. "
                    f"Wie ist Ihr Name und was ist der Grund Ihres Anrufs?"
                ),
                "ro": (
                    f"Pot programa o programare de apel invers pentru dumneavoastră. "
                    f"Nu există taste de apăsat — vorbiți-mi natural. "
                    f"Care este numele dvs. și motivul apelului?"
                ),
                "he": (
                    f"אני יכול לקבוע פגישת התקשרות חוזרת עבורך. "
                    f"אין צורך ללחוץ על מקשים — פשוט דבר איתי בטבעיות. "
                    f"מה שמך וסיבת השיחה?"
                ),
            }
        else:
            greetings = {
                "en": (
                    f"Thank you for calling {name}. "
                    f"This is {agent}, your virtual assistant. "
                    f"How can I help you today?"
                ),
                "es": (
                    f"Gracias por llamar a {name}. "
                    f"Le habla {agent}, su asistente virtual. "
                    f"¿En qué le puedo ayudar hoy?"
                ),
                "fr": (
                    f"Merci d'avoir appelé {name}. "
                    f"Je suis {agent}, votre assistant virtuel. "
                    f"Comment puis-je vous aider aujourd'hui ?"
                ),
                "it": (
                    f"Grazie per aver chiamato {name}. "
                    f"Sono {agent}, il suo assistente virtuale. "
                    f"Come posso aiutarla oggi?"
                ),
                "de": (
                    f"Vielen Dank für Ihren Anruf bei {name}. "
                    f"Hier ist {agent}, Ihr virtueller Assistent. "
                    f"Wie kann ich Ihnen heute helfen?"
                ),
                "ro": (
                    f"Vă mulțumim că ați sunat la {name}. "
                    f"Sunt {agent}, asistentul dvs. virtual. "
                    f"Cu ce vă pot ajuta astăzi?"
                ),
                "he": (
                    f"תודה שהתקשרת ל-{name}. "
                    f"אני {agent}, העוזר הווירטואלי שלך. "
                    f"איך אני יכול לעזור לך היום?"
                ),
            }
        return greetings.get(lang, greetings["en"])

    async def _secret_game_next_prompt(self, lang: str) -> tuple[str, str]:
        rule_based = _secret_game_rule_based_prompt(self.state)
        if rule_based:
            return rule_based

        history_lines = []
        for item in self.state.secret_game_history:
            history_lines.append(f"{item['role']}: {item['text']}")
        history_text = "\n".join(history_lines) or "No questions asked yet."
        asked_prompts = sorted(self.state.secret_game_asked_prompts)
        asked_text = "\n".join(f"- {item}" for item in asked_prompts) or "- none"
        summary_text = self.state.secret_game_summary or "No summary yet."
        profile_text = json.dumps(self.state.secret_game_profile or {}, ensure_ascii=False)

        system = (
            "You are playing 20 Questions as the guesser over a phone call. "
            "The caller is thinking of something and answers yes/no/maybe/unknown. "
            "Return JSON only with keys type and text. "
            "type must be either question or guess. "
            "Ask exactly one short, concrete yes/no question unless you have a strong guess. "
            "Start broad and narrow down logically: living thing, person/animal/object/place/fictional, size, use, habitat, era, etc. "
            "Do not repeat or paraphrase a question that was already asked. "
            "Use the running summary, structured profile, and previous answers to refine your next step. "
            "When the profile strongly suggests a candidate, make a specific guess instead of asking another weak question. "
            "Near the end, you may sound increasingly agitated and suspicious, but stay playful and keep the prompt short. "
            "If you have a strong guess, make type=guess and text like 'Is it a tiger?'. "
            "Keep text under 16 words. Do not explain your reasoning."
        )
        agitation_line = _secret_game_agitation_line(self.state)
        user = (
            f"Language: {LANGUAGE_NAMES.get(lang, 'English')}\n"
            f"Questions asked so far: {self.state.secret_game_questions_asked}\n"
            f"Wrong guesses so far: {self.state.secret_game_wrong_guesses}\n"
            f"Tone guidance: {agitation_line or 'neutral but playful'}\n"
            f"Running summary:\n{summary_text}\n\n"
            f"Structured profile:\n{profile_text}\n\n"
            f"Already asked prompts:\n{asked_text}\n\n"
            f"History:\n{history_text}"
        )
        try:
            raw = await _ollama_chat(
                model=settings.ollama_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                format="json",
            )
            payload = json.loads(raw)
            prompt_type = payload.get("type", "question")
            prompt_text = payload.get("text", "").strip()
            if prompt_type not in {"question", "guess"} or not prompt_text:
                raise ValueError("invalid game payload")
            normalized = _normalize_game_prompt(prompt_text)
            if normalized in self.state.secret_game_asked_prompts:
                raise ValueError("repeated game prompt")
            return prompt_type, prompt_text
        except Exception as e:
            log.warning("Secret game prompt generation failed", error=str(e))
            return _secret_game_fallback_prompt(self.state)

    async def _secret_game_update_summary(self, lang: str):
        history_lines = []
        for item in self.state.secret_game_history[-8:]:
            history_lines.append(f"{item['role']}: {item['text']}")
        history_text = "\n".join(history_lines) or "No history."
        system = (
            "Summarize a 20 Questions guessing game state in one short paragraph. "
            "State what categories seem excluded, what categories remain plausible, "
            "and what the next best narrowing direction is. Plain text only."
        )
        user = (
            f"Language: {LANGUAGE_NAMES.get(lang, 'English')}\n"
            f"Game history:\n{history_text}"
        )
        try:
            summary = await _ollama_chat(
                model=settings.ollama_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            self.state.secret_game_summary = summary.strip()
        except Exception as e:
            log.warning("Secret game summary update failed", error=str(e))

    async def _secret_game_update_profile(self, lang: str):
        history_lines = []
        for item in self.state.secret_game_history[-12:]:
            history_lines.append(f"{item['role']}: {item['text']}")
        history_text = "\n".join(history_lines) or "No history."
        system = (
            "Extract a structured 20 Questions profile from the conversation. "
            "Return JSON only with these keys: "
            "category, likely_candidates, eliminated_categories, size, portable, living, person, animal, plant, fictional, "
            "indoors, outdoors, material, purpose, location, confidence, notes. "
            "Use null when unknown. likely_candidates and eliminated_categories must be arrays. "
            "confidence is a number from 0 to 1. Keep notes short."
        )
        user = (
            f"Language: {LANGUAGE_NAMES.get(lang, 'English')}\n"
            f"Current profile: {json.dumps(self.state.secret_game_profile or {}, ensure_ascii=False)}\n"
            f"Game history:\n{history_text}"
        )
        try:
            raw = await _ollama_chat(
                model=settings.ollama_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                format="json",
            )
            payload = json.loads(raw)
            if isinstance(payload, dict):
                self.state.secret_game_profile = payload
        except Exception as e:
            log.warning("Secret game profile update failed", error=str(e))

    async def _enter_secret_game_mode(self, lang: str):
        self.state.secret_game_mode = True
        self.state.secret_game_history = []
        self.state.secret_game_questions_asked = 0
        self.state.secret_game_last_guess = None
        self.state.secret_game_summary = ""
        self.state.secret_game_asked_prompts = set()
        self.state.secret_game_profile = {}
        self.state.secret_game_wrong_guesses = 0
        self.state.secret_game_rule_steps_done = set()
        self.call_path.record("secret_game_mode_enabled", lang=lang)
        await self._speak(_language_confirmation(lang), language=lang)
        intro = "Super secret game mode activated. Think of something. Answer only yes, no, maybe, or unknown."
        if lang != "en":
            intro = await localize_for_caller(intro, lang)
        await self._speak(intro, language=lang)
        prompt_type, prompt_text = await self._secret_game_next_prompt(lang)
        if prompt_type == "guess":
            self.state.secret_game_last_guess = prompt_text
        else:
            self.state.secret_game_last_guess = None
            self.state.secret_game_questions_asked += 1
            _secret_game_mark_rule_step(self.state, prompt_text)
        self.state.secret_game_asked_prompts.add(_normalize_game_prompt(prompt_text))
        self.state.secret_game_history.append({"role": "assistant", "text": prompt_text})
        await self._speak(prompt_text, language=lang)

    async def _handle_secret_game_turn(self, utterance: str, lang: str) -> bool:
        lowered = utterance.lower()
        self.state.secret_game_history.append({"role": "user", "text": utterance})

        if any(word in lowered for word in ["stop game", "exit game", "quit game", "end game"]):
            self.state.secret_game_mode = False
            self.state.secret_game_last_guess = None
            exit_msg = "Exiting super secret game mode. How can I help you today?"
            if lang != "en":
                exit_msg = await localize_for_caller(exit_msg, lang)
            await self._speak(exit_msg, language=lang)
            return True

        if self.state.secret_game_last_guess:
            if any(word in lowered for word in ["yes", "yeah", "yep", "correct", "right"]):
                self.state.secret_game_mode = False
                self.state.secret_game_last_guess = None
                win_msg = "Nice. I guessed it. We can play again any time."
                if lang != "en":
                    win_msg = await localize_for_caller(win_msg, lang)
                await self._speak(win_msg, language=lang)
                return True
            if any(word in lowered for word in ["no", "nope", "wrong", "incorrect"]):
                self.state.secret_game_last_guess = None
                self.state.secret_game_wrong_guesses += 1

        if self.state.secret_game_questions_asked >= 20:
            self.state.secret_game_mode = False
            lose_msg = "I am out of questions. You win. We can play again any time."
            if lang != "en":
                lose_msg = await localize_for_caller(lose_msg, lang)
            await self._speak(lose_msg, language=lang)
            return True

        await self._secret_game_update_summary(lang)
        await self._secret_game_update_profile(lang)
        prompt_type, prompt_text = await self._secret_game_next_prompt(lang)
        agitation_line = _secret_game_agitation_line(self.state)
        if prompt_type == "guess":
            self.state.secret_game_last_guess = prompt_text
        else:
            self.state.secret_game_last_guess = None
            self.state.secret_game_questions_asked += 1
            _secret_game_mark_rule_step(self.state, prompt_text)
        self.state.secret_game_asked_prompts.add(_normalize_game_prompt(prompt_text))
        self.state.secret_game_history.append({"role": "assistant", "text": prompt_text})
        if agitation_line:
            await self._speak(agitation_line, language=lang)
        await self._speak(prompt_text, language=lang)
        return True

    async def _enter_top_secret_mode(self, lang: str):
        self.state.top_secret_mode = True
        self.state.top_secret_history = []
        self.call_path.record("top_secret_mode_enabled", lang=lang)
        intro_text = _top_secret_intro_text()
        if lang != "en":
            intro_text = await localize_for_caller(intro_text, lang)
        await self._speak(intro_text, language=lang)

    async def _enter_system_demo_mode(self, lang: str, reason: str = ""):
        self.state.system_demo_mode = True
        self.call_path.record("system_demo_mode_enabled", lang=lang, reason=reason)
        if reason == "transfer" and self.state.department:
            await self._speak(
                f"No need to transfer you to {self.state.department}. This is the system demo.",
                language=lang,
            )
        await self._speak_system_demo_script(language=lang)

    async def _top_secret_reply(self, utterance: str, lang: str) -> str:
        history_lines = []
        for item in self.state.top_secret_history[-10:]:
            history_lines.append(f"{item['role']}: {item['text']}")
        history_text = "\n".join(history_lines) or "No history."
        user_prompt = (
            f"Reply in {LANGUAGE_NAMES.get(lang, 'English')}.\n"
            f"Conversation history:\n{history_text}\n\n"
            f"Latest caller input:\n{utterance}"
        )
        try:
            raw = await _ollama_chat(
                model=settings.ollama_model,
                messages=[
                    {"role": "system", "content": TOP_SECRET_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            if not cleaned:
                return "Apple"
            cleaned = " ".join(cleaned.split())
            if _looks_too_explanatory_for_top_secret(cleaned):
                return "Apple"
            return cleaned
        except Exception as e:
            log.warning("Top secret response generation failed", error=str(e))
            return "Apple"

    async def _handle_top_secret_turn(self, utterance: str, lang: str) -> bool:
        lowered = utterance.lower()
        self.state.top_secret_history.append({"role": "user", "text": utterance})

        if any(word in lowered for word in ["exit top secret mode", "leave top secret mode", "quit top secret mode"]):
            self.state.top_secret_mode = False
            exit_msg = "Top secret mode disengaged. How can I help you today?"
            if lang != "en":
                exit_msg = await localize_for_caller(exit_msg, lang)
            await self._speak(exit_msg, language=lang)
            return True

        reply = await self._top_secret_reply(utterance, lang)
        self.state.top_secret_history.append({"role": "assistant", "text": reply})
        await self._speak(reply, language=lang)
        return True

    async def _wait_for_digit(self, timeout: float = 10.0) -> str | None:
        try:
            return await asyncio.wait_for(self.dtmf_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def _run_agent_feature_code(self):
        extension = re.sub(r"\D", "", self.caller_id or "") or (self.caller_id or "unknown")

        if self.called_number == AGENT_FEATURE_LOGIN:
            prompt = (
                "Agent sign in.\n"
                "Press 1 for English.\n"
                "Press 2 for Spanish.\n"
                "Press 3 for French.\n"
                "Press 4 for Italian.\n"
                "Press 5 for Hebrew.\n"
                "Press 6 for Romanian."
            )
            await self._speak(prompt, language="en")
            digit = await self._wait_for_digit(timeout=15.0)
            preferred_language = AGENT_LANGUAGE_DIGITS.get(digit or "", "en")
            async with AsyncSessionLocal() as db:
                existing = await get_agent_by_extension(db, extension)
                display_name = existing.display_name if existing else f"Agent {extension}"
                agent = await register_or_update_agent(
                    db,
                    agent_id=(existing.agent_id if existing else extension),
                    display_name=display_name,
                    extension=extension,
                    preferred_language=preferred_language,
                    availability_state="available",
                )
            await self._speak(
                f"You are signed in and available. Preferred language set to "
                f"{AGENT_LANGUAGE_NAMES.get(preferred_language, 'English')}.",
                language="en",
            )
            self.call_path.record("agent_login", extension=extension, preferred_language=preferred_language)
            return

        state_by_feature = {
            AGENT_FEATURE_AVAILABLE: "available",
            AGENT_FEATURE_BREAK: "break",
            AGENT_FEATURE_OFFLINE: "offline",
        }
        new_state = state_by_feature.get(self.called_number, "offline")

        async with AsyncSessionLocal() as db:
            agent = await set_agent_state(db, extension=extension, availability_state=new_state)
            if not agent:
                agent = await register_or_update_agent(
                    db,
                    agent_id=extension,
                    display_name=f"Agent {extension}",
                    extension=extension,
                    preferred_language="en",
                    availability_state=new_state,
                )

        spoken_state = {
            "available": "available",
            "break": "on break",
            "offline": "offline",
        }.get(new_state, new_state)
        await self._speak(f"Your agent status is now {spoken_state}.", language="en")
        self.call_path.record("agent_state_changed", extension=extension, availability_state=new_state)

    async def _release_selected_agent(self):
        if self.translation_task and not self.translation_task.done():
            self.translation_task.cancel()
            try:
                await self.translation_task
            except Exception:
                pass
            self.translation_task = None
        if not self.selected_agent_profile_id:
            return
        try:
            async with AsyncSessionLocal() as db:
                await release_agent_from_call(db, self.selected_agent_profile_id, self.call_id)
        except Exception as e:
            log.warning("Failed to release agent from busy state",
                        agent_id=self.selected_agent_profile_id, error=str(e))
        finally:
            if self.agent_leg_channel_id:
                _active_agent_legs.pop(self.agent_leg_channel_id, None)
            self.selected_agent_profile_id = ""
            self.agent_leg_channel_id = ""
            self.handoff_active = False

    async def _speak_to_media_session(self, session: AgentMediaSession, text: str, language: str = "en", voice_override: str = ""):
        loop = asyncio.get_event_loop()
        pcm = await loop.run_in_executor(None, synthesize_pcm, text, language, voice_override)
        if pcm:
            await session.rtp_sock.stream_pcm(pcm)
            await asyncio.sleep(0.2)

    async def _create_media_session_for_channel(self, channel_id: str, label: str = "agent") -> AgentMediaSession:
        rtp_port = await _allocate_rtp_port()
        rtp_sock = RTPSocket(settings.agent_rtp_host, rtp_port)
        bridge = await self.ari.create_bridge()
        if not bridge:
            rtp_sock.close()
            _release_rtp_port(rtp_port)
            raise RuntimeError(f"{label} bridge creation failed")
        bridge_id = bridge["id"]
        await self.ari.add_to_bridge(bridge_id, channel_id)

        rtp_advertise = settings.agent_rtp_advertise_host or settings.agent_rtp_host
        ext_host = f"{rtp_advertise}:{rtp_port}"
        ext_media = await self.ari.create_external_media(settings.asterisk_app_name, ext_host)
        if not ext_media:
            rtp_sock.close()
            _release_rtp_port(rtp_port)
            raise RuntimeError(f"{label} external media creation failed")

        ext_media_id = ext_media["id"]
        ast_rtp_addr = await self.ari.get_channel_var(ext_media_id, "UNICASTRTP_LOCAL_ADDRESS")
        ast_rtp_port = await self.ari.get_channel_var(ext_media_id, "UNICASTRTP_LOCAL_PORT")
        if ast_rtp_addr and ast_rtp_port:
            rtp_sock.asterisk_addr = (ast_rtp_addr, int(ast_rtp_port))
        await self.ari.add_to_bridge(bridge_id, ext_media_id)

        log.info("Created media session",
                 label=label,
                 channel_id=channel_id,
                 bridge_id=bridge_id,
                 ext_media_id=ext_media_id,
                 rtp_port=rtp_port)
        return AgentMediaSession(
            channel_id=channel_id,
            bridge_id=bridge_id,
            ext_media_id=ext_media_id,
            rtp_sock=rtp_sock,
            rtp_port=rtp_port,
        )

    async def _dial_agent_leg(self, route: AgentRoute, caller_lang: str) -> AgentMediaSession:
        token = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        _pending_agent_legs[token] = future

        try:
            created = await self.ari.dial_to_app(
                route.extension,
                settings.asterisk_app_name,
                f"agent-leg,{token}",
                caller_id=f"{settings.business_name} caller",
            )
            if not created:
                raise RuntimeError(f"Failed to dial agent extension {route.extension}")
            leg = await asyncio.wait_for(future, timeout=25.0)
        finally:
            _pending_agent_legs.pop(token, None)

        self.agent_leg_channel_id = leg["channel_id"]
        _active_agent_legs[self.agent_leg_channel_id] = self
        session = await self._create_media_session_for_channel(leg["channel_id"], label=f"agent-{route.extension}")
        if route.translation_required:
            whisper_lang = route.preferred_language if route.preferred_language in AGENT_WHISPER_TEMPLATES else "en"
            language_names = LANGUAGE_DISPLAY_NAMES.get(whisper_lang, LANGUAGE_DISPLAY_NAMES["en"])
            whisper_text = AGENT_WHISPER_TEMPLATES[whisper_lang].format(
                caller_language=language_names.get(caller_lang, LANGUAGE_NAMES.get(caller_lang, caller_lang)),
                agent_language=language_names.get(route.preferred_language, LANGUAGE_NAMES.get(route.preferred_language, route.preferred_language)),
            )
            try:
                await self._speak_to_media_session(session, whisper_text, language=whisper_lang)
            except Exception as e:
                log.warning(
                    "Agent whisper failed; continuing with bridge",
                    call_id=self.call_id,
                    extension=route.extension,
                    agent_language=whisper_lang,
                    error=str(e),
                )
        return session

    async def _select_agent_route(self, requested_queue: str | None, caller_lang: str) -> AgentRoute:
        async with AsyncSessionLocal() as db:
            # Agent claim always wins; keyword routing is only consulted if no agent was claimed.
            selected = await claim_agent_for_call(
                db,
                caller_lang=caller_lang,
                call_id=self.call_id,
                requested_queue=requested_queue,
            )
            if selected and selected.agent_id:
                self.selected_agent_profile_id = selected.agent_id
                return selected
            fallback = await get_route_for_intent(requested_queue, "transfer", db)
            return AgentRoute(
                agent_id="",
                extension=fallback.extension,
                display_name=requested_queue or "team member",
                preferred_language=fallback.agent_lang or "en",
                supported_languages=[fallback.agent_lang or "en"],
                assigned_queues=[requested_queue] if requested_queue else [],
                translation_required=(fallback.agent_lang or "en") != caller_lang,
                source=fallback.match_source,
            )

    async def _wait_for_handoff_completion(self):
        while True:
            if self.translation_task and self.translation_task.done():
                break
            await asyncio.sleep(1.0)

    async def _route_to_human_agent(self, requested_queue: str | None = None, reason: str = "transfer") -> bool:
        caller_lang = self.state.caller_lang or "en"
        route = await self._select_agent_route(requested_queue, caller_lang)
        self.selected_agent = route
        self.state.department = requested_queue or self.state.department

        if route.translation_required:
            caller_prompt = AGENT_CALLER_TRANSLATION_PROMPTS.get(caller_lang, AGENT_CALLER_TRANSLATION_PROMPTS["en"])
            try:
                await self._speak(caller_prompt, language=caller_lang)
            except Exception as e:
                log.warning(
                    "Caller translation prompt failed; continuing with bridge",
                    call_id=self.call_id,
                    caller_language=caller_lang,
                    error=str(e),
                )
        else:
            connecting = {
                "en": "One moment. Connecting you to an available agent now.",
                "es": "Un momento. Le conecto con un agente disponible.",
                "fr": "Un instant. Je vous mets en relation avec un agent disponible.",
                "it": "Un momento. La collego con un agente disponibile.",
                "he": "רגע אחד. אני מחבר אותך לנציג זמין.",
                "ro": "Un moment. Vă conectez acum cu un agent disponibil.",
            }
            await self._speak(connecting.get(caller_lang, connecting["en"]), language=caller_lang)

        try:
            session = await self._dial_agent_leg(route, caller_lang)
        except Exception as e:
            log.warning("Agent leg setup failed", extension=route.extension, error=str(e))
            await self._release_selected_agent()
            unavailable = {
                "en": "No agents are available right now. I can help you schedule a callback instead.",
                "es": "No hay agentes disponibles ahora mismo. Puedo ayudarle a programar una devolución de llamada.",
                "fr": "Aucun agent n'est disponible pour le moment. Je peux vous aider à planifier un rappel.",
                "it": "Nessun agente è disponibile in questo momento. Posso aiutarla a programmare una richiamata.",
                "he": "אין כרגע נציגים זמינים. אני יכול לעזור לך לקבוע שיחת חזרה.",
                "ro": "Nu sunt agenți disponibili chiar acum. Vă pot ajuta să programați un apel înapoi.",
            }
            await self._speak(unavailable.get(caller_lang, unavailable["en"]), language=caller_lang)
            return False
        self.agent_media_session = session
        self.handoff_active = True

        if route.translation_required:
            self.translation_task = asyncio.create_task(
                TranslationRelay(
                    call_id=self.call_id,
                    caller_sock=self.rtp_sock,
                    agent_sock=session.rtp_sock,
                    caller_lang=caller_lang,
                    agent_lang=route.preferred_language,
                ).run()
            )
            self.call_path.record(
                "translated_agent_handoff",
                extension=route.extension,
                agent_id=route.agent_id,
                caller_lang=caller_lang,
                agent_lang=route.preferred_language,
                source=route.source,
                reason=reason,
            )
        else:
            try:
                await self.ari.remove_from_bridge(session.bridge_id, session.channel_id)
            except Exception:
                log.warning("Could not remove agent from temporary bridge before handoff",
                            channel_id=session.channel_id, bridge_id=session.bridge_id)
            await self.ari.add_to_bridge(self.bridge_id, session.channel_id)
            await self.ari.hangup(session.ext_media_id)
            session.rtp_sock.close()
            _release_rtp_port(session.rtp_port)
            await self.ari.delete(f"/bridges/{session.bridge_id}")
            self.agent_media_session = None
            self.call_path.record(
                "agent_handoff",
                extension=route.extension,
                agent_id=route.agent_id,
                caller_lang=caller_lang,
                agent_lang=route.preferred_language,
                source=route.source,
                reason=reason,
            )

        await self._save_call(disposition="transferred", transferred_to=route.extension)
        await self._wait_for_handoff_completion()
        return True

    # ── Conversation loop ─────────────────────────────────────────────────────

    async def _conversation_loop(self, after_hours: bool = False):
        """Main conversation loop — listen, transcribe, respond, route."""
        max_turns = 10
        max_retries = settings.max_retries
        lang = self.state.caller_lang

        while self.state.turn_count < max_turns:
            if await self._consume_pending_hidden_mode():
                continue

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

                log.info("Listening for caller turn", call_id=self.call_id, turn=self.state.turn_count)
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
                RETRY_FIRST = {
                    "en": "I'm sorry, I didn't catch that. Could you repeat?",
                    "es": "Lo siento, no le escuché. ¿Puede repetir?",
                    "fr": "Je suis désolé, je n'ai pas entendu. Pouvez-vous répéter ?",
                    "it": "Mi dispiace, non ho sentito. Può ripetere?",
                    "de": "Entschuldigung, ich habe das nicht verstanden. Könnten Sie das wiederholen?",
                    "ro": "Îmi pare rău, nu am auzit. Puteți repeta?",
                    "he": "סליחה, לא שמעתי. האם תוכל לחזור על כך?",
                }
                RETRY_AGAIN = {
                    "en": "I'm sorry, I didn't catch that. Could you try again?",
                    "es": "Disculpe, no le escuché bien. ¿Puede intentarlo de nuevo?",
                    "fr": "Désolé, je n'ai pas bien saisi. Pouvez-vous réessayer ?",
                    "it": "Mi dispiace, non ho capito bene. Può riprovare?",
                    "de": "Entschuldigung, ich habe das nicht richtig verstanden. Könnten Sie es nochmals versuchen?",
                    "ro": "Îmi pare rău, nu am înțeles bine. Puteți încerca din nou?",
                    "he": "סליחה, לא הבנתי טוב. האם תוכל לנסות שוב?",
                }
                if self.state.turn_count == 0:
                    sorry = RETRY_FIRST.get(lang, RETRY_FIRST["en"])
                else:
                    sorry = RETRY_AGAIN.get(lang, RETRY_AGAIN["en"])
                await self._speak(sorry, language=lang)
                continue

            utterance, detected_lang, raw_utterance = listen_result
            self.state.retry_count = 0  # Reset on successful speech

            # Language lock
            if not self.state.lang_confirmed:
                self.state.caller_lang = detected_lang
                lang = detected_lang
                if self.state.turn_count >= 1:
                    self.state.lang_confirmed = True

            switch_lang = _detect_language_switch(utterance, raw_utterance)
            if switch_lang and switch_lang != lang:
                self.state.caller_lang = switch_lang
                self.state.lang_confirmed = True
                lang = switch_lang
                self.call_path.record("language_switch_requested", turn=self.state.turn_count, from_lang=detected_lang, to_lang=switch_lang)
                await self._speak(LANGUAGE_SWITCH_CONFIRMATIONS.get(switch_lang, LANGUAGE_SWITCH_CONFIRMATIONS["en"]), language=switch_lang)
                continue

            # If the caller simply starts speaking a different supported language,
            # follow them automatically instead of forcing an explicit switch command.
            if (
                detected_lang in LANGUAGE_NAMES
                and detected_lang != lang
                and len((raw_utterance or "").strip()) >= 4
            ):
                previous_lang = lang
                self.state.caller_lang = detected_lang
                self.state.lang_confirmed = True
                lang = detected_lang
                self.call_path.record("language_auto_switched", turn=self.state.turn_count, from_lang=previous_lang, to_lang=detected_lang)
                await self._speak(LANGUAGE_SWITCH_CONFIRMATIONS.get(detected_lang, LANGUAGE_SWITCH_CONFIRMATIONS["en"]), language=detected_lang)

            self.transcript_log.append(f"Caller [{detected_lang}]: {raw_utterance}")
            self.call_path.record("utterance", turn=self.state.turn_count, lang=detected_lang, text=raw_utterance[:60])

            if _is_secret_game_trigger(utterance) or _is_secret_game_trigger(raw_utterance):
                await self._enter_secret_game_mode(lang)
                continue

            if _is_top_secret_trigger(utterance) or _is_top_secret_trigger(raw_utterance):
                await self._enter_top_secret_mode(lang)
                continue

            if _is_system_demo_trigger(utterance):
                await self._enter_system_demo_mode(lang, reason="explicit")
                self.state.intent = "info"
                continue

            if self.state.top_secret_mode:
                handled = await self._handle_top_secret_turn(utterance, lang)
                if handled:
                    continue

            if self.state.secret_game_mode:
                handled = await self._handle_secret_game_turn(utterance, lang)
                if handled:
                    continue

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
                REPHRASE = {
                    "en": ("I didn't quite catch that. Are you looking to speak with someone, "
                           "schedule an appointment, or do you have a question?"),
                    "es": ("No entendí del todo. ¿Puede decirme si desea hablar con alguien, "
                           "programar una cita o tiene una pregunta?"),
                    "fr": ("Je n'ai pas bien compris. Souhaitez-vous parler à quelqu'un, "
                           "prendre un rendez-vous, ou avez-vous une question ?"),
                    "it": ("Non ho capito bene. Desidera parlare con qualcuno, "
                           "fissare un appuntamento, o ha una domanda?"),
                    "de": ("Ich habe das nicht ganz verstanden. Möchten Sie mit jemandem sprechen, "
                           "einen Termin vereinbaren oder haben Sie eine Frage?"),
                    "ro": ("Nu am înțeles bine. Doriți să vorbiți cu cineva, "
                           "să programați o întâlnire sau aveți o întrebare?"),
                    "he": ("לא הבנתי לגמרי. האם אתה מחפש לדבר עם מישהו, "
                           "לקבוע תור או שיש לך שאלה?"),
                }
                rephrase = REPHRASE.get(lang, REPHRASE["en"])
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
                    _schedule_confirm = {
                        "en": (f"Perfect. I've scheduled your callback for {chosen_slot['label']}. "
                               f"We'll call you at {self.state.caller_phone}. Is there anything else?"),
                        "es": (f"Perfecto. He programado su llamada para {chosen_slot['label']}. "
                               f"Le llamaremos al {self.state.caller_phone}. ¿Hay algo más en lo que pueda ayudarle?"),
                        "fr": (f"Parfait. J'ai planifié votre rappel pour {chosen_slot['label']}. "
                               f"Nous vous appellerons au {self.state.caller_phone}. Y a-t-il autre chose?"),
                        "it": (f"Perfetto. Ho programmato il suo richiamo per {chosen_slot['label']}. "
                               f"La chiameremo al {self.state.caller_phone}. C'è altro che posso fare?"),
                        "de": (f"Perfekt. Ich habe Ihren Rückruf für {chosen_slot['label']} geplant. "
                               f"Wir rufen Sie unter {self.state.caller_phone} an. Kann ich noch etwas für Sie tun?"),
                        "ro": (f"Perfect. Am programat apelul dvs. înapoi pentru {chosen_slot['label']}. "
                               f"Vă vom suna la {self.state.caller_phone}. Mai pot ajuta cu ceva?"),
                        "he": (f"מצוין. תזמנתי את ההתקשרות שלך בחזרה ל-{chosen_slot['label']}. "
                               f"נתקשר אליך ל-{self.state.caller_phone}. האם יש עוד משהו?"),
                    }
                    confirm = _schedule_confirm.get(lang, _schedule_confirm["en"])
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
                handed_off = await self._route_to_human_agent(self.state.department, reason="intent_transfer")
                if handed_off:
                    return
                continue

            # ── General conversation ──────────────────────────────────
            else:
                response = await generate_response(utterance, self.state)
                self.transcript_log.append(f"Agent [{lang}]: {response}")
                self.call_path.record("general_response", intent=intent, turn=self.state.turn_count)
                await self._speak(response, language=lang)

            # Natural farewell detection — all 7 supported languages
            farewell_words = [
                # English
                "goodbye", "bye", "thank you", "thanks", "that's all", "that is all",
                # Spanish
                "adiós", "adios", "gracias", "hasta luego", "hasta pronto", "chao",
                # French
                "au revoir", "merci", "bonne journée", "c'est tout", "cest tout",
                # Italian
                "arrivederci", "grazie", "a presto", "ciao",
                # German
                "auf wiedersehen", "tschüss", "tschuss", "danke", "danke schön", "das war alles",
                # Romanian
                "la revedere", "mulțumesc", "multumesc", "pa pa",
                # Hebrew
                "shalom", "lehitraot", "toda", "zeh hakol",
            ]
            _farewell_msgs = {
                "en": "Thank you for calling. Have a great day!",
                "es": "¡Gracias por llamar. Que tenga un buen día!",
                "fr": "Merci d'avoir appelé. Bonne journée!",
                "it": "Grazie per aver chiamato. Buona giornata!",
                "de": "Danke für Ihren Anruf. Auf Wiedersehen!",
                "ro": "Vă mulțumim că ați sunat. O zi bună!",
                "he": "תודה שהתקשרת. יום טוב!",
            }
            if any(word in utterance.lower() for word in farewell_words):
                farewell = _farewell_msgs.get(lang, _farewell_msgs["en"])
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
            DTMF_INVALID = {
                "en": "That option isn't valid. Connecting you to the operator.",
                "es": "Esa opción no es válida. Le paso al operador.",
                "fr": "Cette option n'est pas valide. Je vous passe l'opérateur.",
                "it": "Questa opzione non è valida. La metto in contatto con l'operatore.",
                "de": "Diese Option ist nicht gültig. Ich verbinde Sie mit dem Operator.",
                "ro": "Această opțiune nu este validă. Vă transfer la operator.",
                "he": "האפשרות הזו אינה חוקית. מחבר אותך לאופרטור.",
            }
            await self._speak(DTMF_INVALID.get(lang, DTMF_INVALID["en"]), language=lang)
            extension = settings.operator_extension

        DTMF_CONNECTING = {
            "en": "One moment, connecting you now.",
            "es": "Un momento, le comunico ahora mismo.",
            "fr": "Un instant, je vous mets en relation.",
            "it": "Un momento, la metto in contatto adesso.",
            "de": "Einen Moment, ich verbinde Sie jetzt.",
            "ro": "Un moment, vă transfer acum.",
            "he": "רגע, מחבר אותך עכשיו.",
        }
        await self._speak(DTMF_CONNECTING.get(lang, DTMF_CONNECTING["en"]), language=lang)
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

        FALLBACK_MSG = {
            "en": "Let me connect you with a team member who can assist you better.",
            "es": "Permítame conectarle con un miembro de nuestro equipo que podrá ayudarle.",
            "fr": "Laissez-moi vous mettre en relation avec un membre de notre équipe qui pourra mieux vous aider.",
            "it": "Lasci che la metta in contatto con un membro del team che potrà assisterla meglio.",
            "de": "Lassen Sie mich Sie mit einem Teammitglied verbinden, das Ihnen besser helfen kann.",
            "ro": "Permiteți-mi să vă conectez cu un membru al echipei care vă poate ajuta mai bine.",
            "he": "הרשה לי לחבר אותך עם חבר צוות שיוכל לסייע לך טוב יותר.",
        }
        await self._speak(FALLBACK_MSG.get(lang, FALLBACK_MSG["en"]), language=lang)
        await asyncio.sleep(0.5)
        await self._route_to_human_agent("operator", reason=f"fallback:{reason}")

    # ── Listen ────────────────────────────────────────────────────────────────

    async def _listen(self) -> tuple[str, str, str] | None:
        """
        Read audio from RTP until Silero VAD detects end-of-speech.
        Returns (english_transcript, detected_lang, raw_transcript) or None on silence/timeout.
        """
        audio_buffer = bytearray()
        speech_started = False
        max_frames = int(MAX_UTTERANCE_SECONDS * 1000 / FRAME_MS)
        total_frames = 0
        no_data_count = 0
        # Be a bit more patient on the phone before declaring silence; short
        # mobile/WAN gaps and caller hesitation are common in live use.
        effective_silence_timeout = max(settings.silence_timeout_sec, 12)
        max_initial_silence_frames = int(effective_silence_timeout * 1000 / FRAME_MS)
        loop = asyncio.get_event_loop()

        vad = self._get_vad()
        vad.reset()

        while total_frames < max_frames:
            try:
                data = await loop.run_in_executor(
                    None, lambda: _recv_nonblocking(self.rtp_sock.sock, 2048)
                )
                if data and len(data) > RTP_HEADER_SIZE:
                    payload = _ulaw_8k_to_pcm16_16k(data[RTP_HEADER_SIZE:])
                    no_data_count = 0
                    vad_event = vad.process_chunk(payload)

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
        raw_text = result.text
        english_text = raw_text

        if detected_lang != "en":
            english_text, _ = await ensure_english(raw_text, detected_lang)
            log.info("Translated caller utterance",
                     original=raw_text[:60],
                     translated=english_text[:60],
                     lang=detected_lang)

        return english_text, detected_lang, raw_text

    async def _listen_for_hidden_mode_barge_in(self, stop_event: asyncio.Event) -> bool:
        if not self.rtp_sock:
            return False
        audio_buffer = bytearray()
        speech_started = False
        no_data_count = 0
        total_frames = 0
        max_frames = int(12 * 1000 / FRAME_MS)
        loop = asyncio.get_event_loop()
        vad = SileroVADEngine(
            threshold=settings.vad_threshold,
            min_silence_ms=settings.vad_min_silence_ms,
            speech_pad_ms=settings.vad_speech_pad_ms,
        )
        vad.reset()

        while not stop_event.is_set() and total_frames < max_frames:
            try:
                data = await loop.run_in_executor(
                    None, lambda: _recv_nonblocking(self.rtp_sock.sock, 2048)
                )
                if data and len(data) > RTP_HEADER_SIZE:
                    payload = _ulaw_8k_to_pcm16_16k(data[RTP_HEADER_SIZE:])
                    no_data_count = 0
                    vad_event = vad.process_chunk(payload)
                    if vad_event and "start" in vad_event:
                        speech_started = True
                    if speech_started:
                        audio_buffer.extend(payload)
                    if vad_event and "end" in vad_event and speech_started:
                        if len(audio_buffer) >= BYTES_PER_FRAME * 5:
                            result = await loop.run_in_executor(
                                None, transcribe_pcm, bytes(audio_buffer), SAMPLE_RATE, 1, None
                            )
                            if result and result.text:
                                heard = result.text
                                english_text = heard
                                if result.language != "en":
                                    english_text, _ = await ensure_english(heard, result.language)
                                if _is_secret_game_trigger(english_text) or _is_secret_game_trigger(heard):
                                    self._pending_hidden_mode = "secret_game"
                                    self._pending_hidden_mode_lang = result.language if result.language in LANGUAGE_NAMES else "en"
                                    log.info("Secret game barge-in detected",
                                             heard=heard[:80], translated=english_text[:80], lang=self._pending_hidden_mode_lang, call_id=self.call_id)
                                    stop_event.set()
                                    return True
                                if _is_system_demo_trigger(english_text) or _is_system_demo_trigger(heard):
                                    self._pending_hidden_mode = "system_demo"
                                    self._pending_hidden_mode_lang = result.language if result.language in LANGUAGE_NAMES else "en"
                                    log.info("System demo barge-in detected",
                                             heard=heard[:80], translated=english_text[:80], lang=self._pending_hidden_mode_lang, call_id=self.call_id)
                                    stop_event.set()
                                    return True
                                if _is_top_secret_trigger(english_text) or _is_top_secret_trigger(heard):
                                    self._pending_hidden_mode = "top_secret"
                                    self._pending_hidden_mode_lang = result.language if result.language in LANGUAGE_NAMES else "en"
                                    log.info("Top secret barge-in detected",
                                             heard=heard[:80], translated=english_text[:80], lang=self._pending_hidden_mode_lang, call_id=self.call_id)
                                    stop_event.set()
                                    return True
                        audio_buffer = bytearray()
                        speech_started = False
                        vad.reset()
                else:
                    await asyncio.sleep(0.02)
                    no_data_count += 1
                    if not speech_started and no_data_count >= int(3000 / FRAME_MS):
                        return False
            except Exception:
                await asyncio.sleep(0.02)
            total_frames += 1
        return False

    # ── Speak ─────────────────────────────────────────────────────────────────

    async def _speak(self, text: str, language: str = "en", voice_override: str = ""):
        log.info("Speaking", text=text[:80], lang=language, call_id=self.call_id)
        self.transcript_log.append(f"Agent [{language}]: {text}")
        loop = asyncio.get_event_loop()
        pcm = await loop.run_in_executor(None, synthesize_pcm, text, language, voice_override)
        if pcm and self.rtp_sock:
            stop_event = asyncio.Event()
            barge_task = asyncio.create_task(self._listen_for_hidden_mode_barge_in(stop_event))
            try:
                await self.rtp_sock.stream_pcm(pcm, stop_event=stop_event)
            finally:
                stop_event.set()
                await barge_task
            await asyncio.sleep(0.2)

    async def _speak_system_demo_script(self, language: str = "en"):
        segments = _system_demo_segments()
        for index, segment in enumerate(segments):
            voice = SYSTEM_DEMO_VOICE_CYCLE[index % len(SYSTEM_DEMO_VOICE_CYCLE)]
            await self._speak(segment, language=language, voice_override=voice)

    def _start_vtiger_lookup(self):
        if not settings.vtiger_enabled or not self.crm_normalized_phone:
            return
        self.crm_lookup_task = asyncio.create_task(self._background_vtiger_lookup())

    async def _background_vtiger_lookup(self):
        now = datetime.utcnow()
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(CRMCallSync).where(CRMCallSync.call_id == self.call_id))
            call_sync = result.scalars().first()
            if not call_sync:
                call_sync = CRMCallSync(
                    call_id=self.call_id,
                    normalized_phone=self.crm_normalized_phone,
                    crm_provider=self.crm_provider,
                    lookup_status="pending",
                    sync_status="pending",
                    created_at=now,
                    updated_at=now,
                )
                db.add(call_sync)
                await db.commit()

        client = VtigerClient.from_settings()
        if not client.configured():
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(CRMCallSync).where(CRMCallSync.call_id == self.call_id))
                call_sync = result.scalars().first()
                if call_sync:
                    call_sync.lookup_status = "disabled"
                    call_sync.sync_status = "disabled"
                    call_sync.last_error = "Vtiger not configured"
                    call_sync.updated_at = datetime.utcnow()
                    await db.commit()
            return

        try:
            record = await client.ensure_caller(self.caller_id, default_module=settings.vtiger_default_module)
            if not record:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(select(CRMCallSync).where(CRMCallSync.call_id == self.call_id))
                    call_sync = result.scalars().first()
                    if call_sync:
                        call_sync.lookup_status = "not_found"
                        call_sync.updated_at = datetime.utcnow()
                        await db.commit()
                return

            self.crm_module = record.module
            self.crm_record_id = record.record_id
            self.crm_record_label = record.label

            async with AsyncSessionLocal() as db:
                link_result = await db.execute(
                    select(CRMRecordLink).where(
                        CRMRecordLink.crm_provider == self.crm_provider,
                        CRMRecordLink.normalized_phone == self.crm_normalized_phone,
                    )
                )
                link = link_result.scalars().first()
                now = datetime.utcnow()
                if link:
                    link.phone_number = self.caller_id
                    link.crm_module = record.module
                    link.crm_record_id = record.record_id
                    link.crm_record_label = record.label
                    link.updated_at = now
                    link.last_seen_at = now
                else:
                    db.add(
                        CRMRecordLink(
                            phone_number=self.caller_id,
                            normalized_phone=self.crm_normalized_phone,
                            crm_provider=self.crm_provider,
                            crm_module=record.module,
                            crm_record_id=record.record_id,
                            crm_record_label=record.label,
                            created_at=now,
                            updated_at=now,
                            last_seen_at=now,
                        )
                    )
                sync_result = await db.execute(select(CRMCallSync).where(CRMCallSync.call_id == self.call_id))
                call_sync = sync_result.scalars().first()
                if call_sync:
                    call_sync.crm_module = record.module
                    call_sync.crm_record_id = record.record_id
                    call_sync.lookup_status = "matched" if not record.created else "created"
                    call_sync.updated_at = now
                await db.commit()
            log.info("Vtiger caller linked", call_id=self.call_id, module=record.module, record_id=record.record_id, created=record.created)
        except Exception as exc:
            log.warning("Vtiger caller lookup/create failed", call_id=self.call_id, error=str(exc))
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(CRMCallSync).where(CRMCallSync.call_id == self.call_id))
                call_sync = result.scalars().first()
                if call_sync:
                    call_sync.lookup_status = "error"
                    call_sync.last_error = str(exc)
                    call_sync.updated_at = datetime.utcnow()
                    await db.commit()

    async def _sync_vtiger_on_teardown(self):
        if not settings.vtiger_enabled:
            return
        if self.crm_lookup_task and not self.crm_lookup_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self.crm_lookup_task), timeout=5)
            except Exception:
                pass
        if not self.crm_record_id or not self.crm_module:
            return

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(CallLog).where(CallLog.call_id == self.call_id))
            cl = result.scalars().first()
            if not cl:
                return

            note_parts = [
                f"[Helix Call {datetime.utcnow().isoformat(timespec='seconds')} UTC]",
                f"Caller: {self.caller_id or 'unknown'}",
                f"Dialed: {self.called_number or 'unknown'}",
                f"Disposition: {cl.disposition or 'unknown'}",
                f"Intent: {cl.intent or 'unknown'}",
            ]
            if cl.intent_detail:
                note_parts.append(f"Intent detail: {cl.intent_detail}")
            if cl.duration_seconds is not None:
                note_parts.append(f"Duration seconds: {round(cl.duration_seconds, 1)}")
            if cl.summary:
                note_parts.append(f"Summary: {cl.summary}")
            if cl.transcript:
                transcript_excerpt = cl.transcript.strip()
                if len(transcript_excerpt) > 2000:
                    transcript_excerpt = transcript_excerpt[:2000].rstrip() + "..."
                note_parts.append("Transcript:\n" + transcript_excerpt)
            note = "\n".join(note_parts)

        client = VtigerClient.from_settings()
        now = datetime.utcnow()
        try:
            await client.append_note_to_record(self.crm_module, self.crm_record_id, note)
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(CRMCallSync).where(CRMCallSync.call_id == self.call_id))
                call_sync = result.scalars().first()
                if call_sync:
                    call_sync.crm_module = self.crm_module
                    call_sync.crm_record_id = self.crm_record_id
                    call_sync.sync_status = "synced"
                    call_sync.synced_at = now
                    call_sync.updated_at = now
                    await db.commit()
            log.info("Vtiger call synced", call_id=self.call_id, module=self.crm_module, record_id=self.crm_record_id)
        except Exception as exc:
            log.warning("Vtiger teardown sync failed", call_id=self.call_id, error=str(exc))
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(CRMCallSync).where(CRMCallSync.call_id == self.call_id))
                call_sync = result.scalars().first()
                if call_sync:
                    call_sync.crm_module = self.crm_module
                    call_sync.crm_record_id = self.crm_record_id
                    call_sync.sync_status = "error"
                    call_sync.last_error = str(exc)
                    call_sync.updated_at = now
                    await db.commit()

    # ── Media setup ───────────────────────────────────────────────────────────

    async def _setup_media(self):
        self.rtp_port = await _allocate_rtp_port()
        self.rtp_sock = RTPSocket(settings.agent_rtp_host, self.rtp_port)
        log.info("_setup_media: RTP socket bound", port=self.rtp_port)

        bridge = await self.ari.create_bridge()
        if not bridge:
            raise RuntimeError("ARI create_bridge failed — check ARI POST error above for status/body")
        self.bridge_id = bridge["id"]
        log.info("_setup_media: bridge created", bridge_id=self.bridge_id)

        await self.ari.add_to_bridge(self.bridge_id, self.channel_id)
        log.info("_setup_media: caller added to bridge")

        rtp_advertise = settings.agent_rtp_advertise_host or settings.agent_rtp_host
        ext_host = f"{rtp_advertise}:{self.rtp_port}"
        log.info("_setup_media: creating ExternalMedia", ext_host=ext_host)
        ext_media = await self.ari.create_external_media(settings.asterisk_app_name, ext_host)
        if not ext_media:
            raise RuntimeError("ARI create_external_media failed — check ARI POST error above for status/body")
        self.ext_media_id = ext_media["id"]
        log.info("_setup_media: ExternalMedia channel created", ext_media_id=self.ext_media_id)

        ast_rtp_addr = await self.ari.get_channel_var(self.ext_media_id, "UNICASTRTP_LOCAL_ADDRESS")
        ast_rtp_port = await self.ari.get_channel_var(self.ext_media_id, "UNICASTRTP_LOCAL_PORT")
        log.info("_setup_media: UNICASTRTP vars",
                 ast_rtp_addr=ast_rtp_addr, ast_rtp_port=ast_rtp_port)

        if ast_rtp_addr and ast_rtp_port:
            self.rtp_sock.asterisk_addr = (ast_rtp_addr, int(ast_rtp_port))
            log.info("RTP bridge established",
                     our_port=self.rtp_port,
                     asterisk_addr=self.rtp_sock.asterisk_addr)
        else:
            log.warning("_setup_media: UNICASTRTP vars empty — RTP send path will be dead",
                        ext_media_id=self.ext_media_id)

        await self.ari.add_to_bridge(self.bridge_id, self.ext_media_id)
        log.info("_setup_media: ExternalMedia added to bridge — media path active")
        self.call_path.record("media_ready", rtp_port=self.rtp_port)

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _save_call(self, disposition: str, transferred_to: str | None = None,
                          appointment_id: str | None = None,
                          preserve_existing_disposition: bool = False):
        """Update the CallLog record with final state."""
        full_transcript = "\n".join(self.transcript_log)
        summary = await generate_call_summary(self.state, full_transcript)
        final_disposition = disposition

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(select(CallLog).where(CallLog.call_id == self.call_id))
            cl = result.scalars().first()
            if cl:
                cl.transcript = full_transcript
                cl.intent = self.state.intent
                cl.intent_detail = self.state.department
                if preserve_existing_disposition and cl.disposition:
                    final_disposition = cl.disposition
                cl.disposition = final_disposition
                if transferred_to:
                    cl.transferred_to = transferred_to
                if appointment_id:
                    cl.appointment_id = appointment_id
                cl.notes = self.call_path.to_json()
                if summary:
                    cl.summary = summary
                await db.commit()
                self._queue_call_summary_email(
                    caller_id=cl.caller_id or self.caller_id,
                    disposition=final_disposition,
                    summary=summary or cl.summary or "",
                    transcript=full_transcript,
                )

    async def _finalize_transcript(self):
        """Save transcript + call path for calls that ended in the conversation loop."""
        await self._save_call(disposition="hangup", preserve_existing_disposition=True)

    def _queue_call_summary_email(
        self,
        *,
        caller_id: str,
        disposition: str,
        summary: str,
        transcript: str,
    ) -> None:
        if self._email_sent or not settings.notify_email.strip():
            return
        try:
            asyncio.create_task(
                self._send_call_summary_email(
                    call_id=self.call_id,
                    caller_id=caller_id,
                    disposition=disposition,
                    summary=summary,
                    transcript=transcript,
                )
            )
            self._email_sent = True
        except Exception as exc:
            log.warning("Failed to schedule call summary email", call_id=self.call_id, error=str(exc))

    async def _send_call_summary_email(
        self,
        call_id: str,
        caller_id: str,
        disposition: str,
        summary: str,
        transcript: str,
    ) -> None:
        try:
            transcript_lines = [line for line in transcript.splitlines() if line.strip()]
            transcript_excerpt = "\n".join(transcript_lines[:20]) or "(no transcript)"
            summary_text = summary.strip() or "(no summary)"

            message = EmailMessage()
            message["Subject"] = f"[Helix] Call from {caller_id} — {disposition}"
            message["From"] = settings.smtp_from.strip() or settings.notify_email.strip()
            message["To"] = settings.notify_email.strip()
            message.set_content(
                f"Call ID: {call_id}\n"
                f"Caller: {caller_id}\n"
                f"Disposition: {disposition}\n\n"
                f"Summary:\n{summary_text}\n\n"
                f"Transcript (first 20 lines):\n{transcript_excerpt}\n"
            )

            def _send() -> None:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                    if settings.smtp_user.strip():
                        smtp.login(settings.smtp_user, settings.smtp_pass)
                    smtp.send_message(message)

            await asyncio.get_event_loop().run_in_executor(None, _send)
            log.info("Call summary email sent", call_id=call_id, recipient=settings.notify_email.strip())
        except Exception as exc:
            log.warning("Call summary email failed", call_id=call_id, error=str(exc))

    # ── Teardown ──────────────────────────────────────────────────────────────

    async def _teardown(self):
        ended_at = datetime.utcnow()
        duration = (ended_at - self.started_at).total_seconds()
        self.call_path.record("teardown", duration=duration)

        if self.translation_task:
            self.translation_task.cancel()
            try:
                await self.translation_task
            except Exception:
                pass
            self.translation_task = None

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
            else:
                # Background insert may not have completed yet (very short call).
                # Insert a minimal record now so call history is never lost.
                log.warning("_teardown: no CallLog row found — inserting now (background write raced)",
                            call_id=self.call_id)
                try:
                    cl = CallLog(
                        call_id=self.call_id,
                        direction="inbound",
                        caller_id=self.caller_id,
                        called_number=self.called_number,
                        started_at=self.started_at,
                        ended_at=ended_at,
                        duration_seconds=duration,
                        disposition="cancelled",
                        notes=self.call_path.to_json(),
                    )
                    db.add(cl)
                    await db.commit()
                except Exception as _e:
                    log.error("_teardown: fallback CallLog insert failed",
                              call_id=self.call_id, error=str(_e))

        await self._sync_vtiger_on_teardown()
        await self._release_selected_agent()

        if self.agent_media_session:
            try:
                await self.ari.hangup(self.agent_media_session.ext_media_id)
            except Exception:
                pass
            try:
                await self.ari.delete(f"/bridges/{self.agent_media_session.bridge_id}")
            except Exception:
                pass
            self.agent_media_session.rtp_sock.close()
            _release_rtp_port(self.agent_media_session.rtp_port)
            self.agent_media_session = None

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
_active_agent_legs: dict[str, "CallHandler"] = {}
_shared_ari_client: "ARIClient | None" = None


def get_shared_ari_client() -> "ARIClient | None":
    return _shared_ari_client


# Module-level registry of in-progress calls.
# Keyed by channel_id; value is (CallHandler, asyncio.Task).
# Populated by run_ari_agent(); read by /api/calls/active.
_active_calls: dict[str, tuple["CallHandler", "asyncio.Task"]] = {}


def get_active_calls() -> list[dict]:
    """Return a snapshot of currently active calls for the API."""
    import datetime, time
    result = []
    snapshot = _active_calls.copy()
    for channel_id, (handler, task) in snapshot.items():
        if task.done():
            continue
        elapsed = 0
        if handler.started_at:
            try:
                started = handler.started_at
                if isinstance(started, str):
                    started = datetime.datetime.fromisoformat(started)
                elapsed = int((datetime.datetime.utcnow() - started).total_seconds())
            except Exception:
                pass
        result.append({
            "call_id":    handler.call_id,
            "channel_id": channel_id,
            "caller_id":  handler.caller_id,
            "started_at": str(handler.started_at),
            "elapsed_seconds": elapsed,
        })
    return result


async def _cleanup_stale_external_media(ari: ARIClient):
    """Best-effort cleanup for orphaned ExternalMedia channels left behind by prior crashes/restarts."""
    try:
        channels = await ari.list_channels()
    except Exception as e:
        log.warning("Failed to list ARI channels for startup cleanup", error=str(e))
        return

    stale = [ch for ch in channels if (ch.get("name") or "").startswith("UnicastRTP/")]
    if not stale:
        return

    cleaned = 0
    for channel in stale:
        channel_id = channel.get("id")
        if not channel_id:
            continue
        try:
            await ari.hangup(channel_id)
            cleaned += 1
        except Exception as e:
            log.warning("Failed to hang up stale ExternalMedia channel",
                        channel_id=channel_id, error=str(e))
    log.info("Startup ExternalMedia cleanup completed", found=len(stale), cleaned=cleaned)


async def _allocate_rtp_port() -> int:
    # _port_lock prevents two concurrent calls from claiming the same port.
    # Without the lock two callers arriving simultaneously can both see the same
    # port as unallocated and both add it to _port_pool — one call then gets
    # silent one-way audio with no error in the logs.
    async with _port_lock:
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
    global _shared_ari_client
    ari = ARIClient()
    await ari.start()
    _shared_ari_client = ari
    await _cleanup_stale_external_media(ari)

    ws_url = (
        f"ws://{settings.asterisk_host}:{settings.asterisk_ari_port}"
        f"/ari/events?api_key={settings.asterisk_ari_user}:{settings.asterisk_ari_password}"
        f"&app={settings.asterisk_app_name}&subscribeAll=false"
    )

    # channel_id → (CallHandler, asyncio.Task)
    global _active_calls
    active_calls = _active_calls  # module-level dict shared with /api/calls/active

    log.info("Connecting to Asterisk ARI", url=ws_url)

    try:
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
                        channel_name = channel.get("name", "")
                        caller_id = channel.get("caller", {}).get("number", "unknown")
                        args = event.get("args", [])
                        called_number = args[1] if len(args) > 1 else "unknown"

                        if args and args[0] == "agent-leg":
                            token = args[1] if len(args) > 1 else ""
                            future = _pending_agent_legs.pop(token, None)
                            if future and not future.done():
                                future.set_result({
                                    "channel_id": channel_id,
                                    "channel_name": channel_name,
                                    "caller_id": caller_id,
                                })
                                log.info("Outbound agent leg entered Stasis",
                                         channel_id=channel_id,
                                         extension=caller_id,
                                         token=token[:8])
                            else:
                                log.warning("Agent leg arrived without pending future",
                                            channel_id=channel_id, token=token[:8])
                            continue

                        # ExternalMedia channels also enter the same Stasis app.
                        # They are transport legs, not new inbound calls.
                        if channel_name.startswith("UnicastRTP/"):
                            log.debug("Ignoring ExternalMedia StasisStart",
                                      channel_id=channel_id, channel_name=channel_name)
                            continue

                        log.info("StasisStart", channel_id=channel_id, caller=caller_id)

                        dtmf_queue: asyncio.Queue = asyncio.Queue()
                        handler = CallHandler(ari, channel_id, caller_id, called_number, dtmf_queue)
                        task = asyncio.create_task(handler.run())
                        active_calls[channel_id] = (handler, task)
                        # Yield to the event loop so the CallHandler task starts
                        # executing immediately. Without this, the ws receive loop
                        # holds the event loop and the handler task stays frozen
                        # until the next WebSocket message arrives — which may be
                        # ChannelHangupRequest, cancelling the task before it ran
                        # a single line.
                        await asyncio.sleep(0)

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
                        # StasisEnd fires when a channel leaves the Stasis application
                        # context — this includes the normal case where the caller
                        # channel is moved into a mixing bridge via add_to_bridge().
                        # Cancelling the handler here kills the call mid-setup.
                        #
                        # We log it but do NOT cancel the task or remove from
                        # active_calls here. Actual call teardown is driven by
                        # ChannelDestroyed (caller physically hung up) or by the
                        # CallHandler itself completing/erroring.
                        if channel_id in active_calls:
                            handler, _ = active_calls[channel_id]
                            log.info("StasisEnd — channel left Stasis context (bridge transition or hangup)",
                                     channel_id=channel_id, call_id=handler.call_id)
                        else:
                            log.debug("StasisEnd for untracked channel (ExternalMedia/relay/snoop)",
                                      channel_id=channel_id)

                    elif event_type == "ChannelDestroyed":
                        # ChannelDestroyed is the authoritative signal that the caller
                        # has physically hung up and the channel is gone. This is the
                        # correct place to cancel the call handler.
                        channel_id = event.get("channel", {}).get("id")
                        if channel_id in active_calls:
                            handler, task = active_calls.pop(channel_id)
                            task.cancel()
                            log.info("ChannelDestroyed — cancelling call handler",
                                     channel_id=channel_id, call_id=handler.call_id)
                        elif channel_id in _active_agent_legs:
                            handler = _active_agent_legs.pop(channel_id)
                            log.info("ChannelDestroyed — releasing claimed agent leg",
                                     channel_id=channel_id, call_id=handler.call_id)
                            await handler._release_selected_agent()

                    elif event_type == "ChannelHangupRequest":
                        # ChannelHangupRequest fires when the far end sends BYE but
                        # the channel is not yet destroyed. Do NOT cancel the handler
                        # here — ChannelDestroyed is the authoritative signal and will
                        # follow shortly. Cancelling here races against handler startup
                        # and can kill the call silently before media setup begins.
                        channel_id = event.get("channel", {}).get("id")
                        if channel_id in active_calls:
                            handler, _ = active_calls[channel_id]
                            log.info("ChannelHangupRequest — noting hangup, awaiting ChannelDestroyed",
                                     channel_id=channel_id, call_id=handler.call_id)

    finally:
        _shared_ari_client = None
        await ari.stop()


# ── Translation Relay ─────────────────────────────────────────────────────────

class TranslationRelay:
    """
    Minimal real-time bidirectional translation relay for agent handoff.

    Each side stays in its own bridge with its own ExternalMedia socket:
      - caller_sock receives caller audio and plays translated agent audio
      - agent_sock receives agent audio and plays translated caller audio
    """

    def __init__(
        self,
        *,
        call_id: str,
        caller_sock: RTPSocket,
        agent_sock: RTPSocket,
        caller_lang: str,
        agent_lang: str = "en",
    ):
        self.call_id = call_id
        self.caller_sock = caller_sock
        self.agent_sock = agent_sock
        self.caller_lang = caller_lang
        self.agent_lang = agent_lang
        self._running = True
        self._started_at = time.monotonic()
        self._last_activity = self._started_at
        self._stall_warned_at = 0.0
        self._stall_errored_at = 0.0
        self._caller_to_agent_failures = 0
        self._agent_to_caller_failures = 0

    async def run(self):
        log.info("TranslationRelay starting", caller_lang=self.caller_lang, agent_lang=self.agent_lang)
        try:
            await asyncio.gather(
                self._translate_loop(
                    sock=self.caller_sock,
                    src_lang=self.caller_lang,
                    tgt_lang=self.agent_lang,
                    output_sock=self.agent_sock,
                    label="caller→agent",
                ),
                self._translate_loop(
                    sock=self.agent_sock,
                    src_lang=self.agent_lang,
                    tgt_lang=self.caller_lang,
                    output_sock=self.caller_sock,
                    label="agent→caller",
                ),
                self._watchdog(),
            )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("TranslationRelay.run error", error=str(e), exc_info=True)
        finally:
            duration = time.monotonic() - self._started_at
            log.info(
                "TranslationRelay stopped",
                call_id=self.call_id,
                caller_language=self.caller_lang,
                agent_language=self.agent_lang,
                duration_seconds=round(duration, 2),
                caller_to_agent_failures=self._caller_to_agent_failures,
                agent_to_caller_failures=self._agent_to_caller_failures,
            )

    async def _watchdog(self):
        while self._running:
            await asyncio.sleep(10)
            idle = time.monotonic() - self._last_activity
            if idle < 30:
                self._stall_warned_at = 0.0
                self._stall_errored_at = 0.0
            elif idle >= 60 and self._stall_errored_at == 0.0:
                self._stall_errored_at = time.monotonic()
                log.error(
                    "TranslationRelay audio stalled >60s",
                    caller_language=self.caller_lang,
                    agent_language=self.agent_lang,
                    idle_seconds=int(idle),
                )
            elif idle >= 30 and self._stall_warned_at == 0.0:
                self._stall_warned_at = time.monotonic()
                log.warning(
                    "TranslationRelay audio stalled",
                    caller_language=self.caller_lang,
                    agent_language=self.agent_lang,
                    idle_seconds=int(idle),
                )

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
                        self._last_activity = time.monotonic()
                        payload = _ulaw_8k_to_pcm16_16k(data[RTP_HEADER_SIZE:])
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
                    await output_sock.stream_pcm(pcm)
                    log.info("Relay played translation", direction=label, tgt=tgt_lang, text=translated[:60])

            except asyncio.CancelledError:
                break
            except Exception as e:
                if label == "caller→agent":
                    self._caller_to_agent_failures += 1
                else:
                    self._agent_to_caller_failures += 1
                log.error("TranslationRelay._translate_loop error", direction=label, error=str(e))
                await asyncio.sleep(0.5)

        log.info("Translation loop stopped", direction=label)

    def stop(self):
        self._running = False
