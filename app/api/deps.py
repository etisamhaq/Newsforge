from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings
from app.db.session import get_session

__all__ = ["get_session", "require_api_key"]


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API key")
