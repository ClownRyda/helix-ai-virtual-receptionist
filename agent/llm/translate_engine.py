"""
Translation engine using Ollama (fully local, no cloud).

Detects language and translates between English and Spanish.
Used to:
  1. Translate caller speech (ES → EN) before LLM intent detection
  2. Translate AI responses (EN → ES) before Piper TTS speaks to caller
  3. Provide translated transcripts to the dashboard for call takers
"""
import re
import asyncio
import structlog
import ollama
from config import settings

log = structlog.get_logger(__name__)

# Supported language codes
LANG_EN = "en"
LANG_ES = "es"
SUPPORTED_LANGS = {LANG_EN, LANG_ES}

TRANSLATE_PROMPT = """You are a professional translator. Translate the following text to {target_language}.
Output ONLY the translated text — no explanations, no quotes, no labels.
If the text is already in {target_language}, output it unchanged.

Text to translate:
{text}"""

DETECT_PROMPT = """Detect the language of the following text. Reply with only the ISO 639-1 code (e.g. "en" for English, "es" for Spanish).
Output ONLY the 2-letter code, nothing else.

Text:
{text}"""


async def detect_language(text: str) -> str:
    """
    Detect language of text using Ollama.
    Returns ISO 639-1 code ('en', 'es', etc.).
    Defaults to 'en' on failure.
    """
    if not text or len(text.strip()) < 3:
        return LANG_EN

    try:
        prompt = DETECT_PROMPT.format(text=text[:200])
        result = await _ollama_generate(prompt)
        # Extract just the 2-letter code
        code = re.search(r'\b([a-z]{2})\b', result.strip().lower())
        if code:
            lang = code.group(1)
            log.debug("Language detected", lang=lang, text_preview=text[:50])
            return lang
    except Exception as e:
        log.warning("Language detection failed", error=str(e))

    return LANG_EN


async def translate(text: str, target_lang: str, source_lang: str = "") -> str:
    """
    Translate text to target language using Ollama.

    Args:
        text: Text to translate
        target_lang: Target language code ('en' or 'es')
        source_lang: Source language (optional, for logging)

    Returns:
        Translated text, or original text on failure.
    """
    if not text:
        return text

    lang_names = {"en": "English", "es": "Spanish"}
    target_name = lang_names.get(target_lang, target_lang)

    try:
        prompt = TRANSLATE_PROMPT.format(
            target_language=target_name,
            text=text,
        )
        translated = await _ollama_generate(prompt)
        log.info("Translated",
                 source=source_lang or "?",
                 target=target_lang,
                 original=text[:60],
                 translated=translated[:60])
        return translated.strip()

    except Exception as e:
        log.error("Translation failed", error=str(e))
        return text  # Fall back to original


async def ensure_english(text: str, detected_lang: str) -> tuple[str, str]:
    """
    If text is not English, translate it to English.

    Returns:
        (english_text, detected_lang)
    """
    if detected_lang == LANG_EN or detected_lang not in SUPPORTED_LANGS:
        return text, detected_lang
    translated = await translate(text, LANG_EN, source_lang=detected_lang)
    return translated, detected_lang


async def localize_for_caller(text: str, caller_lang: str) -> str:
    """
    Translate an English AI response to the caller's language.
    If caller speaks English, returns unchanged.
    """
    if caller_lang == LANG_EN:
        return text
    return await translate(text, caller_lang, source_lang=LANG_EN)


async def _ollama_generate(prompt: str) -> str:
    """Single-turn Ollama generate call."""
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: ollama.generate(
            model=settings.ollama_model,
            prompt=prompt,
            options={"temperature": 0.1, "num_predict": 300},
        )
    )
    return response["response"].strip()
