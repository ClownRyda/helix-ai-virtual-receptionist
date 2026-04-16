"""
Central configuration — all values sourced from environment / .env file.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    # ── Asterisk ARI ────────────────────────────────────────────
    asterisk_host: str = Field("localhost", env="ASTERISK_HOST")
    asterisk_ari_port: int = Field(8088, env="ASTERISK_ARI_PORT")
    asterisk_ari_user: str = Field("pbx-agent", env="ASTERISK_ARI_USER")
    asterisk_ari_password: str = Field("CHANGE_ME", env="ASTERISK_ARI_PASSWORD")
    asterisk_app_name: str = Field("pbx-agent", env="ASTERISK_APP_NAME")

    # RTP listen address (bind) — use 0.0.0.0 in Docker bridge mode
    agent_rtp_host: str = Field("127.0.0.1", env="AGENT_RTP_HOST")
    agent_rtp_port_start: int = Field(20000, env="AGENT_RTP_PORT_START")
    agent_rtp_port_end: int = Field(20100, env="AGENT_RTP_PORT_END")
    # RTP advertise address — what Asterisk is told to send RTP to.
    # In Docker bridge mode, set this to the agent container's hostname
    # or the Docker service name so Asterisk can route back.
    # Defaults to agent_rtp_host when not set.
    agent_rtp_advertise_host: str = Field("", env="AGENT_RTP_ADVERTISE_HOST")

    # ── Silero VAD ──────────────────────────────────────────────
    vad_threshold: float = Field(0.5, env="VAD_THRESHOLD")
    vad_min_silence_ms: int = Field(600, env="VAD_MIN_SILENCE_MS")
    vad_speech_pad_ms: int = Field(100, env="VAD_SPEECH_PAD_MS")

    # ── Whisper STT ─────────────────────────────────────────────
    whisper_model: str = Field("base.en", env="WHISPER_MODEL")
    whisper_device: str = Field("cuda", env="WHISPER_DEVICE")
    whisper_compute_type: str = Field("float16", env="WHISPER_COMPUTE_TYPE")

    # ── Ollama LLM ──────────────────────────────────────────────
    ollama_host: str = Field("http://localhost:11434", env="OLLAMA_HOST")
    ollama_model: str = Field("llama3.1:8b", env="OLLAMA_MODEL")
    ollama_timeout: int = Field(30, env="OLLAMA_TIMEOUT")

    # ── Kokoro TTS ───────────────────────────────────────────────
    # Voice overrides per language (leave blank to use built-in defaults).
    # Full voice list: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
    # Kokoro supports: EN (a/b), ES (e), FR (f), IT (i)
    # DE, RO, HE fall back to espeak-ng automatically (no Kokoro support)
    kokoro_voice_en: str = Field("af_heart", env="KOKORO_VOICE_EN")
    kokoro_voice_es: str = Field("ef_dora", env="KOKORO_VOICE_ES")
    kokoro_voice_fr: str = Field("ff_siwis", env="KOKORO_VOICE_FR")
    kokoro_voice_it: str = Field("if_sara", env="KOKORO_VOICE_IT")

    # ── Multilingual / translation ───────────────────────────────
    supported_languages: str = Field("en,es,fr,it,de,ro,he", env="SUPPORTED_LANGUAGES")
    auto_detect_language: bool = Field(True, env="AUTO_DETECT_LANGUAGE")
    whisper_model_multilingual: str = Field("base", env="WHISPER_MODEL_MULTILINGUAL")

    # ── Google Calendar ─────────────────────────────────────────
    google_credentials_file: str = Field("credentials.json", env="GOOGLE_CREDENTIALS_FILE")
    google_token_file: str = Field("token.json", env="GOOGLE_TOKEN_FILE")
    google_calendar_id: str = Field("primary", env="GOOGLE_CALENDAR_ID")
    appointment_slot_minutes: int = Field(30, env="APPOINTMENT_SLOT_MINUTES")
    availability_lookahead_days: int = Field(7, env="AVAILABILITY_LOOKAHEAD_DAYS")

    # ── Business hours ──────────────────────────────────────────
    business_hours_start: int = Field(9, env="BUSINESS_HOURS_START")   # 9 AM
    business_hours_end: int = Field(17, env="BUSINESS_HOURS_END")       # 5 PM
    business_timezone: str = Field("America/Chicago", env="BUSINESS_TIMEZONE")

    # ── After-hours / holiday behavior ──────────────────────────
    # Comma-separated ISO dates that are holidays, e.g. "2026-12-25,2027-01-01"
    holiday_dates: str = Field("", env="HOLIDAY_DATES")

    # What to offer callers outside business hours or on holidays.
    # "voicemail"  → record a message (requires VOICEMAIL_ENABLED=true)
    # "callback"   → tell caller we will call back next business day
    # "schedule"   → offer to schedule via Google Calendar (AI flow continues)
    # "emergency"  → transfer to EMERGENCY_EXTENSION immediately
    after_hours_mode: Literal["voicemail", "callback", "schedule", "emergency"] = Field(
        "callback", env="AFTER_HOURS_MODE"
    )

    # Extension reached for after_hours_mode=emergency or operator fallback
    operator_extension: str = Field("1001", env="OPERATOR_EXTENSION")
    emergency_extension: str = Field("1001", env="EMERGENCY_EXTENSION")

    # ── Retry / fallback behavior ────────────────────────────────
    # Max listen retries before offering operator or hanging up
    max_retries: int = Field(3, env="MAX_RETRIES")
    # Seconds to wait for caller audio before counting a silence event
    silence_timeout_sec: int = Field(8, env="SILENCE_TIMEOUT_SEC")

    # ── DTMF fallback menu ───────────────────────────────────────
    # Set true to announce a keypress menu after the initial greeting.
    # Caller can always speak naturally; DTMF is a secondary escape hatch.
    dtmf_enabled: bool = Field(False, env="DTMF_ENABLED")
    # JSON map of digit → extension, e.g. {"1":"1002","2":"1003","0":"1001"}
    dtmf_map: str = Field('{"1": "1002", "2": "1003", "0": "1001"}', env="DTMF_MAP")

    # ── VIP / known-caller routing ───────────────────────────────
    # Comma-separated caller IDs that bypass the AI and go direct to operator
    vip_callers: str = Field("", env="VIP_CALLERS")

    # ── Agent / LLM behavior ─────────────────────────────────────
    agent_name: str = Field("Alex", env="AGENT_NAME")
    business_name: str = Field("My Business", env="BUSINESS_NAME")
    system_prompt: str = Field(
        "You are {agent_name}, a friendly virtual receptionist for {business_name}. "
        "Your job is to greet callers, find out why they're calling, and either: "
        "1) Schedule a callback appointment at an available time slot, or "
        "2) Transfer them to the right person/department. "
        "Be concise — this is a phone call. Keep responses under 2 sentences. "
        "Always confirm names and phone numbers by spelling them back.",
        env="SYSTEM_PROMPT"
    )

    # ── Extension routing rules ──────────────────────────────────
    routing_rules: str = Field(
        '{"sales": "1002", "billing": "1002", "support": "1003", '
        '"technical": "1003", "operator": "1001", "default": "1001"}',
        env="ROUTING_RULES"
    )

    # ── API server ───────────────────────────────────────────────
    api_host: str = Field("127.0.0.1", env="API_HOST")
    api_port: int = Field(8000, env="API_PORT")

    # ── Database ─────────────────────────────────────────────────
    database_url: str = Field("sqlite+aiosqlite:///./pbx_assistant.db", env="DATABASE_URL")

    # ── Optional feature flags ───────────────────────────────────
    # Voicemail recording (after-hours or no-answer).
    # Requires a writable VOICEMAIL_DIR and optionally Whisper for transcription.
    voicemail_enabled: bool = Field(False, env="VOICEMAIL_ENABLED")
    voicemail_dir: str = Field("/var/spool/helix/voicemail", env="VOICEMAIL_DIR")
    voicemail_transcribe: bool = Field(True, env="VOICEMAIL_TRANSCRIBE")

    # Automatic call summary generated by LLM at call end.
    call_summary_enabled: bool = Field(False, env="CALL_SUMMARY_ENABLED")

    # FAQ / business-info lookup from a local plain-text knowledge file.
    # When enabled, matching chunks are injected into the LLM system prompt.
    faq_enabled: bool = Field(False, env="FAQ_ENABLED")
    faq_file: str = Field("faq.txt", env="FAQ_FILE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
