import aiohttp
import hashlib
import json
import re
import structlog
from dataclasses import dataclass

from config import settings

log = structlog.get_logger(__name__)

SUPPORTED_VTIGER_MODULES = {"Contacts", "Leads"}


def normalize_phone_number(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return digits


def phone_query_candidates(phone: str | None) -> list[str]:
    raw = (phone or "").strip()
    normalized = normalize_phone_number(raw)
    candidates: list[str] = []
    for candidate in (raw, normalized, f"+{normalized}" if normalized else ""):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


@dataclass
class VtigerRecord:
    module: str
    record_id: str
    label: str
    phone: str
    created: bool = False


class VtigerClient:
    def __init__(self, base_url: str, username: str, access_key: str):
        self.base_url = (base_url or "").rstrip("/")
        self.username = username or ""
        self.access_key = access_key or ""
        self.ws_url = f"{self.base_url}/webservice.php"

    @classmethod
    def from_settings(cls) -> "VtigerClient":
        return cls(
            base_url=settings.vtiger_base_url,
            username=settings.vtiger_username,
            access_key=settings.vtiger_access_key,
        )

    def configured(self) -> bool:
        return bool(self.base_url and self.username and self.access_key)

    async def _get_json(self, session: aiohttp.ClientSession, params: dict) -> dict:
        async with session.get(self.ws_url, params=params) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"Vtiger GET failed: HTTP {response.status} {payload}")
            if not payload.get("success"):
                raise RuntimeError(str(payload.get("error") or payload))
            return payload["result"]

    async def _post_json(self, session: aiohttp.ClientSession, data: dict) -> dict:
        async with session.post(self.ws_url, data=data) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"Vtiger POST failed: HTTP {response.status} {payload}")
            if not payload.get("success"):
                raise RuntimeError(str(payload.get("error") or payload))
            return payload["result"]

    async def _login(self, session: aiohttp.ClientSession) -> dict:
        if not self.configured():
            raise RuntimeError("Vtiger is not fully configured")
        last_error: Exception | None = None
        for attempt in range(2):
            challenge = await self._get_json(
                session,
                {"operation": "getchallenge", "username": self.username},
            )
            token = challenge["token"]
            access_hash = hashlib.md5(f"{token}{self.access_key}".encode("utf-8")).hexdigest()
            try:
                return await self._post_json(
                    session,
                    {"operation": "login", "username": self.username, "accessKey": access_hash},
                )
            except RuntimeError as exc:
                last_error = exc
                if attempt == 0 and "INVALID_USER_CREDENTIALS" in str(exc):
                    log.warning("Vtiger login failed on first attempt; retrying once")
                    continue
                raise
        if last_error:
            raise last_error
        raise RuntimeError("Vtiger login failed")

    async def health(self) -> dict:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            login = await self._login(session)
            return {
                "ok": True,
                "base_url": self.base_url,
                "user_id": login.get("userId"),
                "session_name": login.get("sessionName"),
                "vtiger_version": login.get("vtigerVersion"),
            }

    async def lookup_by_phone(self, phone: str | None) -> VtigerRecord | None:
        timeout = aiohttp.ClientTimeout(total=20)
        candidates = phone_query_candidates(phone)
        if not candidates:
            return None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            login = await self._login(session)
            session_name = login["sessionName"]
            for module in ("Contacts", "Leads"):
                fields = "id,firstname,lastname,phone,mobile"
                for candidate in candidates:
                    safe_candidate = candidate.replace("'", "\\'")
                    query = (
                        f"select {fields} from {module} "
                        f"where phone='{safe_candidate}' or mobile='{safe_candidate}';"
                    )
                    result = await self._get_json(
                        session,
                        {"operation": "query", "sessionName": session_name, "query": query},
                    )
                    if result:
                        row = result[0]
                        label_parts = [row.get("firstname") or "", row.get("lastname") or "", row.get("company") or ""]
                        label = " ".join(part for part in label_parts if part).strip() or candidate
                        return VtigerRecord(
                            module=module,
                            record_id=row["id"],
                            label=label,
                            phone=row.get("phone") or row.get("mobile") or candidate,
                            created=False,
                        )
        return None

    async def create_caller(self, phone: str | None, default_module: str = "Contacts") -> VtigerRecord | None:
        module = default_module if default_module in SUPPORTED_VTIGER_MODULES else "Contacts"
        normalized = normalize_phone_number(phone)
        if not normalized:
            return None
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            login = await self._login(session)
            session_name = login["sessionName"]
            user_id = login["userId"]
            display_name = normalized
            if module == "Contacts":
                element = {
                    "assigned_user_id": user_id,
                    "firstname": "Helix",
                    "lastname": display_name,
                    "phone": normalized,
                    "mobile": normalized,
                    "description": f"Created automatically by Helix for caller {normalized}.",
                }
            else:
                element = {
                    "assigned_user_id": user_id,
                    "firstname": "Helix",
                    "lastname": display_name,
                    "company": "Helix Caller",
                    "phone": normalized,
                    "mobile": normalized,
                    "description": f"Created automatically by Helix for caller {normalized}.",
                }
            created = await self._post_json(
                session,
                {
                    "operation": "create",
                    "sessionName": session_name,
                    "elementType": module,
                    "element": json.dumps(element),
                },
            )
            label = " ".join(
                part for part in (created.get("firstname") or "", created.get("lastname") or "", created.get("company") or "") if part
            ).strip() or normalized
            return VtigerRecord(
                module=module,
                record_id=created["id"],
                label=label,
                phone=normalized,
                created=True,
            )

    async def ensure_caller(self, phone: str | None, default_module: str = "Contacts") -> VtigerRecord | None:
        record = await self.lookup_by_phone(phone)
        if record:
            return record
        return await self.create_caller(phone, default_module=default_module)

    async def append_note_to_record(self, module: str, record_id: str, note: str) -> None:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            login = await self._login(session)
            session_name = login["sessionName"]
            current = await self._get_json(
                session,
                {"operation": "retrieve", "sessionName": session_name, "id": record_id},
            )
            current_description = current.get("description") or ""
            updated_description = f"{current_description.rstrip()}\n\n{note}".strip() if current_description else note
            current["description"] = updated_description
            await self._post_json(
                session,
                {
                    "operation": "revise",
                    "sessionName": session_name,
                    "element": json.dumps(current),
                },
            )
