from __future__ import annotations

import html
import re
from typing import Any

_WS = re.compile(r"[ \t\r\f\v ]+")
_MULTI_NL = re.compile(r"\n{3,}")
_TAGS = re.compile(r"<[^>]+>")


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = " ".join(str(v) for v in value if v)
    text = html.unescape(str(value))
    if "<" in text and ">" in text:
        text = _TAGS.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    return text or None


def clean_body(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(value)
    lines = [_WS.sub(" ", ln).strip() for ln in text.splitlines()]
    text = "\n".join(lines)
    text = _MULTI_NL.sub("\n\n", text).strip()
    return text or None


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def split_keywords(value: Any) -> list[str]:
    out: list[str] = []
    for v in as_list(value):
        if isinstance(v, str):
            out.extend(p.strip() for p in re.split(r"[,;|]", v))
        elif isinstance(v, dict) and v.get("name"):
            out.append(str(v["name"]).strip())
    seen: dict[str, None] = {}
    for t in out:
        if t and len(t) <= 100:
            seen.setdefault(t, None)
    return list(seen)[:50]


def clean_authors(values: list[str]) -> list[str]:
    out: dict[str, None] = {}
    for v in values:
        v = clean_text(v)
        if not v:
            continue
        v = re.sub(r"^(by|von|par|por|di)\s+", "", v, flags=re.I).strip()
        for part in re.split(r"\s+(?:and|&|und|et|y)\s+|,\s*(?=[A-Z])", v):
            part = part.strip(" ,;|")
            if 2 <= len(part) <= 100 and not part.lower().startswith(("http", "www.")):
                out.setdefault(part, None)
    return list(out)[:20]
