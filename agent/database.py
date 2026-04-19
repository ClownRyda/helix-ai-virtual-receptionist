"""
Database models and setup — call logs, appointments, routing rules,
holidays, voicemail messages, and human-agent presence state.
"""
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, DateTime, Date, Text, Boolean, Float
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from config import settings

Base = declarative_base()
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class CallLog(Base):
    __tablename__ = "call_logs"

    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(String(64), unique=True, index=True)
    caller_id = Column(String(32))
    called_number = Column(String(32))
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    intent = Column(String(64), nullable=True)          # schedule | transfer | info | unknown
    intent_detail = Column(String(128), nullable=True)  # e.g. "sales", "support"
    disposition = Column(String(32), nullable=True)     # answered | transferred | scheduled | hangup | after_hours
    transferred_to = Column(String(16), nullable=True)  # extension number
    transcript = Column(Text, nullable=True)
    appointment_id = Column(String(128), nullable=True) # Google Calendar event ID
    # notes stores structured call-path JSON (list of state transitions)
    notes = Column(Text, nullable=True)
    # Optional LLM-generated summary of the call
    summary = Column(Text, nullable=True)


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    google_event_id = Column(String(128), unique=True, nullable=True)
    call_id = Column(String(64), nullable=True)
    caller_name = Column(String(128))
    caller_phone = Column(String(32))
    scheduled_at = Column(DateTime)
    duration_minutes = Column(Integer, default=30)
    reason = Column(Text, nullable=True)
    confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(64), unique=True, index=True)
    extension = Column(String(16))
    description = Column(String(256), nullable=True)
    active = Column(Boolean, default=True)
    priority = Column(Integer, default=100)
    # Language spoken by the person at this extension.
    agent_lang = Column(String(8), default="en")


class Holiday(Base):
    """
    Business holidays — on these dates the system behaves as if
    closed regardless of business_hours_start/end.
    """
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)       # e.g. "Christmas Day"
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class VoicemailMessage(Base):
    """
    Voicemail recordings left by callers during after-hours or no-answer.
    """
    __tablename__ = "voicemail_messages"

    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(String(64), nullable=True, index=True)
    caller_id = Column(String(32), nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)
    duration_sec = Column(Float, nullable=True)
    # Filesystem path to the recorded .wav file
    audio_path = Column(String(512), nullable=True)
    # Whisper transcript of the voicemail (if voicemail_transcribe=true)
    transcript = Column(Text, nullable=True)
    # unread | read | archived
    status = Column(String(16), default="unread")


class AgentProfile(Base):
    """
    Human agent registration / presence state for live handoff.
    """
    __tablename__ = "agent_profiles"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(64), unique=True, index=True)
    display_name = Column(String(128), nullable=False)
    extension = Column(String(32), unique=True, index=True)
    availability_state = Column(String(16), default="offline", index=True)
    preferred_language = Column(String(8), default="en")
    # Comma-separated ISO language codes, e.g. "en,es"
    supported_languages = Column(Text, default="en")
    # Comma-separated queue / skill names, e.g. "sales,support"
    assigned_queues = Column(Text, default="")
    current_call_id = Column(String(64), nullable=True)
    last_offered_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed default routing rules if empty
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(select(RoutingRule))
        if not result.scalars().first():
            defaults = [
                RoutingRule(keyword="sales",     extension="1002", description="Sales department",     priority=10, agent_lang="en"),
                RoutingRule(keyword="billing",   extension="1002", description="Billing goes to sales", priority=20, agent_lang="en"),
                RoutingRule(keyword="support",   extension="1003", description="Technical support",     priority=10, agent_lang="en"),
                RoutingRule(keyword="technical", extension="1003", description="Technical issues",      priority=20, agent_lang="en"),
                RoutingRule(keyword="operator",  extension="1001", description="Operator / reception",  priority=10, agent_lang="en"),
            ]
            session.add_all(defaults)
            await session.commit()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
