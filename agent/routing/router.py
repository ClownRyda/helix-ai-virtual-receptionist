"""
Extension routing — maps detected intents/departments to Asterisk extensions.
Rules are loaded from the database (editable via the dashboard).

Each rule now carries an agent_lang field so the transfer flow can
automatically start a TranslationRelay when the caller and call taker
speak different languages.
"""
import json
from dataclasses import dataclass
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import RoutingRule
from config import settings

log = structlog.get_logger(__name__)

# Fallback extension rules from config (used if DB is empty)
_FALLBACK_RULES: dict[str, str] = json.loads(settings.routing_rules)

# Fallback agent language per extension (all English unless overridden in DB)
_FALLBACK_AGENT_LANG: dict[str, str] = {
    ext: "en" for ext in _FALLBACK_RULES.values()
}


@dataclass
class RouteResult:
    """Result of a routing lookup — extension + the language of the person there."""
    extension: str
    agent_lang: str   # language spoken by the person at this extension


async def get_route_for_intent(
    department: str | None,
    intent: str,
    db: AsyncSession,
) -> RouteResult:
    """
    Look up the correct extension and agent language for a given department/intent.

    Priority:
      1. Exact keyword match in DB routing rules (ordered by priority)
      2. Fallback config rules (agent_lang defaults to 'en')
      3. Default operator (1001, English)
    """
    if not department and intent == "transfer":
        ext = _FALLBACK_RULES.get("default", "1001")
        return RouteResult(extension=ext, agent_lang="en")

    lookup_key = (department or "").lower()

    # Try DB rules first
    try:
        result = await db.execute(
            select(RoutingRule)
            .where(RoutingRule.keyword == lookup_key, RoutingRule.active == True)
            .order_by(RoutingRule.priority)
        )
        rule = result.scalars().first()
        if rule:
            log.info("Routing via DB rule",
                     keyword=lookup_key,
                     extension=rule.extension,
                     agent_lang=rule.agent_lang)
            return RouteResult(
                extension=rule.extension,
                agent_lang=rule.agent_lang or "en",
            )
    except Exception as e:
        log.warning("DB routing lookup failed, using fallback", error=str(e))

    # Fallback to config rules
    ext = _FALLBACK_RULES.get(lookup_key) or _FALLBACK_RULES.get("default", "1001")
    agent_lang = _FALLBACK_AGENT_LANG.get(ext, "en")
    log.info("Routing via config fallback",
             keyword=lookup_key,
             extension=ext,
             agent_lang=agent_lang)
    return RouteResult(extension=ext, agent_lang=agent_lang)


# Keep old name as alias so nothing else breaks
async def get_extension_for_intent(
    department: str | None,
    intent: str,
    db: AsyncSession,
) -> str:
    """Legacy alias — returns extension only. Use get_route_for_intent for bilingual support."""
    result = await get_route_for_intent(department, intent, db)
    return result.extension


async def get_all_rules(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(RoutingRule).order_by(RoutingRule.priority))
    rules = result.scalars().all()
    return [
        {
            "id":          r.id,
            "keyword":     r.keyword,
            "extension":   r.extension,
            "description": r.description,
            "active":      r.active,
            "priority":    r.priority,
            "agent_lang":  r.agent_lang or "en",
        }
        for r in rules
    ]


async def upsert_rule(
    keyword: str,
    extension: str,
    description: str,
    priority: int,
    agent_lang: str = "en",
    db: AsyncSession = None,
) -> dict:
    result = await db.execute(select(RoutingRule).where(RoutingRule.keyword == keyword))
    rule = result.scalars().first()

    if rule:
        rule.extension   = extension
        rule.description = description
        rule.priority    = priority
        rule.agent_lang  = agent_lang
    else:
        rule = RoutingRule(
            keyword=keyword,
            extension=extension,
            description=description,
            priority=priority,
            agent_lang=agent_lang,
        )
        db.add(rule)

    await db.commit()
    await db.refresh(rule)
    return {
        "id":         rule.id,
        "keyword":    rule.keyword,
        "extension":  rule.extension,
        "agent_lang": rule.agent_lang,
    }
