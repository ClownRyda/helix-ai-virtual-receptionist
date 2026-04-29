"""
Translation engine with a MarianMT fast path and Ollama fallback.

Used to:
  1. Translate caller speech to English before LLM intent detection
  2. Translate AI responses back to the caller's language before TTS
  3. Provide translated transcripts to the dashboard for call takers
"""
import asyncio
from pathlib import Path

import ollama
import structlog

from config import settings

log = structlog.get_logger(__name__)

try:
    import ctranslate2
    from ctranslate2.converters import TransformersConverter
except Exception:  # pragma: no cover - import availability is environment-dependent
    ctranslate2 = None
    TransformersConverter = None

try:
    from huggingface_hub import snapshot_download
except Exception:  # pragma: no cover - import availability is environment-dependent
    snapshot_download = None

try:
    from langdetect import DetectorFactory, LangDetectException, detect as langdetect_detect

    DetectorFactory.seed = 0
except Exception:  # pragma: no cover - import availability is environment-dependent
    LangDetectException = Exception
    langdetect_detect = None

try:
    from transformers import MarianTokenizer
except Exception:  # pragma: no cover - import availability is environment-dependent
    MarianTokenizer = None

# Canonical language codes
LANG_EN = "en"
LANG_ES = "es"
LANG_FR = "fr"
LANG_IT = "it"
LANG_DE = "de"
LANG_RO = "ro"
LANG_HE = "he"

LANG_NAMES = {
    LANG_EN: "English",
    LANG_ES: "Spanish",
    LANG_FR: "French",
    LANG_IT: "Italian",
    LANG_DE: "German",
    LANG_RO: "Romanian",
    LANG_HE: "Hebrew",
}

SUPPORTED_LANGS = set(LANG_NAMES.keys())
LANG_NORMALIZATION = {
    "iw": LANG_HE,
}

MARIAN_MODEL_MAP = {
    (LANG_EN, LANG_ES): "Helsinki-NLP/opus-mt-en-es",
    (LANG_ES, LANG_EN): "Helsinki-NLP/opus-mt-es-en",
    (LANG_EN, LANG_FR): "Helsinki-NLP/opus-mt-en-fr",
    (LANG_FR, LANG_EN): "Helsinki-NLP/opus-mt-fr-en",
    (LANG_EN, LANG_IT): "Helsinki-NLP/opus-mt-en-it",
    (LANG_IT, LANG_EN): "Helsinki-NLP/opus-mt-it-en",
    (LANG_EN, LANG_DE): "Helsinki-NLP/opus-mt-en-de",
    (LANG_DE, LANG_EN): "Helsinki-NLP/opus-mt-de-en",
    (LANG_EN, LANG_RO): "Helsinki-NLP/opus-mt-en-ro",
    (LANG_RO, LANG_EN): "Helsinki-NLP/opus-mt-ro-en",
    (LANG_EN, LANG_HE): "Helsinki-NLP/opus-mt-en-he",
    (LANG_HE, LANG_EN): "Helsinki-NLP/opus-mt-he-en",
}

TRANSLATE_PROMPT = """You are a professional translator. Translate the following text to {target_language}.
Output ONLY the translated text — no explanations, no quotes, no labels.
If the text is already in {target_language}, output it unchanged.

Text to translate:
{text}"""

DETECT_PROMPT = """Detect the language of the following text. Reply with only the ISO 639-1 language code.
Examples: "en" for English, "es" for Spanish, "fr" for French, "it" for Italian, "de" for German, "ro" for Romanian, "he" for Hebrew.
Output ONLY the 2-letter code, nothing else.

Text:
{text}"""

MODEL_CACHE_ROOT = Path("/opt/helix/.cache/opus-mt")
_MARIAN_ASSETS: dict[tuple[str, str], tuple["ctranslate2.Translator", "MarianTokenizer"]] = {}
_PAIR_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def _normalize_lang(code: str) -> str:
    lang = (code or "").strip().lower()
    return LANG_NORMALIZATION.get(lang, lang)


def _use_marian_backend() -> bool:
    return (settings.translation_backend or "marian").strip().lower() != "ollama"


