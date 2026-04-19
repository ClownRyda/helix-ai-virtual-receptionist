"""
Minimal human-agent presence and selection layer.

This is intentionally small:
  - persistent agent registration / state
  - queue-aware available-agent lookup
  - simple busy/available lifecycle for live handoff
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import AgentProfile, RoutingRule

log = structlog.get_logger(__name__)

AGENT_AVAILABILITY_STATES = {"offline", "available", "busy", "break"}
AGENT_LANGUAGE_DIGITS = {
    "1": "en",
    "2": "es",
    "3": "fr",
    "4": "it",
    "5": "he",
    "6": "ro",
}

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "he": "Hebrew",
    "ro": "Romanian",
}


@dataclass
class AgentRoute:
    extension: str
    display_name: str
    preferred_language: str
    supported_languages: list[str]
    assigned_queues: list[str]
    translation_required: bool
    source: str = "agent"
    agent_id: str = ""


def _csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _serialize_csv(values: list[str] | None) -> str:
    if not values:
        return ""
    ordered = []
    for value in values:
        cleaned = str(value).strip().lower()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return ",".join(ordered)


def _queue_matches(agent: AgentProfile, requested_queue: str | None) -> bool:
    if not requested_queue:
        return True
    queues = _csv_list(agent.assigned_queues)
    if not queues:
        return True
    return requested_queue.lower() in queues or "general" in queues or "all" in queues


def _language_rank(agent: AgentProfile, caller_lang: str) -> int:
    if (agent.preferred_language or "en") == caller_lang:
        return 0
    if caller_lang in _csv_list(agent.supported_languages):
        return 1
    return 2


def _queue_rank(agent: AgentProfile, requested_queue: str | None) -> int:
    if not requested_queue:
        return 0
    queues = _csv_list(agent.assigned_queues)
    if requested_queue.lower() in queues:
        return 0
    if not queues or "general" in queues or "all" in queues:
        return 1
    return 2


async def list_agents(db: AsyncSession) -> list[AgentProfile]:
    result = await db.execute(select(AgentProfile).order_by(AgentProfile.display_name, AgentProfile.extension))
    return list(result.scalars().all())


async def get_agent_by_extension(db: AsyncSession, extension: str) -> AgentProfile | None:
    result = await db.execute(select(AgentProfile).where(AgentProfile.extension == extension))
    return result.scalars().first()


async def get_agent_by_agent_id(db: AsyncSession, agent_id: str) -> AgentProfile | None:
    result = await db.execute(select(AgentProfile).where(AgentProfile.agent_id == agent_id))
    return result.scalars().first()


async def infer_default_queues(db: AsyncSession, extension: str) -> list[str]:
    result = await db.execute(
        select(RoutingRule.keyword).where(
            RoutingRule.extension == extension,
            RoutingRule.active == True,
        )
    )
    queues = [str(row[0]).strip().lower() for row in result.all() if row and row[0]]
    ordered = []
    for queue in queues:
        if queue not in ordered:
            ordered.append(queue)
    return ordered


async def register_or_update_agent(
    db: AsyncSession,
    *,
    agent_id: str,
    display_name: str,
    extension: str,
    preferred_language: str,
    availability_state: str = "available",
    supported_languages: list[str] | None = None,
    assigned_queues: list[str] | None = None,
) -> AgentProfile:
    if availability_state not in AGENT_AVAILABILITY_STATES:
        raise ValueError(f"invalid agent availability_state: {availability_state}")
    agent = await get_agent_by_agent_id(db, agent_id)
    if not agent:
        agent = await get_agent_by_extension(db, extension)

    if not assigned_queues:
        assigned_queues = await infer_default_queues(db, extension)
    if not supported_languages:
        supported_languages = [preferred_language]

    now = datetime.utcnow()
    if agent:
        agent.agent_id = agent_id
        agent.display_name = display_name
        agent.extension = extension
        agent.availability_state = availability_state
        agent.preferred_language = preferred_language
        agent.supported_languages = _serialize_csv(supported_languages)
        agent.assigned_queues = _serialize_csv(assigned_queues)
        agent.current_call_id = None if availability_state != "busy" else agent.current_call_id
        agent.state_changed_at = now
        agent.updated_at = now
    else:
        agent = AgentProfile(
            agent_id=agent_id,
            display_name=display_name,
            extension=extension,
            availability_state=availability_state,
            preferred_language=preferred_language,
            supported_languages=_serialize_csv(supported_languages),
            assigned_queues=_serialize_csv(assigned_queues),
            state_changed_at=now,
            updated_at=now,
        )
        db.add(agent)

    await db.commit()
    await db.refresh(agent)
    log.info("Agent registered or updated",
             agent_id=agent.agent_id,
             extension=agent.extension,
             state=agent.availability_state,
             preferred_language=agent.preferred_language,
             queues=agent.assigned_queues)
    return agent


async def set_agent_state(
    db: AsyncSession,
    *,
    agent_id: str | None = None,
    extension: str | None = None,
    availability_state: str,
    preferred_language: str | None = None,
) -> AgentProfile | None:
    if availability_state not in AGENT_AVAILABILITY_STATES:
        raise ValueError(f"invalid agent availability_state: {availability_state}")
    agent = None
    if agent_id:
        agent = await get_agent_by_agent_id(db, agent_id)
    if not agent and extension:
        agent = await get_agent_by_extension(db, extension)
    if not agent:
        return None
    agent.availability_state = availability_state
    if preferred_language:
        agent.preferred_language = preferred_language
        supported = _csv_list(agent.supported_languages)
        if preferred_language not in supported:
            supported.insert(0, preferred_language)
            agent.supported_languages = _serialize_csv(supported)
    if availability_state != "busy":
        agent.current_call_id = None
    now = datetime.utcnow()
    agent.state_changed_at = now
    agent.updated_at = now
    await db.commit()
    await db.refresh(agent)
    return agent


async def reserve_agent_for_call(db: AsyncSession, agent_id: str, call_id: str) -> AgentProfile | None:
    agent = await get_agent_by_agent_id(db, agent_id)
    if not agent:
        return None
    now = datetime.utcnow()
    agent.availability_state = "busy"
    agent.current_call_id = call_id
    agent.last_offered_at = now
    agent.state_changed_at = now
    agent.updated_at = now
    await db.commit()
    await db.refresh(agent)
    return agent


async def release_agent_from_call(db: AsyncSession, agent_id: str, call_id: str = "") -> AgentProfile | None:
    agent = await get_agent_by_agent_id(db, agent_id)
    if not agent:
        return None
    if call_id and agent.current_call_id and agent.current_call_id != call_id:
        return agent
    if agent.availability_state == "busy":
        agent.availability_state = "available"
    agent.current_call_id = None
    now = datetime.utcnow()
    agent.state_changed_at = now
    agent.updated_at = now
    await db.commit()
    await db.refresh(agent)
    return agent


def _to_agent_route(agent: AgentProfile, caller_lang: str) -> AgentRoute:
    preferred_language = agent.preferred_language or "en"
    supported_languages = _csv_list(agent.supported_languages) or [preferred_language]
    return AgentRoute(
        agent_id=agent.agent_id,
        extension=agent.extension,
        display_name=agent.display_name,
        preferred_language=preferred_language,
        supported_languages=supported_languages,
        assigned_queues=_csv_list(agent.assigned_queues),
        translation_required=preferred_language != caller_lang,
        source="agent",
    )


async def claim_agent_for_call(
    db: AsyncSession,
    caller_lang: str,
    call_id: str,
    requested_queue: str | None = None,
) -> AgentRoute | None:
    # Use optimistic conditional UPDATE because SQLite bare-metal deploys do not
    # give us a clean SKIP LOCKED story; the row is claimed only if still idle.
    for _attempt in range(3):
        result = await db.execute(
            select(AgentProfile).where(
                AgentProfile.availability_state == "available",
                AgentProfile.current_call_id.is_(None),
            )
        )
        agents = list(result.scalars().all())
        if not agents:
            return None

        matching = [agent for agent in agents if _queue_matches(agent, requested_queue)]
        if requested_queue and not matching:
            log.warning("no queue match, falling back", requested_queue=requested_queue)
        candidates = matching or agents

        preferred = [agent for agent in candidates if (agent.preferred_language or "en") == caller_lang]
        supported = [agent for agent in candidates if caller_lang in _csv_list(agent.supported_languages)]
        tier = preferred or supported or candidates
        ranked = sorted(
            tier,
            key=lambda agent: (
                agent.last_offered_at or datetime.min,
                agent.display_name.lower(),
                agent.extension,
            ),
        )

        now = datetime.utcnow()
        for candidate in ranked:
            claim = await db.execute(
                update(AgentProfile)
                .where(
                    AgentProfile.id == candidate.id,
                    AgentProfile.availability_state == "available",
                    AgentProfile.current_call_id.is_(None),
                )
                .values(
                    availability_state="busy",
                    current_call_id=call_id,
                    last_offered_at=now,
                    state_changed_at=now,
                    updated_at=now,
                )
            )
            if (claim.rowcount or 0) == 1:
                await db.commit()
                claimed = await get_agent_by_agent_id(db, candidate.agent_id)
                if not claimed:
                    return None
                route = _to_agent_route(claimed, caller_lang)
                log.info(
                    "Claimed available human agent",
                    agent_id=route.agent_id,
                    extension=route.extension,
                    queue=requested_queue,
                    caller_lang=caller_lang,
                    agent_lang=route.preferred_language,
                    translation_required=route.translation_required,
                )
                return route

        await db.rollback()
    return None


async def find_available_agent(
    db: AsyncSession,
    *,
    caller_lang: str,
    requested_queue: str | None = None,
) -> AgentRoute | None:
    result = await db.execute(
        select(AgentProfile).where(AgentProfile.availability_state == "available")
    )
    agents = list(result.scalars().all())
    if not agents:
        return None

    matching = [agent for agent in agents if _queue_matches(agent, requested_queue)]
    candidates = matching or agents
    ranked = sorted(
        candidates,
        key=lambda agent: (
            _queue_rank(agent, requested_queue),
            _language_rank(agent, caller_lang),
            agent.last_offered_at or datetime.min,
            agent.display_name.lower(),
            agent.extension,
        ),
    )
    selected = ranked[0]
    route = _to_agent_route(selected, caller_lang)
    log.info("Selected available human agent",
             agent_id=route.agent_id,
             extension=route.extension,
             queue=requested_queue,
             caller_lang=caller_lang,
             agent_lang=route.preferred_language,
             translation_required=route.translation_required)
    return route
