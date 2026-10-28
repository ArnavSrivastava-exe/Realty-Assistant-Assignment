"""Central configuration. Values come from environment variables / backend/.env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _placeholder_to_empty(value: str) -> str:
    value = value.strip()
    return "" if value.startswith("your_") else value


# --- Gemini ---------------------------------------------------------------
GEMINI_API_KEY = _placeholder_to_empty(os.getenv("GEMINI_API_KEY", ""))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"
# Tried in order when the configured model is unavailable for the API key.
GEMINI_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-2.5-flash,gemini-2.5-flash-lite",
    ).split(",")
    if m.strip()
]
GEMINI_TIMEOUT_SECONDS = _float("GEMINI_TIMEOUT_SECONDS", 40)
GEMINI_MAX_ATTEMPTS = max(1, _int("GEMINI_MAX_ATTEMPTS", 3))

# --- ElevenLabs -------------------------------------------------------------
ELEVENLABS_API_KEY = _placeholder_to_empty(os.getenv("ELEVENLABS_API_KEY", ""))
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2").strip() or "eleven_multilingual_v2"
# Keys are "<language>-<gender>". Defaults are ElevenLabs premade voices; override in .env.
ELEVENLABS_VOICES = {
    "en-female": os.getenv("ELEVENLABS_VOICE_EN_FEMALE", "21m00Tcm4TlvDq8ikWAM").strip(),
    "en-male": os.getenv("ELEVENLABS_VOICE_EN_MALE", "pNInz6obpgDQGcFmaJgB").strip(),
    "hi-female": os.getenv("ELEVENLABS_VOICE_HI_FEMALE", "EXAVITQu4vr4xnSDxMaL").strip(),
    "hi-male": os.getenv("ELEVENLABS_VOICE_HI_MALE", "nPczCjzI2devNBz1zQrb").strip(),
}

# --- CORS -----------------------------------------------------------------
FRONTEND_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").split(",")
    if o.strip()
]
for _origin in list(FRONTEND_ORIGINS):
    if "localhost" in _origin:
        FRONTEND_ORIGINS.append(_origin.replace("localhost", "127.0.0.1"))

# --- Folders --------------------------------------------------------------
TEMP_DIR = BASE_DIR / "temp_uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Upload limits ----------------------------------------------------------
MIN_IMAGES = 4
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 60 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_TOTAL_BYTES + 2 * 1024 * 1024
MIN_IMAGE_SIDE = 400
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# --- Video ----------------------------------------------------------------
VIDEO_WIDTH = _int("VIDEO_WIDTH", 720)
VIDEO_HEIGHT = _int("VIDEO_HEIGHT", 1280)
VIDEO_WIDTH -= VIDEO_WIDTH % 2   # H.264 + yuv420p needs even dimensions
VIDEO_HEIGHT -= VIDEO_HEIGHT % 2
VIDEO_FPS = _int("VIDEO_FPS", 24)
TRANSITION_SECONDS = 0.6
FONT_PATH = os.getenv("FONT_PATH", "").strip()

# --- TTS (Google fallback) ----------------------------------------------------
TTS_ENABLED = _bool("TTS_ENABLED", True)
TTS_LANG = os.getenv("TTS_LANG", "en").strip() or "en"
TTS_TLD = os.getenv("TTS_TLD", "com").strip() or "com"

# --- Jobs -----------------------------------------------------------------
MAX_CONCURRENT_JOBS = max(1, _int("MAX_CONCURRENT_JOBS", 1))
MAX_JOBS_IN_MEMORY = 200
OUTPUT_RETENTION_HOURS = _float("OUTPUT_RETENTION_HOURS", 24)