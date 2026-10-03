"""Shared fixtures for signed-in requests: a real ES256 key pair served as a mock Supabase JWKS."""

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import TokenVerifier, set_verifier
from app.config import get_settings

SUPABASE = "https://proj.supabase.co"
ISSUER = f"{SUPABASE}/auth/v1"
SOURCE = {"name": "Example", "base_url": "https://news.example.com/", "min_delay_seconds": 0}


class Keys:
    def __init__(self):
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.kid = "kid-1"
        self.jwks_calls = 0

    def jwks(self) -> dict:
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(self.private.public_key()))
        jwk.update(kid=self.kid, alg="ES256", use="sig")
        return {"keys": [jwk]}

    def token(self, sub="user-1", email="ana@example.com", *, exp_in=3600, aud="authenticated", iss=ISSUER,
              role="authenticated", key=None, kid=None) -> str:
        now = int(time.time())
        claims = {"sub": sub, "email": email, "aud": aud, "iss": iss, "role": role, "iat": now, "exp": now + exp_in}
        return jwt.encode(claims, key or self.private, algorithm="ES256", headers={"kid": kid or self.kid})


@pytest.fixture
def keys():
    return Keys()


@pytest.fixture
async def auth_client(client, keys, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "supabase_url", SUPABASE)
    monkeypatch.setattr(settings, "api_key", "machine-key")
    monkeypatch.setattr(settings, "admin_emails", ["boss@example.com"])

    def jwks_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{ISSUER}/.well-known/jwks.json"
        keys.jwks_calls += 1
        return httpx.Response(200, json=keys.jwks())

    set_verifier(TokenVerifier(settings, transport=httpx.MockTransport(jwks_handler)))
    yield client
    set_verifier(None)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def invite(client, email: str, role: str) -> dict:
    r = await client.post("/api/v1/members", json={"email": email, "role": role}, headers={"X-API-Key": "machine-key"})
    assert r.status_code == 201, r.text
    return r.json()


