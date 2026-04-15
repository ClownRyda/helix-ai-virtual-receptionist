"""
Database models and setup — call logs, scheduled appointments, routing rules.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float
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
    disposition = Column(String(32), nullable=True)     # answered | transferred | scheduled | hangup
    transferred_to = Column(String(16), nullable=True)  # extension number
    transcript = Column(Text, nullable=True)
    appointment_id = Column(String(128), nullable=True) # Google Calendar event ID
    notes = Column(Text, nullable=True)


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
    # The relay compares this against the caller's detected language.
    # If they differ, live translation kicks in automatically.
    # 'en' = English, 'es' = Spanish, etc.
    agent_lang = Column(String(8), default="en")


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
