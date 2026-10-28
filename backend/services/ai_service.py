"""Gemini script generation with model fallback, validation, retries and a template fallback."""
import json
import logging
import re
import time
from typing import Optional

from pydantic import BaseModel

from config import (
    GEMINI_API_KEY, GEMINI_FALLBACK_MODELS, GEMINI_MAX_ATTEMPTS, GEMINI_MODEL, GEMINI_TIMEOUT_SECONDS,
)
from models.schemas import MAX_FEATURES, PropertyData, ScriptScene, VideoScript

logger = logging.getLogger("propertymotion.ai")

MAX_SCENES = MAX_FEATURES + 2
MAX_CAPTION_CHARS = 110
MAX_VOICEOVER_CHARS = 320

# Remembers the model that last worked so later jobs skip unavailable ones.
_active_model: Optional[str] = None

# Words that would make a *claim* the user never supplied. Rejected unless the user wrote them.
_UNSUPPORTED_CLAIM_WORDS = [
    "spacious", "luxurious", "luxury", "premium", "prime", "affordable", "discount", "offer",
    "offers", "guarantee", "guaranteed", "award", "certified", "investment", "returns", "roi",
    "nearby", "close to", "walking distance", "minutes from", "panoramic", "modern",
    "state-of-the-art", "best", "heart of",
]

SYSTEM_INSTRUCTION = (
    "You write short promotional video scripts for real estate listings. "
    "You may ONLY use facts supplied in the PROPERTY FACTS block. Never invent or imply amenities, "
    "sizes, certifications, nearby landmarks, views, investment returns, discounts, or quality "
    "adjectives that were not supplied (for example 'spacious', 'luxurious', 'modern', 'prime'). "
    "Never introduce numbers that were not supplied. Copy the price and contact details exactly as "
    "provided. Use plain, professional, grammatically correct language. "
    "Respond only with JSON matching the schema."
)

_TYPE_HI = {"Apartment": "अपार्टमेंट", "Villa": "विला", "Commercial": "कमर्शियल प्रॉपर्टी", "House": "मकान"}


class _SceneOut(BaseModel):
    type: str
    caption: str
    voiceover: str
    duration_hint: int


class _ScriptOut(BaseModel):
    title: str
    scenes: list[_SceneOut]


class _MalformedResponse(Exception):
    pass


