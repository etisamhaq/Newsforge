from __future__ import annotations

import re

_LANG = re.compile(r"^[a-z]{2,3}$")


def normalize_language(value: str | None) -> str | None:
    """'en-US' / 'en_GB' / 'English' -> 'en'."""
    if not value:
        return None
    v = value.strip().lower().replace("_", "-").split("-", 1)[0]
    names = {"english": "en", "german": "de", "french": "fr", "spanish": "es", "italian": "it",
             "portuguese": "pt", "dutch": "nl", "arabic": "ar", "urdu": "ur", "chinese": "zh",
             "japanese": "ja", "russian": "ru", "hindi": "hi", "turkish": "tr"}
    v = names.get(v, v)
    return v if _LANG.match(v) else None


def detect_language(text: str | None) -> str | None:
    if not text or len(text) < 50:
        return None
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return normalize_language(detect(text[:5000]))
    except Exception:  # noqa: BLE001 - detection is best-effort
        return None
