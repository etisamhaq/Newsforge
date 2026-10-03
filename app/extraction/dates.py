from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import struct_time

from dateutil import parser as dateparser

MIN_DATE = datetime(1990, 1, 1, tzinfo=timezone.utc)


def parse_date(value) -> datetime | None:
    """Parse a date-ish value into an aware UTC datetime; reject implausible values."""
    if value is None or value == "":
        return None
    dt: datetime | None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, struct_time):
        dt = datetime(*value[:6], tzinfo=timezone.utc)
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text or len(text) > 100:
            return None
        try:
            dt = dateparser.parse(text, fuzzy=False)
        except (ValueError, OverflowError, TypeError):
            try:
                dt = dateparser.parse(text, fuzzy=True)
            except (ValueError, OverflowError, TypeError):
                return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt < MIN_DATE or dt > datetime.now(timezone.utc) + timedelta(days=2):
        return None
    return dt
