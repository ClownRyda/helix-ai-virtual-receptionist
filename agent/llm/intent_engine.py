"""
LLM intent detection and conversation management via Ollama.

Intents:
  - schedule   → caller wants to book a callback appointment
  - transfer   → caller wants to speak to a specific person/department
  - info       → caller has a question the AI can answer
  - unknown    → can't determine, ask for clarification
"""
import json
import re
import structlog
import ollama
from config import settings

log = structlog.get_logger(__name__)

INTENT_SYSTEM_PROMPT = """You are a call routing assistant. Analyze the caller's message and respond with JSON only.

Determine the intent from these options:
- "schedule": caller wants to book an appointment, callback, or meeting
- "transfer": caller wants to speak to a specific department (sales, support, billing, technical, operator)
- "info": caller has a general question
- "unknown": unclear intent

Also extract:
- "department": if transfer intent, which department (sales, support, billing, technical, operator, or null)
- "caller_name": if the caller stated their name (or null)
- "reason": brief 1-sentence reason for the call (or null)

Respond ONLY with valid JSON, no other text. Example:
{"intent": "transfer", "department": "support", "caller_name": "John Smith", "reason": "Having trouble with the software"}
"""

CONVERSATION_SYSTEM_PROMPT = """You are {agent_name}, a professional virtual receptionist for {business_name}.
Keep responses SHORT — this is a phone call. 1-2 sentences max.
You MUST NOT discuss topics unrelated to routing the call or scheduling.
If scheduling: confirm the caller's name and phone number, then offer available time slots.
If transferring: confirm the department and let them know you're connecting them.
Always be warm but efficient."""


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
        self.collecting_info: bool = False  # True when gathering name/phone for scheduling

    def add_turn(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if role == "user":
            self.turn_count += 1


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

        return result

    except (json.JSONDecodeError, Exception) as e:
        log.warning("Intent detection failed", error=str(e))
        return {"intent": "unknown", "department": None, "caller_name": None, "reason": None}


async def generate_response(transcript: str, state: ConversationState, context: str = "") -> str:
    """
    Generate a conversational response for the caller.

    Args:
        transcript: Latest caller utterance
        state: Current conversation state
        context: Additional context (e.g., available time slots from calendar)

    Returns:
        Text response to speak to the caller.
    """
    system = CONVERSATION_SYSTEM_PROMPT.format(
        agent_name=settings.agent_name,
        business_name=settings.business_name,
    )

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
        # Strip any thinking tags (Qwen3 uses <think>...</think>)
        response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        state.add_turn("assistant", response)
        log.info("Generated response", response=response[:80])
        return response

    except Exception as e:
        log.error("Response generation failed", error=str(e))
        return "I'm sorry, I had a technical issue. Let me transfer you to our operator."


async def _ollama_chat(model: str, messages: list[dict], format: str = "") -> str:
    """Raw Ollama chat call, returns content string."""
    kwargs = {
        "model": model,
        "messages": messages,
        "options": {"temperature": 0.3, "num_predict": 150},
    }
    if format:
        kwargs["format"] = format

    # ollama Python client is sync; run in thread pool
    import asyncio
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: ollama.chat(**kwargs)
    )
    return response["message"]["content"]
