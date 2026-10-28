"""Pydantic models and input validation for PropertyMotion AI."""
import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator

PROPERTY_TYPES = ("Apartment", "Villa", "Commercial", "House")
VOICE_LANGUAGES = ("en", "hi")
VOICE_GENDERS = ("male", "female")
MIN_FEATURES = 2
MAX_FEATURES = 6
MAX_FEATURE_LEN = 60

FIELD_LABELS = {
    "property_name": "Property name",
    "location": "Location",
    "price": "Price",
    "cta": "Call-to-action text",
    "contact": "Contact information",
}
FIELD_MAX_LEN = {
    "property_name": 80,
    "location": 100,
    "price": 40,
    "cta": 80,
    "contact": 80,
}

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
_SPACES = re.compile(r"\s{2,}")


def clean_text(value: Any) -> str:
    """Strip control characters, collapse spaces."""
    if not isinstance(value, str):
        return ""
    return _SPACES.sub(" ", _CONTROL_CHARS.sub(" ", value)).strip()


def parse_features(raw: str) -> list[str]:
    """Accepts a JSON array string (preferred) or comma/newline separated text."""
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(item) for item in data]
        except json.JSONDecodeError:
            pass
    return re.split(r"[,\n]", raw)


class PropertyData(BaseModel):
    property_name: str
    location: str
    price: str
    property_type: str
    features: list[str]
    contact: str = ""
    cta: str
    voice_language: str = "en"
    voice_gender: str = "female"

    @field_validator("property_name", "location", "price", "cta", mode="before")
    @classmethod
    def _required_text(cls, value: Any, info: ValidationInfo) -> str:
        text = clean_text(value)
        label = FIELD_LABELS[info.field_name]
        if not text:
            raise ValueError(f"{label} is required.")
        limit = FIELD_MAX_LEN[info.field_name]
        if len(text) > limit:
            raise ValueError(f"{label} must be at most {limit} characters.")
        return text

    @field_validator("contact", mode="before")
    @classmethod
    def _contact(cls, value: Any) -> str:
        text = clean_text(value)
        if len(text) > FIELD_MAX_LEN["contact"]:
            raise ValueError(f"Contact information must be at most {FIELD_MAX_LEN['contact']} characters.")
        return text

    @field_validator("property_type", mode="before")
    @classmethod
    def _property_type(cls, value: Any) -> str:
        text = clean_text(value).lower()
        for allowed in PROPERTY_TYPES:
            if allowed.lower() == text:
                return allowed
        raise ValueError(f"Property type must be one of: {', '.join(PROPERTY_TYPES)}.")

    @field_validator("voice_language", mode="before")
    @classmethod
    def _voice_language(cls, value: Any) -> str:
        text = clean_text(value).lower() or "en"
        if text not in VOICE_LANGUAGES:
            raise ValueError("Choose English or Hindi narration.")
        return text

    @field_validator("voice_gender", mode="before")
    @classmethod
    def _voice_gender(cls, value: Any) -> str:
        text = clean_text(value).lower() or "female"
        if text not in VOICE_GENDERS:
            raise ValueError("Choose a male or female narrator voice.")
        return text

    @field_validator("features", mode="before")
    @classmethod
    def _features(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError(f"Add at least {MIN_FEATURES} key features.")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = clean_text(item)
            if not text:
                continue
            if len(text) > MAX_FEATURE_LEN:
                raise ValueError(f"Each feature must be at most {MAX_FEATURE_LEN} characters.")
            if text.lower() in seen:
                continue
            seen.add(text.lower())
            cleaned.append(text)
        if len(cleaned) < MIN_FEATURES:
            raise ValueError(f"Add at least {MIN_FEATURES} key features.")
        if len(cleaned) > MAX_FEATURES:
            raise ValueError(f"Use at most {MAX_FEATURES} key features.")
        return cleaned


class ScriptScene(BaseModel):
    type: Literal["intro", "feature", "outro"]
    caption: str
    voiceover: str
    duration_hint: float = 4.0


class VideoScript(BaseModel):
    title: str
    scenes: list[ScriptScene]
    source: Literal["gemini", "template"] = "gemini"
    warning: Optional[str] = None


class GenerateResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    stage: str
    progress: int
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    script_source: Optional[str] = None
    narration: Optional[bool] = None
    filename: Optional[str] = None
    video_url: Optional[str] = None
    download_url: Optional[str] = None
    video_info: Optional[dict] = None