def _marian_available() -> bool:
    return all((ctranslate2, TransformersConverter, snapshot_download, MarianTokenizer))


def _pair_directory(pair: tuple[str, str]) -> Path:
    return MODEL_CACHE_ROOT / f"{pair[0]}-{pair[1]}"


def _resolve_translation_steps(source_lang: str, target_lang: str) -> list[tuple[str, str]]:
    if source_lang == target_lang:
        return []
    if (source_lang, target_lang) in MARIAN_MODEL_MAP:
        return [(source_lang, target_lang)]
    if source_lang != LANG_EN and target_lang != LANG_EN:
        via_english = [(source_lang, LANG_EN), (LANG_EN, target_lang)]
        if all(step in MARIAN_MODEL_MAP for step in via_english):
            return via_english
    return []


def _prepare_marian_assets(pair: tuple[str, str]) -> tuple["ctranslate2.Translator", "MarianTokenizer"]:
    if not _marian_available():
        raise RuntimeError("Marian translation dependencies are not installed")

    model_name = MARIAN_MODEL_MAP.get(pair)
    if not model_name:
        raise RuntimeError(f"No Marian model configured for {pair[0]}->{pair[1]}")

    pair_dir = _pair_directory(pair)
    source_dir = pair_dir / "hf"
    ct2_dir = pair_dir / "ct2"
    MODEL_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    pair_dir.mkdir(parents=True, exist_ok=True)

    config_file = source_dir / "config.json"
    model_file = ct2_dir / "model.bin"

    if not config_file.exists():
        snapshot_download(repo_id=model_name, local_dir=str(source_dir))

    if not model_file.exists():
        converter = TransformersConverter(model_name_or_path=str(source_dir))
        converter.convert(output_dir=str(ct2_dir), quantization="int8")

    tokenizer = MarianTokenizer.from_pretrained(str(source_dir))
    translator = ctranslate2.Translator(str(ct2_dir), device="cpu")
    return translator, tokenizer


async def _get_marian_assets(pair: tuple[str, str]) -> tuple["ctranslate2.Translator", "MarianTokenizer"]:
    cached = _MARIAN_ASSETS.get(pair)
    if cached:
        return cached

    lock = _PAIR_LOCKS.setdefault(pair, asyncio.Lock())
    async with lock:
        cached = _MARIAN_ASSETS.get(pair)
        if cached:
            return cached
        loop = asyncio.get_running_loop()
        assets = await loop.run_in_executor(None, _prepare_marian_assets, pair)
        _MARIAN_ASSETS[pair] = assets
        return assets


def _decode_translation(tokenizer: "MarianTokenizer", hypothesis: list[str]) -> str:
    token_ids = tokenizer.convert_tokens_to_ids(hypothesis)
    return tokenizer.decode(token_ids, skip_special_tokens=True).strip()


async def _translate_with_marian_single(text: str, pair: tuple[str, str]) -> str:
    translator, tokenizer = await _get_marian_assets(pair)
    source_ids = tokenizer.encode(text)
    source_tokens = tokenizer.convert_ids_to_tokens(source_ids)
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(
        None,
        lambda: translator.translate_batch([source_tokens], beam_size=1),
    )
    if not results or not results[0].hypotheses:
        raise RuntimeError(f"No Marian translation result for {pair[0]}->{pair[1]}")
    return _decode_translation(tokenizer, results[0].hypotheses[0])


async def _translate_with_marian(text: str, target_lang: str, source_lang: str) -> str:
    steps = _resolve_translation_steps(source_lang, target_lang)
    if not steps:
        raise RuntimeError(f"No Marian translation path for {source_lang}->{target_lang}")

    translated = text
    for pair in steps:
        translated = await _translate_with_marian_single(translated, pair)
    return translated


