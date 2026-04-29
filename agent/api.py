"""
FastAPI REST API — exposes call logs, routing rules, appointments, config,
holidays, and voicemail messages for the web dashboard.

v1.2 additions:
  - GET/POST/DELETE /api/holidays
  - PATCH /api/config  (write selected runtime settings back to .env)
  - GET /api/voicemails, GET /api/voicemails/{id}, PATCH /api/voicemails/{id}
"""
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime, date
import os
import re
import json
from uuid import uuid4
import structlog

from database import (
    CallLog,
    Appointment,
    RoutingRule,
    Holiday,
    VoicemailMessage,
    AgentProfile,
    Campaign,
    CRMRecordLink,
    CRMCallSync,
    get_db,
)
from routing.router import get_all_rules, upsert_rule
from routing.agents import (
    list_agents as list_agent_profiles,
    register_or_update_agent,
    set_agent_state,
)
from gcal.gcal import get_available_slots
from config import settings
from ari_agent import get_shared_ari_client, get_active_calls
from integrations.vtiger import VtigerClient, normalize_phone_number

app = FastAPI(title="Helix AI API", version="1.9.0")
log = structlog.get_logger(__name__)

# Production: restrict to localhost. Set API_CORS_ORIGINS env var to
# a comma-separated list of allowed origins if you need LAN access
# e.g. API_CORS_ORIGINS=http://192.168.1.100 (nginx proxy address)
import os as _os
_cors_origins = [o.strip() for o in _os.environ.get(
    "API_CORS_ORIGINS",
    "http://127.0.0.1,http://localhost,http://127.0.0.1:3000,http://localhost:3000"
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class RoutingRuleCreate(BaseModel):
    keyword: str
    extension: str
    description: Optional[str] = ""
    priority: int = 100


class RoutingRuleUpdate(BaseModel):
    extension: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    priority: Optional[int] = None


class HolidayCreate(BaseModel):
    date: str      # ISO format: YYYY-MM-DD
    name: str
    active: bool = True


class ConfigPatch(BaseModel):
    agent_name: Optional[str] = None
    business_name: Optional[str] = None
    whisper_model: Optional[str] = None
    ollama_model: Optional[str] = None
    kokoro_voice_en: Optional[str] = None
    kokoro_voice_es: Optional[str] = None
    kokoro_voice_fr: Optional[str] = None
    kokoro_voice_it: Optional[str] = None
    business_hours_start: Optional[int] = None
    business_hours_end: Optional[int] = None
    business_timezone: Optional[str] = None
    appointment_slot_minutes: Optional[int] = None
    availability_lookahead_days: Optional[int] = None
    google_calendar_id: Optional[str] = None
    after_hours_mode: Optional[Literal["voicemail", "callback", "schedule", "emergency"]] = None
    operator_extension: Optional[str] = None
    emergency_extension: Optional[str] = None
    max_retries: Optional[int] = None
    silence_timeout_sec: Optional[int] = None
    dtmf_enabled: Optional[bool] = None
    dtmf_map: Optional[str] = None
    vip_callers: Optional[str] = None
    voicemail_enabled: Optional[bool] = None
    voicemail_dir: Optional[str] = None
    voicemail_transcribe: Optional[bool] = None
    call_summary_enabled: Optional[bool] = None
    faq_enabled: Optional[bool] = None
    faq_file: Optional[str] = None


class VoicemailStatusPatch(BaseModel):
    status: Literal["unread", "read", "archived"]


class AgentRegister(BaseModel):
    agent_id: str
    display_name: str
    extension: str
    preferred_language: Literal["en", "es", "fr", "it", "he", "ro"]
    availability_state: Literal["offline", "available", "busy", "break"] = "available"
    supported_languages: list[str] = []
    assigned_queues: list[str] = []


class AgentStatePatch(BaseModel):
    display_name: Optional[str] = None
    preferred_language: Optional[Literal["en", "es", "fr", "it", "he", "ro"]] = None
    availability_state: Optional[Literal["offline", "available", "busy", "break"]] = None
    supported_languages: Optional[list[str]] = None
    assigned_queues: Optional[list[str]] = None


class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    caller_id: Optional[str] = ""
    script: Optional[str] = ""
    target_list: str


class CampaignPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    caller_id: Optional[str] = None
    script: Optional[str] = None
    target_list: Optional[str] = None
    status: Optional[Literal["draft", "active", "paused", "completed", "archived"]] = None


class OutboundTestCallBody(BaseModel):
    destination: str
    caller_id: Optional[str] = None
    context: Optional[str] = "helix-outbound"


def _parse_target_list(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"target_list must be valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise HTTPException(status_code=400, detail="target_list must be a JSON array of strings")
    return parsed


def _campaign_payload(campaign: Campaign) -> dict:
    return {
        "id": campaign.id,
        "campaign_id": campaign.campaign_id,
        "name": campaign.name,
        "description": campaign.description or "",
        "status": campaign.status,
        "caller_id": campaign.caller_id or "",
        "script": campaign.script or "",
        "target_list": json.loads(campaign.target_list or "[]"),
        "calls_attempted": campaign.calls_attempted,
        "calls_connected": campaign.calls_connected,
        "calls_failed": campaign.calls_failed,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
    }


# ── Call logs ─────────────────────────────────────────────────────────────────

@app.get("/api/calls")
async def list_calls(
    limit: int = 50,
    offset: int = 0,
    direction: Optional[Literal["inbound", "outbound"]] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CallLog)
    if direction:
        stmt = stmt.where(CallLog.direction == direction)
    stmt = stmt.order_by(desc(CallLog.started_at)).limit(limit).offset(offset)
    result = await db.execute(stmt)
    calls = result.scalars().all()
    return [
        {
            "id": c.id,
            "call_id": c.call_id,
            "direction": c.direction,
            "caller_id": c.caller_id,
            "called_number": c.called_number,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "ended_at": c.ended_at.isoformat() if c.ended_at else None,
            "duration_seconds": c.duration_seconds,
            "intent": c.intent,
            "intent_detail": c.intent_detail,
            "disposition": c.disposition,
            "transferred_to": c.transferred_to,
            "appointment_id": c.appointment_id,
            "notes": c.notes,
        }
        for c in calls
    ]


# ── Live active calls ─────────────────────────────────────────────────────────

@app.get("/api/calls/active")
async def get_active_calls_endpoint():
    """Returns in-progress calls from the ARI agent runtime (not the DB)."""
    return get_active_calls()


@app.get("/api/calls/{call_id}")
async def get_call(call_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CallLog).where(CallLog.call_id == call_id))
    call = result.scalars().first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return {
        "id": call.id,
        "call_id": call.call_id,
        "direction": call.direction,
        "caller_id": call.caller_id,
        "called_number": call.called_number,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "duration_seconds": call.duration_seconds,
        "intent": call.intent,
        "intent_detail": call.intent_detail,
        "disposition": call.disposition,
        "transferred_to": call.transferred_to,
        "transcript": call.transcript,
        "appointment_id": call.appointment_id,
        "notes": call.notes,
        "summary": call.summary,
    }


@app.get("/api/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Return aggregate call stats using SQL COUNT/SUM — O(1) regardless of table size."""
    from sqlalchemy import func, case
    stmt = select(
        func.count().label("total"),
        func.sum(case((CallLog.disposition == "transferred", 1), else_=0)).label("transferred"),
        func.sum(case((CallLog.disposition == "scheduled",   1), else_=0)).label("scheduled"),
        func.sum(case((CallLog.disposition == "after_hours", 1), else_=0)).label("after_hours"),
        func.sum(case((CallLog.disposition == "voicemail",   1), else_=0)).label("voicemail"),
        func.avg(CallLog.duration_seconds).label("avg_duration"),
    ).select_from(CallLog)
    row = (await db.execute(stmt)).one()
    total        = row.total        or 0
    transferred  = row.transferred  or 0
    scheduled    = row.scheduled    or 0
    after_hours  = row.after_hours  or 0
    voicemail    = row.voicemail    or 0
    avg_duration = float(row.avg_duration or 0)
    return {
        "total_calls": total,
        "transferred": transferred,
        "scheduled": scheduled,
        "after_hours": after_hours,
        "voicemail": voicemail,
        "hangup": total - transferred - scheduled - after_hours - voicemail,
        "avg_duration_seconds": round(avg_duration, 1),
    }



# ── Daily call volume (last 7 days) ──────────────────────────────────────────

@app.get("/api/stats/daily")
async def get_daily_stats(db: AsyncSession = Depends(get_db)):
    """
    Returns call counts per day for the last 7 days (UTC dates).
    Uses a single SQL GROUP BY query — no Python-side row scan.
    SQLite stores datetimes as ISO strings; strftime('%Y-%m-%d', ...) works on both
    ISO string columns and native datetime columns.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func, text
    today = datetime.now(timezone.utc).date()
    cutoff = (today - timedelta(days=6)).isoformat()
    # Build the 7-day scaffold so days with 0 calls still appear
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    stmt = (
        select(
            func.strftime("%Y-%m-%d", CallLog.started_at).label("day"),
            func.count().label("calls"),
        )
        .where(CallLog.started_at >= cutoff)
        .group_by(func.strftime("%Y-%m-%d", CallLog.started_at))
    )
    rows = (await db.execute(stmt)).all()
    counts = {d: 0 for d in days}
    for row in rows:
        if row.day in counts:
            counts[row.day] = row.calls
    return [{"date": k, "calls": v} for k, v in counts.items()]


# ── Routing rules ─────────────────────────────────────────────────────────────

@app.get("/api/rules")
async def list_rules(db: AsyncSession = Depends(get_db)):
    return await get_all_rules(db)


@app.post("/api/rules")
async def create_rule(body: RoutingRuleCreate, db: AsyncSession = Depends(get_db)):
    return await upsert_rule(
        body.keyword, body.extension, body.description or "", body.priority, db=db
    )


@app.put("/api/rules/{rule_id}")
async def update_rule(rule_id: int, body: RoutingRuleUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RoutingRule).where(RoutingRule.id == rule_id))
    rule = result.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if body.extension is not None:
        rule.extension = body.extension
    if body.description is not None:
        rule.description = body.description
    if body.active is not None:
        rule.active = body.active
    if body.priority is not None:
        rule.priority = body.priority
    await db.commit()
    return {"id": rule.id, "keyword": rule.keyword, "extension": rule.extension, "active": rule.active}


@app.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RoutingRule).where(RoutingRule.id == rule_id))
    rule = result.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()
    return {"deleted": rule_id}


# ── Agents ───────────────────────────────────────────────────────────────────

@app.get("/api/agents")
async def list_agents(db: AsyncSession = Depends(get_db)):
    agents = await list_agent_profiles(db)
    return [
        {
            "id": agent.id,
            "agent_id": agent.agent_id,
            "display_name": agent.display_name,
            "extension": agent.extension,
            "availability_state": agent.availability_state,
            "preferred_language": agent.preferred_language,
            "supported_languages": [item for item in (agent.supported_languages or "").split(",") if item],
            "assigned_queues": [item for item in (agent.assigned_queues or "").split(",") if item],
            "current_call_id": agent.current_call_id,
            "last_offered_at": agent.last_offered_at.isoformat() if agent.last_offered_at else None,
            "state_changed_at": agent.state_changed_at.isoformat() if agent.state_changed_at else None,
            "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
        }
        for agent in agents
    ]


@app.post("/api/agents/register")
async def register_agent(body: AgentRegister, db: AsyncSession = Depends(get_db)):
    agent = await register_or_update_agent(
        db,
        agent_id=body.agent_id,
        display_name=body.display_name,
        extension=body.extension,
        preferred_language=body.preferred_language,
        availability_state=body.availability_state,
        supported_languages=body.supported_languages,
        assigned_queues=body.assigned_queues,
    )
    return {
        "id": agent.id,
        "agent_id": agent.agent_id,
        "display_name": agent.display_name,
        "extension": agent.extension,
        "availability_state": agent.availability_state,
        "preferred_language": agent.preferred_language,
        "supported_languages": [item for item in (agent.supported_languages or "").split(",") if item],
        "assigned_queues": [item for item in (agent.assigned_queues or "").split(",") if item],
        "state_changed_at": agent.state_changed_at.isoformat() if agent.state_changed_at else None,
    }


@app.patch("/api/agents/{agent_id}")
async def patch_agent(agent_id: str, body: AgentStatePatch, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentProfile).where(AgentProfile.agent_id == agent_id))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if body.display_name is not None:
        agent.display_name = body.display_name
    if body.preferred_language is not None:
        agent.preferred_language = body.preferred_language
        current_supported = [item for item in (agent.supported_languages or "").split(",") if item]
        if body.preferred_language not in current_supported:
            current_supported.insert(0, body.preferred_language)
            agent.supported_languages = ",".join(dict.fromkeys(current_supported))
    if body.supported_languages is not None:
        agent.supported_languages = ",".join(dict.fromkeys(body.supported_languages))
    if body.assigned_queues is not None:
        agent.assigned_queues = ",".join(dict.fromkeys(q.strip().lower() for q in body.assigned_queues if q.strip()))
    if body.availability_state is not None:
        agent = await set_agent_state(
            db,
            agent_id=agent_id,
            availability_state=body.availability_state,
            preferred_language=body.preferred_language,
        )
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if body.display_name is not None or body.supported_languages is not None or body.assigned_queues is not None:
            await db.commit()
            await db.refresh(agent)
    else:
        agent.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(agent)

    return {
        "id": agent.id,
        "agent_id": agent.agent_id,
        "display_name": agent.display_name,
        "extension": agent.extension,
        "availability_state": agent.availability_state,
        "preferred_language": agent.preferred_language,
        "supported_languages": [item for item in (agent.supported_languages or "").split(",") if item],
        "assigned_queues": [item for item in (agent.assigned_queues or "").split(",") if item],
        "current_call_id": agent.current_call_id,
        "state_changed_at": agent.state_changed_at.isoformat() if agent.state_changed_at else None,
    }


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentProfile).where(AgentProfile.agent_id == agent_id))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.current_call_id:
        raise HTTPException(status_code=409, detail="Agent is on an active call")
    await db.delete(agent)
    await db.commit()
    return {"deleted": agent_id}


# ── Campaigns / outbound scaffolding ────────────────────────────────────────

@app.get("/api/campaigns")
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).order_by(desc(Campaign.created_at)))
    return [_campaign_payload(campaign) for campaign in result.scalars().all()]


@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.campaign_id == campaign_id))
    campaign = result.scalars().first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_payload(campaign)


@app.post("/api/campaigns")
async def create_campaign(body: CampaignCreate, db: AsyncSession = Depends(get_db)):
    target_list = _parse_target_list(body.target_list)
    now = datetime.utcnow()
    campaign = Campaign(
        campaign_id=f"camp-{uuid4().hex[:12]}",
        name=body.name.strip(),
        description=(body.description or "").strip(),
        caller_id=(body.caller_id or "").strip(),
        script=body.script or "",
        target_list=json.dumps(target_list),
        status="draft",
        created_at=now,
        updated_at=now,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return _campaign_payload(campaign)


@app.patch("/api/campaigns/{campaign_id}")
async def patch_campaign(campaign_id: str, body: CampaignPatch, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.campaign_id == campaign_id))
    campaign = result.scalars().first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if body.name is not None:
        campaign.name = body.name.strip()
    if body.description is not None:
        campaign.description = body.description.strip()
    if body.caller_id is not None:
        campaign.caller_id = body.caller_id.strip()
    if body.script is not None:
        campaign.script = body.script
    if body.target_list is not None:
        campaign.target_list = json.dumps(_parse_target_list(body.target_list))
    if body.status is not None:
        campaign.status = body.status
    campaign.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(campaign)
    return _campaign_payload(campaign)


@app.delete("/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.campaign_id == campaign_id))
    campaign = result.scalars().first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == "active":
        raise HTTPException(status_code=409, detail="Active campaigns cannot be deleted")
    await db.delete(campaign)
    await db.commit()
    return {"deleted": campaign_id}


@app.post("/api/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.campaign_id == campaign_id))
    campaign = result.scalars().first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    now = datetime.utcnow()
    campaign.status = "active"
    campaign.started_at = campaign.started_at or now
    campaign.updated_at = now
    await db.commit()
    await db.refresh(campaign)
    return _campaign_payload(campaign)


@app.post("/api/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.campaign_id == campaign_id))
    campaign = result.scalars().first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign.status = "paused"
    campaign.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(campaign)
    return _campaign_payload(campaign)


@app.post("/api/campaigns/{campaign_id}/complete")
async def complete_campaign(campaign_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.campaign_id == campaign_id))
    campaign = result.scalars().first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    now = datetime.utcnow()
    campaign.status = "completed"
    campaign.completed_at = now
    campaign.updated_at = now
    await db.commit()
    await db.refresh(campaign)
    return _campaign_payload(campaign)


@app.post("/api/outbound/test-call")
async def outbound_test_call(body: OutboundTestCallBody, db: AsyncSession = Depends(get_db)):
    destination = body.destination.strip()
    context = (body.context or "helix-outbound").strip() or "helix-outbound"
    caller_id = (body.caller_id or settings.operator_extension or "9999").strip()

    ari = get_shared_ari_client()
    if not ari:
        raise HTTPException(status_code=503, detail="ARI agent is not connected")
    try:
        channel = await ari.originate_to_dialplan(
            endpoint=f"Local/{destination}@{context}",
            context=context,
            extension=destination,
            priority=1,
            caller_id=caller_id,
        )
    except Exception as exc:
        log.error("Outbound test call originate failed", destination=destination, context=context, error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    call_log = CallLog(
        call_id=f"outbound-{channel.get('id', uuid4().hex[:12])}",
        direction="outbound",
        caller_id=caller_id,
        called_number=destination,
        started_at=datetime.utcnow(),
        disposition="originated",
        notes=json.dumps({"context": context, "channel_id": channel.get("id", "")}),
    )
    db.add(call_log)
    await db.commit()
    await db.refresh(call_log)

    return {
        "channel_id": channel.get("id"),
        "call_log_id": call_log.id,
        "call_id": call_log.call_id,
        "destination": destination,
        "context": context,
    }


# ── Appointments ─────────────────────────────────────────────────────────────

@app.get("/api/appointments")
async def list_appointments(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Appointment).order_by(desc(Appointment.scheduled_at)))
    appts = result.scalars().all()
    return [
        {
            "id": a.id,
            "google_event_id": a.google_event_id,
            "caller_name": a.caller_name,
            "caller_phone": a.caller_phone,
            "scheduled_at": a.scheduled_at.isoformat() if a.scheduled_at else None,
            "duration_minutes": a.duration_minutes,
            "reason": a.reason,
            "confirmed": a.confirmed,
        }
        for a in appts
    ]


@app.get("/api/calendar/slots")
async def get_calendar_slots(days: int = 7, num_slots: int = 10):
    slots = await get_available_slots(num_slots=num_slots, lookahead_days=days)
    return [
        {
            "start": s["start"].isoformat(),
            "end": s["end"].isoformat(),
            "label": s["label"],
        }
        for s in slots
    ]


# ── Holidays ──────────────────────────────────────────────────────────────────

@app.get("/api/holidays")
async def list_holidays(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Holiday).order_by(Holiday.date))
    holidays = result.scalars().all()
    return [
        {
            "id": h.id,
            "date": h.date.isoformat(),
            "name": h.name,
            "active": h.active,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in holidays
    ]


@app.post("/api/holidays")
async def create_holiday(body: HolidayCreate, db: AsyncSession = Depends(get_db)):
    try:
        holiday_date = date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # Check for existing
    result = await db.execute(select(Holiday).where(Holiday.date == holiday_date))
    existing = result.scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Holiday on {body.date} already exists.")

    holiday = Holiday(date=holiday_date, name=body.name, active=body.active)
    db.add(holiday)
    await db.commit()
    await db.refresh(holiday)
    return {"id": holiday.id, "date": holiday.date.isoformat(), "name": holiday.name, "active": holiday.active}


@app.delete("/api/holidays/{holiday_id}")
async def delete_holiday(holiday_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Holiday).where(Holiday.id == holiday_id))
    holiday = result.scalars().first()
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
    await db.delete(holiday)
    await db.commit()
    return {"deleted": holiday_id}


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return {
        "agent_name": settings.agent_name,
        "business_name": settings.business_name,
        "whisper_model": settings.whisper_model,
        "ollama_model": settings.ollama_model,
        # TTS engine is Kokoro (replaced Piper in v1.6). Expose per-language voices.
        "kokoro_voice_en": settings.kokoro_voice_en,
        "kokoro_voice_es": settings.kokoro_voice_es,
        "kokoro_voice_fr": settings.kokoro_voice_fr,
        "kokoro_voice_it": settings.kokoro_voice_it,
        "business_hours_start": settings.business_hours_start,
        "business_hours_end": settings.business_hours_end,
        "business_timezone": settings.business_timezone,
        "appointment_slot_minutes": settings.appointment_slot_minutes,
        "availability_lookahead_days": settings.availability_lookahead_days,
        "google_calendar_id": settings.google_calendar_id,
        # v1.2 fields
        "after_hours_mode": settings.after_hours_mode,
        "operator_extension": settings.operator_extension,
        "emergency_extension": settings.emergency_extension,
        "max_retries": settings.max_retries,
        "silence_timeout_sec": settings.silence_timeout_sec,
        "dtmf_enabled": settings.dtmf_enabled,
        "dtmf_map": settings.dtmf_map,
        "vip_callers": settings.vip_callers,
        "voicemail_enabled": settings.voicemail_enabled,
        "voicemail_dir": settings.voicemail_dir,
        "voicemail_transcribe": settings.voicemail_transcribe,
        "call_summary_enabled": settings.call_summary_enabled,
        "faq_enabled": settings.faq_enabled,
        "faq_file": settings.faq_file,
    }


@app.patch("/api/config")
async def patch_config(body: ConfigPatch):
    """
    Write selected runtime settings back to the .env file.
    Changes take effect on the next agent restart.
    """
    env_file = ".env"
    if not os.path.exists(env_file):
        raise HTTPException(status_code=404, detail=".env file not found")

    with open(env_file, "r") as f:
        content = f.read()

    updates = body.dict(exclude_none=True)
    env_key_map = {
        "agent_name": "AGENT_NAME",
        "business_name": "BUSINESS_NAME",
        "whisper_model": "WHISPER_MODEL",
        "ollama_model": "OLLAMA_MODEL",
        "kokoro_voice_en": "KOKORO_VOICE_EN",
        "kokoro_voice_es": "KOKORO_VOICE_ES",
        "kokoro_voice_fr": "KOKORO_VOICE_FR",
        "kokoro_voice_it": "KOKORO_VOICE_IT",
        "business_hours_start": "BUSINESS_HOURS_START",
        "business_hours_end": "BUSINESS_HOURS_END",
        "business_timezone": "BUSINESS_TIMEZONE",
        "appointment_slot_minutes": "APPOINTMENT_SLOT_MINUTES",
        "availability_lookahead_days": "AVAILABILITY_LOOKAHEAD_DAYS",
        "google_calendar_id": "GOOGLE_CALENDAR_ID",
        "after_hours_mode": "AFTER_HOURS_MODE",
        "operator_extension": "OPERATOR_EXTENSION",
        "emergency_extension": "EMERGENCY_EXTENSION",
        "max_retries": "MAX_RETRIES",
        "silence_timeout_sec": "SILENCE_TIMEOUT_SEC",
        "dtmf_enabled": "DTMF_ENABLED",
        "dtmf_map": "DTMF_MAP",
        "vip_callers": "VIP_CALLERS",
        "voicemail_enabled": "VOICEMAIL_ENABLED",
        "voicemail_dir": "VOICEMAIL_DIR",
        "voicemail_transcribe": "VOICEMAIL_TRANSCRIBE",
        "call_summary_enabled": "CALL_SUMMARY_ENABLED",
        "faq_enabled": "FAQ_ENABLED",
        "faq_file": "FAQ_FILE",
    }

    for field, value in updates.items():
        env_key = env_key_map.get(field)
        if not env_key:
            continue
        str_value = str(value) if not isinstance(value, bool) else str(value).upper()
        # Replace existing key or append
        pattern = rf"^{env_key}=.*$"
        new_line = f"{env_key}={str_value}"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
        else:
            content += f"\n{new_line}"

    with open(env_file, "w") as f:
        f.write(content)

    return {"updated": list(updates.keys()), "note": "Restart the agent for changes to take effect."}


# ── Voicemails ────────────────────────────────────────────────────────────────

@app.get("/api/voicemails")
async def list_voicemails(db: AsyncSession = Depends(get_db)):
    if not settings.voicemail_enabled:
        return []
    result = await db.execute(
        select(VoicemailMessage).order_by(desc(VoicemailMessage.recorded_at))
    )
    vms = result.scalars().all()
    return [
        {
            "id": v.id,
            "call_id": v.call_id,
            "caller_id": v.caller_id,
            "recorded_at": v.recorded_at.isoformat() if v.recorded_at else None,
            "duration_sec": v.duration_sec,
            "transcript": v.transcript,
            "status": v.status,
            "audio_path": v.audio_path,
        }
        for v in vms
    ]


@app.get("/api/voicemails/{vm_id}")
async def get_voicemail(vm_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VoicemailMessage).where(VoicemailMessage.id == vm_id))
    vm = result.scalars().first()
    if not vm:
        raise HTTPException(status_code=404, detail="Voicemail not found")
    return {
        "id": vm.id,
        "call_id": vm.call_id,
        "caller_id": vm.caller_id,
        "recorded_at": vm.recorded_at.isoformat() if vm.recorded_at else None,
        "duration_sec": vm.duration_sec,
        "transcript": vm.transcript,
        "status": vm.status,
        "audio_path": vm.audio_path,
    }


@app.patch("/api/voicemails/{vm_id}")
async def update_voicemail_status(vm_id: int, body: VoicemailStatusPatch, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VoicemailMessage).where(VoicemailMessage.id == vm_id))
    vm = result.scalars().first()
    if not vm:
        raise HTTPException(status_code=404, detail="Voicemail not found")
    vm.status = body.status
    await db.commit()
    return {"id": vm.id, "status": vm.status}


# ── Integrations: Vtiger ────────────────────────────────────────────────────

@app.get("/api/integrations/vtiger/health")
async def vtiger_health():
    if not settings.vtiger_enabled:
        return {"enabled": False, "ok": False, "reason": "VTIGER_ENABLED=false"}
    client = VtigerClient.from_settings()
    try:
        payload = await client.health()
        payload["enabled"] = True
        return payload
    except Exception as exc:
        log.error("Vtiger health failed", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/integrations/vtiger/lookup")
async def vtiger_lookup(phone: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    normalized = normalize_phone_number(phone)
    if not normalized:
        raise HTTPException(status_code=400, detail="Phone number did not contain any digits")

    cached_result = await db.execute(
        select(CRMRecordLink)
        .where(
            CRMRecordLink.crm_provider == "vtiger",
            CRMRecordLink.normalized_phone == normalized,
        )
        .order_by(desc(CRMRecordLink.last_seen_at))
    )
    cached = cached_result.scalars().first()

    client = VtigerClient.from_settings()
    live_record = None
    if settings.vtiger_enabled:
        try:
            live_record = await client.lookup_by_phone(phone)
        except Exception as exc:
            log.warning("Vtiger lookup failed", phone=normalized, error=str(exc))

    record_payload = None
    if live_record:
        now = datetime.utcnow()
        if cached:
            cached.phone_number = phone
            cached.crm_module = live_record.module
            cached.crm_record_id = live_record.record_id
            cached.crm_record_label = live_record.label
            cached.updated_at = now
            cached.last_seen_at = now
        else:
            db.add(
                CRMRecordLink(
                    phone_number=phone,
                    normalized_phone=normalized,
                    crm_provider="vtiger",
                    crm_module=live_record.module,
                    crm_record_id=live_record.record_id,
                    crm_record_label=live_record.label,
                    created_at=now,
                    updated_at=now,
                    last_seen_at=now,
                )
            )
        await db.commit()
    elif cached:
        pass

    if live_record:
        record_payload = {
            "module": live_record.module,
            "record_id": live_record.record_id,
            "label": live_record.label,
            "phone": live_record.phone,
        }
    elif cached:
        record_payload = {
            "module": cached.crm_module,
            "record_id": cached.crm_record_id,
            "label": cached.crm_record_label,
            "phone": cached.phone_number,
        }

    return {
        "enabled": settings.vtiger_enabled,
        "normalized_phone": normalized,
        "record": record_payload,
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    import os, httpx

    # ── ARI connectivity check ────────────────────────────────────────────────
    ari_ok = False
    ari_detail = "not checked"
    try:
        ari_url = (
            f"http://{settings.asterisk_host}:{settings.asterisk_ari_port}"
            f"/ari/asterisk/info"
        )
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(
                ari_url,
                auth=(settings.asterisk_ari_user, settings.asterisk_ari_password),
            )
        ari_ok = r.status_code == 200
        ari_detail = "connected" if ari_ok else f"HTTP {r.status_code}"
    except Exception as e:
        ari_detail = str(e)[:80]

    # ── MOH asset sanity check ────────────────────────────────────────────────
    # At least one .wav/.alaw/.ulaw should exist in the MOH default dir.
    moh_dir = "/var/lib/asterisk/moh"
    moh_ok = False
    moh_detail = "not found"
    try:
        files = os.listdir(moh_dir)
        audio_files = [f for f in files if f.endswith((".wav", ".alaw", ".ulaw", ".mp3", ".gsm"))]
        moh_ok = len(audio_files) > 0
        moh_detail = f"{len(audio_files)} file(s)" if moh_ok else "no audio files"
    except FileNotFoundError:
        moh_detail = f"{moh_dir} not found"
    except Exception as e:
        moh_detail = str(e)[:80]

    # ── Voicemail spool sanity check ──────────────────────────────────────────
    vm_spool = "/var/spool/asterisk/voicemail"
    vm_ok = os.path.isdir(vm_spool)
    vm_detail = "present" if vm_ok else f"{vm_spool} not found"

    # ── Overall status ────────────────────────────────────────────────────────
    checks_ok = ari_ok and moh_ok and vm_ok
    overall = "ok" if checks_ok else ("degraded" if ari_ok else "error")

    return {
        "status": overall,
        "service": "helix-ai",
        "version": "1.9.5",
        "tts_engine": "Kokoro",
        "tts_voices": {
            "en": settings.kokoro_voice_en,
            "es": settings.kokoro_voice_es,
            "fr": settings.kokoro_voice_fr,
            "it": settings.kokoro_voice_it,
        },
        "features": {
            "voicemail": settings.voicemail_enabled,
            "call_summary": settings.call_summary_enabled,
            "faq": settings.faq_enabled,
            "dtmf": settings.dtmf_enabled,
        },
        "checks": {
            "ari":       {"ok": ari_ok,  "detail": ari_detail},
            "moh":       {"ok": moh_ok,  "detail": moh_detail},
            "voicemail": {"ok": vm_ok,   "detail": vm_detail},
        },
    }