# --------------------------------------------------------------------------- helpers
def _tidy_line(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tidy_caption(value) -> str:
    text = str(value or "").replace("\\n", "\n")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _sentence(text: str, hindi: bool = False) -> str:
    text = text.strip()
    if text[-1:] in ".!?।":
        return text
    return text + ("।" if hindi else ".")


def _digits(text: str) -> list[str]:
    return re.findall(r"\d+", text)


def _input_blob(prop: PropertyData) -> str:
    return " ".join([prop.property_name, prop.location, prop.price, prop.property_type,
                     prop.cta, prop.contact, *prop.features])


def _outro_caption(prop: PropertyData) -> str:
    lines = [prop.price, prop.cta]
    if prop.contact:
        lines.append(prop.contact)
    return "\n".join(lines)


# --------------------------------------------------------------------------- template fallback
_FEATURE_LEADS_EN = [
    "Key feature: {f}.", "Another highlight: {f}.", "You will also find: {f}.",
    "Also featured: {f}.", "Don't miss: {f}.", "Plus: {f}.",
]
_FEATURE_LEADS_HI = [
    "मुख्य विशेषता: {f}।", "एक और ख़ास बात: {f}।", "साथ ही: {f}।",
    "और भी: {f}।", "यह भी देखिए: {f}।", "इसके अलावा: {f}।",
]


def _template_script(prop: PropertyData, warning: str) -> VideoScript:
    hindi = prop.voice_language == "hi"
    leads = _FEATURE_LEADS_HI if hindi else _FEATURE_LEADS_EN

    if hindi:
        intro_voice = f"प्रस्तुत है {prop.property_name}, {prop.location} में स्थित {_TYPE_HI[prop.property_type]}।"
    else:
        intro_voice = f"Introducing {prop.property_name}, a {prop.property_type.lower()} in {prop.location}."

    scenes = [ScriptScene(type="intro", caption=f"{prop.property_name}\n{prop.location}", voiceover=intro_voice, duration_hint=4)]
    for i, feature in enumerate(prop.features):
        feature = feature.rstrip(". ")
        scenes.append(
            ScriptScene(
                type="feature",
                caption=feature[:1].upper() + feature[1:],
                voiceover=leads[i % len(leads)].format(f=feature),
                duration_hint=4,
            )
        )

    if hindi:
        outro_voice = f"{prop.property_name} की कीमत {prop.price} है। {_sentence(prop.cta, True)}"
        if prop.contact:
            outro_voice += f" संपर्क करें: {prop.contact}।"
    else:
        outro_voice = f"{prop.property_name} is priced at {prop.price}. {_sentence(prop.cta)}"
        if prop.contact:
            outro_voice += f" Contact: {prop.contact}."
    scenes.append(ScriptScene(type="outro", caption=_outro_caption(prop), voiceover=outro_voice, duration_hint=5))
    return VideoScript(title=prop.property_name, scenes=scenes, source="template", warning=warning)


# --------------------------------------------------------------------------- Gemini call
def _build_prompt(prop: PropertyData) -> str:
    facts = {
        "property_name": prop.property_name,
        "location": prop.location,
        "price": prop.price,
        "property_type": prop.property_type,
        "key_features": prop.features,
        "contact": prop.contact or None,
        "call_to_action": prop.cta,
    }
    n = len(prop.features)
    language_rule = ""
    if prop.voice_language == "hi":
        language_rule = (
            "- LANGUAGE: write every 'voiceover' in natural, spoken Hindi (Devanagari script). Keep 'caption' "
            "and 'title' in English exactly as described above. Inside the Hindi sentences keep the property "
            "name, location, feature wording, price and contact exactly as supplied (Latin script, Western "
            "digits 0-9 only, never Devanagari digits).\n"
        )
    return (
        "Create a script for a 20-40 second vertical promotional video.\n\n"
        "PROPERTY FACTS (the only facts you may use):\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
        "Requirements:\n"
        f"- Output exactly {n + 2} scenes in this order: 1 'intro', {n} 'feature' (one per key feature, "
        "in the given order), 1 'outro'.\n"
        "- intro: caption = property name and location on two lines (use \\n). voiceover = 1-2 short "
        "sentences (max 30 words) welcoming viewers to the property.\n"
        "- feature: caption = the feature in the supplied wording (max 8 words). voiceover = ONE short "
        "sentence (max 22 words) that only restates that feature.\n"
        "- outro: caption = price, call to action and contact on separate lines (use \\n). voiceover = "
        "closing line (max 35 words) stating the price and the call to action"
        + (" and the contact details" if prop.contact else "")
        + ".\n"
        "- duration_hint: whole seconds. intro 4, features 4 or 5, outro 5.\n"
        + language_rule
        + "- Do not add facts, adjectives that imply quality, numbers, or locations beyond the facts above.\n"
        "- title: the property name."
    )


def _call_gemini(prompt: str, model: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=int(GEMINI_TIMEOUT_SECONDS * 1000)),
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=_ScriptOut,
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise _MalformedResponse("empty response")
    return text


def _discover_models(already_tried: list[str]) -> list[str]:
    """Last resort: ask Google which Flash models this API key can call."""
    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
        skip = ("image", "tts", "live", "audio", "embedding", "native", "robotics", "computer", "vision")
        found: list[str] = []
        for model in client.models.list():
            name = (getattr(model, "name", "") or "").removeprefix("models/")
            actions = getattr(model, "supported_actions", None) or []
            if "generateContent" in actions and "flash" in name and not any(s in name for s in skip) and name not in already_tried:
                found.append(name)
        return sorted(found, reverse=True)[:3]
    except Exception as exc:
        logger.warning("Model discovery failed: %s", str(exc)[:200])
        return []


def _parse_json(text: str) -> dict:
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _MalformedResponse(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise _MalformedResponse("top-level JSON is not an object")
    return data


# --------------------------------------------------------------------------- validation
def _validate_script(data: dict, prop: PropertyData) -> VideoScript:
    hindi = prop.voice_language == "hi"
    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list):
        raise _MalformedResponse("'scenes' missing or not a list")
    if not 4 <= len(raw_scenes) <= MAX_SCENES:
        raise _MalformedResponse(f"expected 4-{MAX_SCENES} scenes, got {len(raw_scenes)}")

    scenes: list[ScriptScene] = []
    for number, item in enumerate(raw_scenes, start=1):
        if not isinstance(item, dict):
            raise _MalformedResponse(f"scene {number} is not an object")
        stype = str(item.get("type", "")).strip().lower()
        if stype not in ("intro", "feature", "outro"):
            raise _MalformedResponse(f"scene {number} has invalid type '{stype}'")
        caption = _tidy_caption(item.get("caption"))
        voiceover = _tidy_line(item.get("voiceover"))
        if not caption or not voiceover:
            raise _MalformedResponse(f"scene {number} has empty caption or voiceover")
        if stype != "outro" and len(caption) > MAX_CAPTION_CHARS:
            raise _MalformedResponse(f"scene {number} caption too long")
        if len(voiceover) > MAX_VOICEOVER_CHARS:
            raise _MalformedResponse(f"scene {number} voiceover too long")
        try:
            hint = float(item.get("duration_hint", 4))
        except (TypeError, ValueError):
            hint = 4.0
        hint = min(max(hint, 3.0), 8.0)
        scenes.append(ScriptScene(type=stype, caption=caption, voiceover=voiceover, duration_hint=hint))

    if scenes[0].type != "intro" or scenes[-1].type != "outro":
        raise _MalformedResponse("first scene must be intro and last must be outro")
    middle = scenes[1:-1]
    if len(middle) < 2 or any(s.type != "feature" for s in middle):
        raise _MalformedResponse("need at least two feature scenes between intro and outro")

    # Deterministic accuracy for the facts that matter most.
    intro, outro = scenes[0], scenes[-1]
    if prop.property_name.lower() not in intro.caption.lower():
        intro.caption = f"{prop.property_name}\n{prop.location}"
    outro.caption = _outro_caption(prop)
    if not all(d in _digits(outro.voiceover) for d in _digits(prop.price)):
        outro.voiceover = outro.voiceover.rstrip() + (f" कीमत {prop.price}।" if hindi else f" Priced at {prop.price}.")
    if prop.contact and not all(d in _digits(outro.voiceover) for d in _digits(prop.contact)):
        outro.voiceover = outro.voiceover.rstrip() + (f" संपर्क करें {prop.contact}।" if hindi else f" Contact {prop.contact}.")

    _reject_invented_facts(scenes, prop)

    title = _tidy_line(data.get("title")) or prop.property_name
    return VideoScript(title=title[:100], scenes=scenes, source="gemini")


def _reject_invented_facts(scenes: list[ScriptScene], prop: PropertyData) -> None:
    blob = _input_blob(prop)
    blob_lower = blob.lower()
    allowed_numbers = set(_digits(blob))
    for number, scene in enumerate(scenes, start=1):
        text = f"{scene.caption} {scene.voiceover}"
        extra = [d for d in _digits(text) if d not in allowed_numbers]
        if extra:
            raise _MalformedResponse(f"scene {number} contains numbers not supplied by the user ({extra[0]})")
        lowered = text.lower()
        for word in _UNSUPPORTED_CLAIM_WORDS:
            if re.search(r"\b" + re.escape(word) + r"\b", lowered) and word not in blob_lower:
                raise _MalformedResponse(f"scene {number} makes an unsupported claim ('{word}')")


# --------------------------------------------------------------------------- error handling
def _classify_error(exc: Exception, model: str) -> tuple[str, str, bool]:
    """Returns (kind, user-facing message, retryable)."""
    code = getattr(exc, "code", None)
    text = str(exc).lower()
    if isinstance(exc, ImportError):
        return "sdk", "The google-genai package is not installed.", False
    if code == 404 or ("not found" in text and "model" in text) or "no longer available" in text:
        return "model", f"Gemini model '{model}' is unavailable for this API key.", False
    if code in (401, 403) or "api key" in text or "permission_denied" in text or "unauthenticated" in text:
        return "auth", "Gemini rejected the API key (authentication or permission error).", False
    if code == 429 or "resource_exhausted" in text or "quota" in text:
        return "quota", "Gemini quota or rate limit was reached.", False
    if code == 400:
        return "bad_request", "Gemini rejected the request (HTTP 400).", False
    if code in (500, 502, 503, 504) or "timed out" in text or "timeout" in text or "deadline" in text:
        return "transient", "Gemini was temporarily unavailable or timed out.", True
    return "unknown", "The Gemini request failed unexpectedly.", True


def _model_queue() -> list[str]:
    first = _active_model or GEMINI_MODEL
    ordered = [first, GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]
    seen: set[str] = set()
    return [m for m in ordered if not (m in seen or seen.add(m))]


# --------------------------------------------------------------------------- public API
def generate_video_script(property_data: PropertyData) -> VideoScript:
    """Ask Gemini for a structured script. Falls back to a template (clearly flagged) on failure."""
    global _active_model

    if not GEMINI_API_KEY:
        return _template_script(
            property_data,
            "GEMINI_API_KEY is not configured, so a template script was used instead of Gemini.",
        )

    prompt = _build_prompt(property_data)
    reason = "Gemini did not return a usable script."
    queue = _model_queue()
    tried: list[str] = []
    discovered = False

    while queue:
        model = queue.pop(0)
        if model in tried:
            continue
        tried.append(model)
        unavailable = False

        for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
            try:
                script = _validate_script(_parse_json(_call_gemini(prompt, model)), property_data)
                if _active_model != model:
                    logger.info("Using Gemini model '%s'", model)
                _active_model = model
                logger.info("Gemini script accepted (model=%s, attempt=%d, %d scenes)", model, attempt, len(script.scenes))
                return script
            except _MalformedResponse as exc:
                reason = f"Gemini returned an unusable script ({exc})."
                logger.warning("Model %s attempt %d/%d malformed: %s", model, attempt, GEMINI_MAX_ATTEMPTS, exc)
            except Exception as exc:
                kind, message, retryable = _classify_error(exc, model)
                reason = message
                logger.warning("Model %s attempt %d/%d error [%s]: %s", model, attempt, GEMINI_MAX_ATTEMPTS, kind, str(exc)[:300])
                if kind == "model":
                    unavailable = True
                    break
                if not retryable:
                    break
                time.sleep(min(2 * attempt, 6))

        if not unavailable:
            break  # quota/auth/malformed/etc. will not be fixed by another model
        if not queue and not discovered:
            discovered = True
            queue = _discover_models(tried)

    if tried and reason.startswith("Gemini model"):
        reason = f"None of the Gemini models tried ({', '.join(tried)}) is available for this API key."
    return _template_script(property_data, f"{reason} A template-based script was used instead of Gemini.")