"""
Extension routing — maps detected intents/departments to Asterisk extensions.
Rules are loaded from the database (editable via the dashboard).
"""
import json
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import RoutingRule
from config import settings

log = structlog.get_logger(__name__)

# Fallback rules from config (used if DB is empty)
_FALLBACK_RULES: dict[str, str] = json.loads(settings.routing_rules)


async def get_extension_for_intent(
    department: str | None,
    intent: str,
    db: AsyncSession,
) -> str:
    """
    Look up the correct extension for a given department/intent.

    Priority:
      1. Exact keyword match in DB routing rules (ordered by priority)
      2. Fallback config rules
      3. Default operator (1001)
    """
    if not department and intent == "transfer":
        return _FALLBACK_RULES.get("default", "1001")

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
            log.info("Routing via DB rule", keyword=lookup_key, extension=rule.extension)
            return rule.extension
    except Exception as e:
        log.warning("DB routing lookup failed, using fallback", error=str(e))

    # Fallback to config rules
    ext = _FALLBACK_RULES.get(lookup_key) or _FALLBACK_RULES.get("default", "1001")
    log.info("Routing via config fallback", keyword=lookup_key, extension=ext)
    return ext


async def get_all_rules(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(RoutingRule).order_by(RoutingRule.priority))
    rules = result.scalars().all()
    return [
        {
            "id": r.id,
            "keyword": r.keyword,
            "extension": r.extension,
            "description": r.description,
            "active": r.active,
            "priority": r.priority,
        }
        for r in rules
    ]


async def upsert_rule(
    keyword: str,
    extension: str,
    description: str,
    priority: int,
    db: AsyncSession,
) -> dict:
    result = await db.execute(select(RoutingRule).where(RoutingRule.keyword == keyword))
    rule = result.scalars().first()

    if rule:
        rule.extension = extension
        rule.description = description
        rule.priority = priority
    else:
        rule = RoutingRule(
            keyword=keyword,
            extension=extension,
            description=description,
            priority=priority,
        )
        db.add(rule)

    await db.commit()
    await db.refresh(rule)
    return {"id": rule.id, "keyword": rule.keyword, "extension": rule.extension}
