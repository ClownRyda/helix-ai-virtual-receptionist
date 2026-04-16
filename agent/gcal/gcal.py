"""
Google Calendar integration.
- Check free/busy slots
- Book appointments
- Cancel/update events
"""
import asyncio
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from typing import Optional
import structlog
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import json

from config import settings

log = structlog.get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]


def _get_service():
    """Build and return an authenticated Google Calendar service."""
    creds = None

    if os.path.exists(settings.google_token_file):
        creds = Credentials.from_authorized_user_file(settings.google_token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.google_credentials_file, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(settings.google_token_file, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


async def get_available_slots(
    num_slots: int = 5,
    lookahead_days: int | None = None,
) -> list[dict]:
    """
    Find available appointment slots within business hours.

    Returns list of dicts: [{"start": datetime, "end": datetime, "label": "Mon Apr 14 at 10:00 AM"}]
    """
    lookahead = lookahead_days or settings.availability_lookahead_days
    tz = ZoneInfo(settings.business_timezone)
    now = datetime.now(tz)
    end_window = now + timedelta(days=lookahead)
    slot_duration = timedelta(minutes=settings.appointment_slot_minutes)

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _get_service)

    # Fetch busy times from Google Calendar
    body = {
        "timeMin": now.isoformat(),
        "timeMax": end_window.isoformat(),
        "timeZone": settings.business_timezone,
        "items": [{"id": settings.google_calendar_id}],
    }

    try:
        freebusy = await loop.run_in_executor(
            None,
            lambda: service.freebusy().query(body=body).execute()
        )
        busy_periods = freebusy["calendars"][settings.google_calendar_id].get("busy", [])
    except HttpError as e:
        log.error("Google Calendar freebusy error", error=str(e))
        busy_periods = []

    # Parse busy periods
    busy = []
    for period in busy_periods:
        busy.append((
            datetime.fromisoformat(period["start"]).astimezone(tz),
            datetime.fromisoformat(period["end"]).astimezone(tz),
        ))

    # Generate candidate slots in business hours
    slots = []
    current = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    while current < end_window and len(slots) < num_slots:
        # Skip weekends
        if current.weekday() >= 5:
            current += timedelta(days=1)
            current = current.replace(hour=settings.business_hours_start, minute=0, second=0)
            continue

        # Skip outside business hours
        if current.hour < settings.business_hours_start:
            current = current.replace(hour=settings.business_hours_start, minute=0, second=0)
            continue
        if current.hour >= settings.business_hours_end:
            current += timedelta(days=1)
            current = current.replace(hour=settings.business_hours_start, minute=0, second=0)
            continue

        slot_end = current + slot_duration

        # Check if slot conflicts with any busy period
        conflict = any(
            not (slot_end <= b_start or current >= b_end)
            for b_start, b_end in busy
        )

        if not conflict:
            slots.append({
                "start": current,
                "end": slot_end,
                "label": current.strftime("%A, %B %-d at %-I:%M %p"),
            })

        current += slot_duration

    log.info("Found available slots", count=len(slots))
    return slots


async def book_appointment(
    caller_name: str,
    caller_phone: str,
    start: datetime,
    reason: str = "",
    call_id: str = "",
) -> str | None:
    """
    Create a Google Calendar event for the appointment.
    Returns the event ID, or None on failure.
    """
    tz = ZoneInfo(settings.business_timezone)
    end = start + timedelta(minutes=settings.appointment_slot_minutes)

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _get_service)

    event = {
        "summary": f"Call Back: {caller_name}",
        "description": (
            f"Caller: {caller_name}\n"
            f"Phone: {caller_phone}\n"
            f"Reason: {reason or 'Requested callback via AI attendant'}\n"
            f"Call ID: {call_id}"
        ),
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": settings.business_timezone,
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": settings.business_timezone,
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 15},
                {"method": "email", "minutes": 60},
            ],
        },
    }

    try:
        created = await loop.run_in_executor(
            None,
            lambda: service.events().insert(
                calendarId=settings.google_calendar_id,
                body=event
            ).execute()
        )
        log.info("Appointment booked", event_id=created["id"], summary=created["summary"])
        return created["id"]

    except HttpError as e:
        log.error("Failed to book appointment", error=str(e))
        return None


def slots_to_speech(slots: list[dict]) -> str:
    """Convert slot list to a natural-sounding spoken string."""
    if not slots:
        return "I'm sorry, I don't see any available times in the next week. Can I take a message?"

    if len(slots) == 1:
        return f"I have one opening: {slots[0]['label']}. Does that work for you?"

    options = ", ".join(s["label"] for s in slots[:3])
    return f"I have a few openings: {options}. Which time works best for you?"


def parse_slot_choice(utterance: str, slots: list[dict]) -> dict | None:
    """
    Try to match what the caller said to one of the offered slots.
    Simple keyword matching — good enough for <5 slots.
    """
    utterance_lower = utterance.lower()
    for slot in slots:
        label_lower = slot["label"].lower()
        # Match day names or time
        for keyword in ["monday", "tuesday", "wednesday", "thursday", "friday",
                        "saturday", "sunday", "first", "second", "third",
                        "10", "11", "12", "1:", "2:", "3:", "4:"]:
            if keyword in utterance_lower and keyword in label_lower:
                return slot
    # Default: first slot if they say yes/sure/okay/that works
    for word in ["yes", "sure", "okay", "ok", "works", "good", "great", "that one", "first"]:
        if word in utterance_lower:
            return slots[0] if slots else None
    return None