async def prewarm_translation_pair(source_lang: str, target_lang: str) -> None:
    pair = (_normalize_lang(source_lang), _normalize_lang(target_lang))
    if not _use_marian_backend():
        log.info("Translation prewarm skipped", backend="ollama", source=pair[0], target=pair[1])
        return
    try:
        await _get_marian_assets(pair)
        log.info("Translation pair prewarmed", source=pair[0], target=pair[1], cache_dir=str(_pair_directory(pair)))
    except Exception as exc:
        log.warning("Translation prewarm fell back to Ollama", source=pair[0], target=pair[1], error=str(exc))


async def detect_language(text: str) -> str:
    """
    Detect language of text.
    Uses langdetect when available, otherwise falls back to Ollama.
    Defaults to 'en' on failure.
    """
    if not text or len(text.strip()) < 3:
        return LANG_EN

    if langdetect_detect:
        try:
            detected = _normalize_lang(langdetect_detect(text[:200]))
            if detected in SUPPORTED_LANGS:
                log.debug("Language detected", lang=detected, backend="langdetect", text_preview=text[:50])
                return detected
        except LangDetectException as exc:
            log.warning("Language detection failed", backend="langdetect", error=str(exc))
        except Exception as exc:
            log.warning("Language detection failed", backend="langdetect", error=str(exc))

    try:
        prompt = DETECT_PROMPT.format(text=text[:200])
        result = await _ollama_generate(prompt)
        detected = _normalize_lang(result.strip())
        if detected in SUPPORTED_LANGS:
            log.debug("Language detected", lang=detected, backend="ollama", text_preview=text[:50])
            return detected
    except Exception as exc:
        log.warning("Language detection failed", backend="ollama", error=str(exc))

    return LANG_EN


async def translate(text: str, target_lang: str, source_lang: str = "") -> str:
    """
    Translate text to the target language.

    Public signature intentionally unchanged.
    """
    if not text:
        return text

    target_lang = _normalize_lang(target_lang)
    source_lang = _normalize_lang(source_lang) if source_lang else ""

    if target_lang not in SUPPORTED_LANGS:
        return text

    if source_lang and source_lang == target_lang:
        return text

    resolved_source = source_lang or await detect_language(text)
    if resolved_source == target_lang:
        return text

    if _use_marian_backend():
        try:
            translated = await _translate_with_marian(text, target_lang, resolved_source)
            log.info(
                "Translated",
                backend="marian",
                source=resolved_source or "?",
                target=target_lang,
                original=text[:60],
                translated=translated[:60],
            )
            return translated.strip()
        except Exception as exc:
            log.warning(
                "Marian translation failed; falling back to Ollama",
                source=resolved_source or "?",
                target=target_lang,
                error=str(exc),
            )

    try:
        target_name = LANG_NAMES.get(target_lang, target_lang)
        prompt = TRANSLATE_PROMPT.format(target_language=target_name, text=text)
        translated = await _ollama_generate(prompt)
        log.info(
            "Translated",
            backend="ollama",
            source=resolved_source or "?",
            target=target_lang,
            original=text[:60],
            translated=translated[:60],
        )
        return translated.strip()
    except Exception as exc:
        log.error("Translation failed", backend="ollama", error=str(exc))
        return text


async def ensure_english(text: str, detected_lang: str) -> tuple[str, str]:
    """
    If text is not English, translate it to English.

    Public signature intentionally unchanged.
    """
    detected_lang = _normalize_lang(detected_lang)
    if detected_lang == LANG_EN or detected_lang not in SUPPORTED_LANGS:
        return text, detected_lang
    translated = await translate(text, LANG_EN, source_lang=detected_lang)
    return translated, detected_lang


async def localize_for_caller(text: str, caller_lang: str) -> str:
    """
    Translate an English AI response to the caller's language.
    If caller speaks English, returns unchanged.
    """
    caller_lang = _normalize_lang(caller_lang)
    if caller_lang == LANG_EN:
        return text
    return await translate(text, caller_lang, source_lang=LANG_EN)


async def _ollama_generate(prompt: str) -> str:
    """Single-turn Ollama generate call."""
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None,
        lambda: ollama.generate(
            model=settings.ollama_model,
            prompt=prompt,
            options={"temperature": 0.1, "num_predict": 300},
        ),
    )
    return response["response"].strip()
