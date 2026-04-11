"""
Central configuration — all values sourced from environment / .env file.
"""
from pydantic_settings import BaseSettings
from pydantic import Field


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
    # Speech probability above this → SPEECH.  0.5 works well for most cases.
    # Raise to 0.6-0.7 in noisy environments to reduce false positives.
    vad_min_silence_ms: int = Field(600, env="VAD_MIN_SILENCE_MS")
    # Milliseconds of silence after speech before we consider the utterance done.
    # 600 ms is a good balance — short enough for responsive turn-taking,
    # long enough to survive brief pauses mid-sentence.
    vad_speech_pad_ms: int = Field(100, env="VAD_SPEECH_PAD_MS")
    # Padding added to start/end of detected speech segments (captures soft onsets).

    # ── Whisper STT ─────────────────────────────────────────────
    whisper_model: str = Field("base.en", env="WHISPER_MODEL")
    # Options: tiny.en, base.en, small.en, medium.en, large-v3
    whisper_device: str = Field("cuda", env="WHISPER_DEVICE")
    # cuda | cpu | auto
    whisper_compute_type: str = Field("float16", env="WHISPER_COMPUTE_TYPE")
    # float16 (GPU), int8 (CPU)

    # ── Ollama LLM ──────────────────────────────────────────────
    ollama_host: str = Field("http://localhost:11434", env="OLLAMA_HOST")
    ollama_model: str = Field("qwen3:8b", env="OLLAMA_MODEL")
    ollama_timeout: int = Field(30, env="OLLAMA_TIMEOUT")

    # ── Piper TTS ───────────────────────────────────────────────
    piper_model: str = Field("en_US-lessac-medium", env="PIPER_MODEL")
    piper_model_path: str = Field("/opt/piper/models", env="PIPER_MODEL_PATH")

    # ── Google Calendar ─────────────────────────────────────────
    google_credentials_file: str = Field("credentials.json", env="GOOGLE_CREDENTIALS_FILE")
    google_token_file: str = Field("token.json", env="GOOGLE_TOKEN_FILE")
    google_calendar_id: str = Field("primary", env="GOOGLE_CALENDAR_ID")
    # Slot duration in minutes for scheduling
    appointment_slot_minutes: int = Field(30, env="APPOINTMENT_SLOT_MINUTES")
    # How many days ahead to look for availability
    availability_lookahead_days: int = Field(7, env="AVAILABILITY_LOOKAHEAD_DAYS")

    # ── Business hours ──────────────────────────────────────────
    business_hours_start: int = Field(9, env="BUSINESS_HOURS_START")   # 9 AM
    business_hours_end: int = Field(17, env="BUSINESS_HOURS_END")       # 5 PM
    business_timezone: str = Field("America/Chicago", env="BUSINESS_TIMEZONE")

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
    # JSON string mapping intent keywords → extension numbers
    routing_rules: str = Field(
        '{"sales": "1002", "billing": "1002", "support": "1003", '
        '"technical": "1003", "operator": "1001", "default": "1001"}',
        env="ROUTING_RULES"
    )

    # ── API server ───────────────────────────────────────────────
    api_host: str = Field("0.0.0.0", env="API_HOST")
    api_port: int = Field(8000, env="API_PORT")

    # ── Database ─────────────────────────────────────────────────
    database_url: str = Field("sqlite+aiosqlite:///./pbx_assistant.db", env="DATABASE_URL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
