"""Content fingerprints: exact (sha256 of normalized text) and near-duplicate (64-bit SimHash)."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
MASK64 = (1 << 64) - 1


def normalize_for_hash(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = _NON_WORD.sub(" ", text)
    return _WS.sub(" ", text).strip()


def content_hash(text: str | None) -> str | None:
    if not text:
        return None
    norm = normalize_for_hash(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest() if norm else None


def _h64(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")


def simhash(text: str | None, shingle: int = 3) -> int | None:
    """Unsigned 64-bit SimHash over word shingles."""
    if not text:
        return None
    words = normalize_for_hash(text).split()
    if len(words) < shingle:
        return None
    weights = [0] * 64
    for i in range(len(words) - shingle + 1):
        h = _h64(" ".join(words[i : i + shingle]))
        for bit in range(64):
            weights[bit] += 1 if (h >> bit) & 1 else -1
    value = 0
    for bit in range(64):
        if weights[bit] > 0:
            value |= 1 << bit
    return value


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & MASK64).count("1")


def to_signed(value: int) -> int:
    """Store unsigned 64-bit values in a signed BIGINT column."""
    return value - (1 << 64) if value >= (1 << 63) else value


def to_unsigned(value: int) -> int:
    return value & MASK64


def bands(value: int) -> tuple[int, int, int, int]:
    """Split into 4 x 16-bit bands. Two hashes within distance <= 3 share at least one band."""
    return tuple((value >> (16 * i)) & 0xFFFF for i in range(4))  # type: ignore[return-value]
