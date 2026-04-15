"""
LLM intent detection and conversation management via Ollama.

Intents:
  - schedule   → caller wants to book a callback appointment
  - transfer   → caller wants to speak to a specific person/department
  - info       → caller has a general question
  - faq        → caller's question matches a known FAQ entry (feature-flagged)
  - unknown    → can't determine, ask for clarification

v1.2 additions:
  - FAQ chunk injection from local faq.txt (gated by FAQ_ENABLED)
  - generate_call_summary() for post-call LLM summary (gated by CALL_SUMMARY_ENABLED)
"""
import json
import re
import os
import structlog
import ollama
from functools import lru_cache
from config import settings

log = structlog.get_logger(__name__)

# ── FAQ loader ───────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_faq() -> list[str]:
    """
    Load FAQ entries from the configured file.
    Each non-empty line is treated as one FAQ chunk.
    Cached so the file is only read once at startup.
    """
    if not settings.faq_enabled:
        return []
    faq_path = settings.faq_file
    if not os.path.isabs(faq_path):
        # Resolve relative to agent directory
        faq_path = os.path.join(os.path.dirname(__file__), "..", faq_path)
    faq_path = os.path.normpath(faq_path)
    try:
        with open(faq_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        log.info("FAQ loaded", entries=len(lines), path=faq_path)
        return lines
    except FileNotFoundError:
        log.warning("FAQ file not found — FAQ disabled", path=faq_path)
        return []
    except Exception as e:
        log.warning("FAQ load error", error=str(e))
        return []


def _find_faq_chunks(query: str, max_chunks: int = 3) -> list[str]:
    """
    Simple keyword match — returns up to max_chunks FAQ lines that share
    at least one word with the query. No vector DB required.
    """
    faq = _load_faq()
    if not faq:
        return []
    query_words = set(query.lower().split())
    scored = []
    for line in faq:
        line_words = set(line.lower().split())
        overlap = len(query_words & line_words)
        if overlap > 0:
            scored.append((overlap, line))
    scored.sort(reverse=True)
    return [line for _, line in scored[:max_chunks]]


# ── System prompts ────────────────────────────────────────────────────────────

_faq_intent_line = (
    '\n- "faq": caller is asking about business information that may be in our knowledge base'
    if settings.faq_enabled else ""
)

INTENT_SYSTEM_PROMPT = f"""You are a call routing assistant. Analyze the caller's message and respond with JSON only.

Determine the intent from these options:
- "schedule": caller wants to book an appointment, callback, or meeting
- "transfer": caller wants to speak to a specific department (sales, support, billing, technical, operator)
- "info": caller has a general question{_faq_intent_line}
- "unknown": unclear intent

Also extract:
- "department": if transfer intent, which department (sales, support, billing, technical, operator, or null)
- "caller_name": if the caller stated their name (or null)
- "reason": brief 1-sentence reason for the call (or null)

Respond ONLY with valid JSON, no other text. Example:
{{"intent": "transfer", "department": "support", "caller_name": "John Smith", "reason": "Having trouble with the software"}}
"""

CONVERSATION_SYSTEM_PROMPT = """You are {agent_name}, a professional virtual receptionist for {business_name}.
Keep responses SHORT — this is a phone call. 1-2 sentences max.
You MUST NOT discuss topics unrelated to routing the call or scheduling.
If scheduling: confirm the caller's name and phone number, then offer available time slots.
If transferring: confirm the department and let them know you're connecting them.
Always be warm but efficient."""

BILINGUAL_ADDENDUM = """
IMPORTANT: You must respond in {response_lang}. Do not mix languages."""

SUMMARY_SYSTEM_PROMPT = """You are a call summarizer. Given a conversation transcript from a phone call,
produce a brief structured summary in 2-3 sentences covering:
1. Who called and why
2. What was accomplished (transferred, scheduled, answered, or abandoned)
3. Any follow-up needed

Be factual and concise. Output plain text only."""


# ── Conversation state ────────────────────────────────────────────────────────

class ConversationState:
    """Tracks the state of an active call conversation."""

    def __init__(self, call_id: str, caller_id: str):
        self.call_id = call_id
        self.caller_id = caller_id
        self.messages: list[dict] = []
        self.intent: str | None = None
        self.department: str | None = None
        self.caller_name: str | None = None
        self.caller_phone: str = caller_id
        self.reason: str | None = None
        self.turn_count: int = 0
        self.collecting_info: bool = False
        # Bilingual support
        self.caller_lang: str = "en"
        self.lang_confirmed: bool = False
        # Retry tracking
        self.retry_count: int = 0      # consecutive no-speech / unknown-intent events
        self.unknown_count: int = 0    # consecutive unknown-intent turns

    def add_turn(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if role == "user":
            self.turn_count += 1


# ── Intent detection ─────────────────────────────────────────────────────────

async def detect_intent(transcript: str, state: ConversationState) -> dict:
    """
    Run a quick intent detection pass on the latest caller utterance.
    Returns dict with intent, department, caller_name, reason.
    """
    try:
        response = await _ollama_chat(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            format="json",
        )
        result = json.loads(response)
        log.info("Intent detected", **result)

        state.intent = result.get("intent", "unknown")
        if result.get("department"):
            state.department = result["department"]
        if result.get("caller_name"):
            state.caller_name = result["caller_name"]
        if result.get("reason"):
            state.reason = result["reason"]

        # Track consecutive unknowns for retry logic
        if state.intent == "unknown":
            state.unknown_count += 1
        else:
            state.unknown_count = 0

        return result

    except (json.JSONDecodeError, Exception) as e:
        log.warning("Intent detection failed", error=str(e))
        return {"intent": "unknown", "department": None, "caller_name": None, "reason": None}


# ── Response generation ───────────────────────────────────────────────────────

async def generate_response(transcript: str, state: ConversationState, context: str = "") -> str:
    """
    Generate a conversational response for the caller.

    Args:
        transcript: Latest caller utterance (in English)
        state: Current conversation state
        context: Additional context (e.g., available time slots from calendar)

    Returns:
        Text response to speak to the caller.
    """
    lang_names = {"en": "English", "es": "Spanish"}
    response_lang = lang_names.get(state.caller_lang, "English")

    system = CONVERSATION_SYSTEM_PROMPT.format(
        agent_name=settings.agent_name,
        business_name=settings.business_name,
    ) + BILINGUAL_ADDENDUM.format(response_lang=response_lang)

    # Inject FAQ context if enabled and we have relevant chunks
    if settings.faq_enabled:
        faq_chunks = _find_faq_chunks(transcript)
        if faq_chunks:
            system += "\n\nBusiness information you may use to answer the caller:\n"
            system += "\n".join(f"- {chunk}" for chunk in faq_chunks)

    if context:
        system += f"\n\nContext: {context}"

    # Add caller turn to history
    state.add_turn("user", transcript)

    messages = [{"role": "system", "content": system}] + state.messages

    try:
        response = await _ollama_chat(
            model=settings.ollama_model,
            messages=messages,
        )
        # Strip any thinking tags (e.g. Qwen3 <think>...</think>)
        response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        state.add_turn("assistant", response)
        log.info("Generated response", response=response[:80])
        return response

    except Exception as e:
        log.error("Response generation failed", error=str(e))
        return "I'm sorry, I had a technical issue. Let me transfer you to our operator."


# ── Call summary ──────────────────────────────────────────────────────────────

async def generate_call_summary(state: ConversationState, transcript: str) -> str:
    """
    Generate a brief post-call summary using the LLM.
    Gated by CALL_SUMMARY_ENABLED — returns empty string if disabled.
    """
    if not settings.call_summary_enabled:
        return ""
    try:
        prompt = f"Caller: {state.caller_id}\nIntent: {state.intent}\nDepartment: {state.department}\n\nTranscript:\n{transcript}"
        response = await _ollama_chat(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        log.info("Call summary generated", summary=response[:80])
        return response
    except Exception as e:
        log.warning("Call summary generation failed", error=str(e))
        return ""


# ── Ollama wrapper ────────────────────────────────────────────────────────────

async def _ollama_chat(model: str, messages: list[dict], format: str = "") -> str:
    """Raw Ollama chat call, returns content string."""
    kwargs = {
        "model": model,
        "messages": messages,
        "options": {"temperature": 0.3, "num_predict": 150},
    }
    if format:
        kwargs["format"] = format

    import asyncio
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: ollama.chat(**kwargs)
    )
    return response["message"]["content"]
