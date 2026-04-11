"""
FastAPI REST API — exposes call logs, routing rules, appointments, and config
for the web dashboard.
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from database import CallLog, Appointment, RoutingRule, get_db
from routing.router import get_all_rules, upsert_rule
from calendar.gcal import get_available_slots
from config import settings

app = FastAPI(title="PBX Assistant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────────────

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


# ── Call logs ─────────────────────────────────────────────────────────────────

@app.get("/api/calls")
async def list_calls(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CallLog).order_by(desc(CallLog.started_at)).limit(limit).offset(offset)
    )
    calls = result.scalars().all()
    return [
        {
            "id": c.id,
            "call_id": c.call_id,
            "caller_id": c.caller_id,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "ended_at": c.ended_at.isoformat() if c.ended_at else None,
            "duration_seconds": c.duration_seconds,
            "intent": c.intent,
            "intent_detail": c.intent_detail,
            "disposition": c.disposition,
            "transferred_to": c.transferred_to,
            "appointment_id": c.appointment_id,
        }
        for c in calls
    ]


@app.get("/api/calls/{call_id}")
async def get_call(call_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CallLog).where(CallLog.call_id == call_id))
    call = result.scalars().first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return {
        "id": call.id,
        "call_id": call.call_id,
        "caller_id": call.caller_id,
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
    }


@app.get("/api/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CallLog))
    calls = result.scalars().all()
    total = len(calls)
    transferred = sum(1 for c in calls if c.disposition == "transferred")
    scheduled = sum(1 for c in calls if c.disposition == "scheduled")
    avg_duration = (
        sum(c.duration_seconds for c in calls if c.duration_seconds) / total
        if total > 0 else 0
    )
    return {
        "total_calls": total,
        "transferred": transferred,
        "scheduled": scheduled,
        "hangup": total - transferred - scheduled,
        "avg_duration_seconds": round(avg_duration, 1),
    }


# ── Routing rules ─────────────────────────────────────────────────────────────

@app.get("/api/rules")
async def list_rules(db: AsyncSession = Depends(get_db)):
    return await get_all_rules(db)


@app.post("/api/rules")
async def create_rule(body: RoutingRuleCreate, db: AsyncSession = Depends(get_db)):
    return await upsert_rule(
        body.keyword, body.extension, body.description or "", body.priority, db
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


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return {
        "agent_name": settings.agent_name,
        "business_name": settings.business_name,
        "whisper_model": settings.whisper_model,
        "ollama_model": settings.ollama_model,
        "piper_model": settings.piper_model,
        "business_hours_start": settings.business_hours_start,
        "business_hours_end": settings.business_hours_end,
        "business_timezone": settings.business_timezone,
        "appointment_slot_minutes": settings.appointment_slot_minutes,
        "availability_lookahead_days": settings.availability_lookahead_days,
        "google_calendar_id": settings.google_calendar_id,
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "pbx-assistant"}
