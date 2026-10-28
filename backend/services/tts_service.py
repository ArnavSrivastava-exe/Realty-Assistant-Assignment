"""Narration: ElevenLabs (preferred, 4 voice profiles) with a Google TTS fallback.

Also normalises text so numbers are spoken properly (no more "one five zero zero zero ...").
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from config import ELEVENLABS_API_KEY, ELEVENLABS_MODEL, ELEVENLABS_VOICES, TTS_ENABLED, TTS_LANG, TTS_TLD

logger = logging.getLogger("propertymotion.tts")

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


@dataclass
class NarrationClip:
    path: str
    duration: float


# =========================================================================== text normalisation
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_DIGIT_WORDS = {
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
    "hi": ["शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ"],
}
_UNIT_WORDS = {
    "en": {"cr": "crore", "crore": "crore", "crores": "crores", "lakh": "lakh", "lakhs": "lakhs",
           "lac": "lakh", "lacs": "lakhs", "l": "lakh", "k": "thousand"},
    "hi": {"cr": "करोड़", "crore": "करोड़", "crores": "करोड़", "lakh": "लाख", "lakhs": "लाख",
           "lac": "लाख", "lacs": "लाख", "l": "लाख", "k": "हज़ार"},
}
_CURRENCY_WORDS = {"en": {"inr": "rupees", "usd": "dollars"}, "hi": {"inr": "रुपये", "usd": "डॉलर"}}


def _below_1000(n: int) -> str:
    parts = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append(f"{_ONES[hundreds]} hundred")
    if rest:
        if rest < 20:
            parts.append(_ONES[rest])
        else:
            tens, ones = divmod(rest, 10)
            parts.append(_TENS[tens] + (f" {_ONES[ones]}" if ones else ""))
    return " ".join(parts)


def _int_words_en(n: int) -> str:
    """Indian numbering: crore / lakh / thousand."""
    if n == 0:
        return "zero"
    if n >= 10**12:
        return str(n)
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    parts = []
    if crore:
        parts.append(f"{_int_words_en(crore)} crore")
    if lakh:
        parts.append(f"{_below_1000(lakh)} lakh")
    if thousand:
        parts.append(f"{_below_1000(thousand)} thousand")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


def _int_speech_hi(n: int) -> str:
    """Hindi: small numerals plus unit words, e.g. 1 करोड़ 50 लाख."""
    if n < 1000 or n >= 10**12:
        return str(n)
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    parts = []
    if crore:
        parts.append(f"{crore} करोड़")
    if lakh:
        parts.append(f"{lakh} लाख")
    if thousand:
        parts.append(f"{thousand} हज़ार")
    if n:
        parts.append(str(n))
    return " ".join(parts)


def _int_speech(n: int, lang: str) -> str:
    return _int_words_en(n) if lang == "en" else _int_speech_hi(n)


def _money(text: str, symbol_pattern: str, currency: str, lang: str) -> str:
    pattern = symbol_pattern + r"\s*(\d[\d,]*(?:\.\d+)?)\s*(crores|crore|cr|lakhs|lakh|lacs|lac|l|k)?\b"

    def repl(match: re.Match) -> str:
        full = match.group(1)
        raw = full.rstrip(",")
        trailing = "," * (len(full) - len(raw))
        unit = (match.group(2) or "").lower()
        clean = raw.replace(",", "")
        if unit:
            amount = f"{clean} {_UNIT_WORDS[lang][unit]}"
        elif "." in clean:
            amount = clean
        else:
            amount = _int_speech(int(clean), lang) if lang == "en" else _int_speech_hi(int(clean)) if int(clean) >= 1000 else clean
        return f"{amount} {_CURRENCY_WORDS[lang][currency]}{trailing}"

    return re.sub(pattern, repl, text, flags=re.IGNORECASE)


def _spell_phone(raw: str, lang: str) -> str:
    plus = raw.strip().startswith("+")
    digits = re.sub(r"\D", "", raw)
    groups = []
    if len(digits) > 10:
        groups.append(digits[: len(digits) - 10])
        digits = digits[-10:]
    groups += [digits[i:i + 5] for i in range(0, len(digits), 5)]
    words = [" ".join(_DIGIT_WORDS[lang][int(d)] for d in group) for group in groups]
    prefix = ("plus " if lang == "en" else "प्लस ") if plus else ""
    return prefix + ", ".join(words)


def make_speakable(text: str, lang: str = "en") -> str:
    """Rewrite currency, phone numbers, big numbers and abbreviations so TTS reads them naturally."""
    lang = "hi" if lang == "hi" else "en"

    # 1. Currency with a symbol/prefix: ₹15,00,000 | ₹1.25 Cr | Rs. 50 lakh | $450,000
    text = _money(text, r"(?:₹|\bRs\.?|\bINR\b)", "inr", lang)
    text = _money(text, r"\$", "usd", lang)

    # 2. "1.25 Cr" / "2 lakh" without a currency symbol
    def unit_repl(match: re.Match) -> str:
        return f"{match.group(1)} {_UNIT_WORDS[lang][match.group(2).lower()]}"

    text = re.sub(r"(\d+(?:\.\d+)?)\s*(crores|crore|cr|lakhs|lakh|lacs|lac)\b", unit_repl, text, flags=re.IGNORECASE)

    # 3. Phone numbers are read digit by digit
    def phone_repl(match: re.Match) -> str:
        raw = match.group(1)
        digit_count = len(re.sub(r"\D", "", raw))
        has_separator = bool(re.search(r"[\s\-]", raw.strip()))
        if digit_count >= 8 and (raw.strip().startswith("+") or has_separator or digit_count >= 10):
            return _spell_phone(raw, lang)
        return raw

    text = re.sub(r"(?<![\d.,])(\+?\d[\d\s\-]{6,}\d)(?![\d])", phone_repl, text)

    # 4. Remaining large plain numbers: 15000000 -> "one crore fifty lakh"
    def number_repl(match: re.Match) -> str:
        full = match.group(0)
        raw = full.rstrip(",")
        trailing = "," * (len(full) - len(raw))
        n = int(raw.replace(",", ""))
        if 1000 <= n < 10**12:
            return _int_speech(n, lang) + trailing
        return full

    text = re.sub(r"(?<![\w.])\d[\d,]{3,}(?!\w)", number_repl, text)

    # 5. Abbreviations
    if lang == "hi":
        text = re.sub(r"\bsq\.?\s?ft\.?\b", "वर्ग फुट", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBHK\b", "बी एच के", text)
        text = text.replace("24/7", "चौबीस घंटे")
    else:
        text = re.sub(r"\bsq\.?\s?ft\.?\b", "square feet", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBHK\b", "B H K", text)
        text = text.replace("24/7", "twenty four seven")
    text = text.replace("&", " and " if lang == "en" else " और ").replace("/-", "")
    return re.sub(r"\s+", " ", text).strip()


# =========================================================================== providers
def _audio_duration(path: Path, text: str) -> float:
    try:
        from moviepy import AudioFileClip

        with AudioFileClip(str(path)) as clip:
            if clip.duration and clip.duration > 0:
                return float(clip.duration)
    except Exception as exc:
        logger.warning("Could not read audio duration (%s); estimating.", type(exc).__name__)
    return max(1.5, len(text.split()) / 2.5)


class _ElevenError(Exception):
    pass


def _eleven_error_message(response: requests.Response) -> str:
    status = response.status_code
    try:
        payload = response.json()
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    except ValueError:
        detail = ""
    code = detail.get("status", "") if isinstance(detail, dict) else ""
    message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
    if code == "quota_exceeded":
        return "character quota exceeded"
    if status == 401:
        return "API key rejected"
    if status == 404 or code == "voice_not_found":
        return "voice ID not found for this account"
    if status == 402 or code in ("payment_required", "paid_plan_required"):
        return "this voice needs a paid ElevenLabs plan"
    if status == 429:
        return "rate limit or too many concurrent requests"
    return f"HTTP {status} {message[:120]}".strip()


def _make_eleven_synth(voice_id: str) -> Callable[[str, Path], None]:
    url = ELEVENLABS_URL.format(voice_id=voice_id)
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"}

    def synth(text: str, out: Path) -> None:
        body = {
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True},
        }
        last = "unknown error"
        for _ in range(2):
            try:
                response = requests.post(url, params={"output_format": "mp3_44100_128"}, headers=headers, json=body, timeout=60)
            except requests.RequestException as exc:
                last = f"network error ({type(exc).__name__})"
                continue
            if response.status_code == 200 and response.content:
                out.write_bytes(response.content)
                return
            last = _eleven_error_message(response)
            if response.status_code < 500:
                break  # client errors will not succeed on retry
        raise _ElevenError(last)

    return synth


def _make_gtts_synth(lang: str) -> Callable[[str, Path], None]:
    def synth(text: str, out: Path) -> None:
        from gtts import gTTS

        gtts_lang = "hi" if lang == "hi" else TTS_LANG
        tld = "co.in" if lang == "hi" else TTS_TLD
        last: Optional[Exception] = None
        for _ in range(2):
            try:
                try:
                    tts = gTTS(text=text, lang=gtts_lang, tld=tld, slow=False, timeout=20)
                except TypeError:
                    tts = gTTS(text=text, lang=gtts_lang, tld=tld, slow=False)
                tts.save(str(out))
                if out.exists() and out.stat().st_size > 0:
                    return
                raise RuntimeError("gTTS produced an empty file")
            except Exception as exc:
                last = exc
        raise last  # type: ignore[misc]

    return synth


def _run_provider(texts: list[str], audio_dir: Path, synth: Callable[[str, Path], None]):
    clips: list[NarrationClip] = []
    for index, text in enumerate(texts):
        out = audio_dir / f"scene_{index:02d}.mp3"
        try:
            synth(text, out)
            if not out.exists() or out.stat().st_size == 0:
                raise RuntimeError("empty audio file")
            clips.append(NarrationClip(str(out), _audio_duration(out, text)))
        except Exception as exc:
            logger.warning("TTS failed on scene %d: %s", index + 1, str(exc)[:200])
            return None, (str(exc) or type(exc).__name__)[:160]
    return clips, None


# =========================================================================== public API
def generate_narration(
    scenes,
    audio_dir: Path,
    voice_language: str = "en",
    voice_gender: str = "female",
) -> tuple[list[Optional[NarrationClip]], Optional[str]]:
    """Returns (clips aligned with scenes, warning). Clips are all None when narration is unavailable."""
    none_list: list[Optional[NarrationClip]] = [None] * len(scenes)
    if not TTS_ENABLED:
        return none_list, "Narration is disabled (TTS_ENABLED=false); the video has no voice-over."

    lang = "hi" if voice_language == "hi" else "en"
    gender = "male" if voice_gender == "male" else "female"
    profile = f"{lang}-{gender}"
    label = f"{'Hindi' if lang == 'hi' else 'English'} {gender}"
    audio_dir.mkdir(parents=True, exist_ok=True)
    texts = [make_speakable(scene.voiceover, lang) for scene in scenes]

    warning: Optional[str]
    if ELEVENLABS_API_KEY and ELEVENLABS_VOICES.get(profile):
        clips, error = _run_provider(texts, audio_dir, _make_eleven_synth(ELEVENLABS_VOICES[profile]))
        if clips:
            return clips, None
        warning = f"ElevenLabs narration ({label}) failed: {error}. The basic Google voice was used instead."
    elif ELEVENLABS_API_KEY:
        warning = f"No ElevenLabs voice ID is set for '{profile}'. The basic Google voice was used instead."
    else:
        warning = "ELEVENLABS_API_KEY is not configured, so the basic Google voice was used (the male/female choice does not apply)."

    clips, error = _run_provider(texts, audio_dir, _make_gtts_synth(lang))
    if clips:
        return clips, warning
    return none_list, f"{warning} Google TTS also failed ({error}); the video was rendered without voice-over."