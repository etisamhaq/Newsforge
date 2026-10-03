"""Per-person access: Supabase token verification, members, roles, and the API-key fallback."""

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


async def test_open_mode_without_credentials(client):
    assert (await client.get("/api/v1/me")).json() == {"email": None, "role": "admin", "via": "open"}


async def test_requires_sign_in(auth_client):
    r = await auth_client.get("/api/v1/sources")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert (await auth_client.get("/health")).status_code == 200


@pytest.mark.parametrize(
    "make_token",
    [
        lambda k: k.token(exp_in=-120),  # expired
        lambda k: k.token(aud="other"),  # wrong audience
        lambda k: k.token(iss="https://evil.supabase.co/auth/v1"),  # wrong issuer
        lambda k: k.token(key=ec.generate_private_key(ec.SECP256R1())),  # forged signature
        lambda k: k.token(role="anon"),  # anon key, not a person
        lambda k: "not-a-jwt",
        lambda k: jwt.encode({"sub": "x"}, "secret", algorithm="HS256", headers={"kid": k.kid}),  # alg confusion
    ],
)
async def test_rejects_bad_tokens(auth_client, keys, make_token):
    r = await auth_client.get("/api/v1/sources", headers=bearer(make_token(keys)))
    assert r.status_code == 401


async def test_unknown_person_is_forbidden(auth_client, keys):
    r = await auth_client.get("/api/v1/me", headers=bearer(keys.token(email="stranger@example.com")))
    assert r.status_code == 403
    assert "Ask an admin" in r.json()["detail"]


async def test_admin_email_bootstraps_first_admin(auth_client, keys):
    token = keys.token(sub="boss-id", email="Boss@Example.com")
    me = (await auth_client.get("/api/v1/me", headers=bearer(token))).json()
    assert me == {"email": "boss@example.com", "role": "admin", "via": "user"}
    members = (await auth_client.get("/api/v1/members", headers=bearer(token))).json()
    assert members[0]["email"] == "boss@example.com" and members[0]["joined"] is True


async def test_invitation_links_on_first_sign_in(auth_client, keys):
    await invite(auth_client, "ana@example.com", "editor")
    r = await auth_client.get("/api/v1/me", headers=bearer(keys.token(sub="ana-id", email="ana@example.com")))
    assert r.json()["role"] == "editor"
    members = (await auth_client.get("/api/v1/members", headers={"X-API-Key": "machine-key"})).json()
    assert members[0]["joined"] is True and members[0]["invited_by"] == "API key"
    # A different account later signing up with the same email can't take over the membership.
    r = await auth_client.get("/api/v1/me", headers=bearer(keys.token(sub="impostor", email="ana@example.com")))
    assert r.status_code == 403


async def test_role_permissions(auth_client, keys):
    await invite(auth_client, "v@example.com", "viewer")
    await invite(auth_client, "e@example.com", "editor")
    viewer = bearer(keys.token(sub="v", email="v@example.com"))
    editor = bearer(keys.token(sub="e", email="e@example.com"))
    admin = {"X-API-Key": "machine-key"}

    assert (await auth_client.get("/api/v1/sources", headers=viewer)).status_code == 200
    assert (await auth_client.get("/api/v1/stats", headers=viewer)).status_code == 200
    r = await auth_client.post("/api/v1/sources", json=SOURCE, headers=viewer)
    assert r.status_code == 403 and "editor" in r.json()["detail"]
    assert (await auth_client.post("/api/v1/debug/extract", json={"url": "https://a.com/x", "html": "<p>x</p>"}, headers=viewer)).status_code == 403

    src = (await auth_client.post("/api/v1/sources", json=SOURCE, headers=editor)).json()
    assert (await auth_client.patch(f"/api/v1/sources/{src['id']}", json={"max_pages": 5}, headers=editor)).status_code == 200
    assert (await auth_client.delete(f"/api/v1/sources/{src['id']}", headers=editor)).status_code == 403
    assert (await auth_client.get("/api/v1/members", headers=editor)).status_code == 403
    assert (await auth_client.delete(f"/api/v1/sources/{src['id']}", headers=admin)).status_code == 204


async def test_crawl_records_who_started_it(auth_client, keys):
    from app.api.routes.crawls import get_dispatcher

    app = auth_client._transport.app

    async def noop(job_id):
        return None

    app.dependency_overrides[get_dispatcher] = lambda: noop
    await invite(auth_client, "e@example.com", "editor")
    editor = bearer(keys.token(sub="e", email="e@example.com"))
    src = (await auth_client.post("/api/v1/sources", json=SOURCE, headers=editor)).json()
    job = (await auth_client.post(f"/api/v1/sources/{src['id']}/crawl", headers=editor)).json()
    assert job["triggered_by"] == "e@example.com"
    app.dependency_overrides.clear()


async def test_team_management_and_last_admin_guard(auth_client, keys):
    boss = bearer(keys.token(sub="boss-id", email="boss@example.com"))
    await auth_client.get("/api/v1/me", headers=boss)  # bootstrap admin
    m = (await auth_client.post("/api/v1/members", json={"email": " New@Example.com ", "role": "viewer"}, headers=boss)).json()
    assert m["email"] == "new@example.com" and m["joined"] is False and m["invited_by"] == "boss@example.com"
    assert (await auth_client.post("/api/v1/members", json={"email": "new@example.com"}, headers=boss)).status_code == 409
    assert (await auth_client.post("/api/v1/members", json={"email": "not-an-email"}, headers=boss)).status_code == 422
    assert (await auth_client.patch(f"/api/v1/members/{m['id']}", json={"role": "admin"}, headers=boss)).json()["role"] == "admin"

    members = (await auth_client.get("/api/v1/members", headers=boss)).json()
    boss_id = next(x["id"] for x in members if x["email"] == "boss@example.com")
    # Two admins: demoting one is fine; then the remaining admin can't be demoted or removed.
    assert (await auth_client.patch(f"/api/v1/members/{m['id']}", json={"role": "editor"}, headers=boss)).status_code == 200
    assert (await auth_client.patch(f"/api/v1/members/{boss_id}", json={"role": "viewer"}, headers=boss)).status_code == 409
    assert (await auth_client.delete(f"/api/v1/members/{boss_id}", headers=boss)).status_code == 409
    assert (await auth_client.delete(f"/api/v1/members/{m['id']}", headers=boss)).status_code == 204


async def test_removed_member_loses_access(auth_client, keys):
    m = await invite(auth_client, "temp@example.com", "viewer")
    token = bearer(keys.token(sub="t", email="temp@example.com"))
    assert (await auth_client.get("/api/v1/sources", headers=token)).status_code == 200
    await auth_client.delete(f"/api/v1/members/{m['id']}", headers={"X-API-Key": "machine-key"})
    assert (await auth_client.get("/api/v1/sources", headers=token)).status_code == 403


async def test_api_key_still_works_and_wrong_key_fails(auth_client):
    assert (await auth_client.get("/api/v1/me", headers={"X-API-Key": "machine-key"})).json()["via"] == "api_key"
    assert (await auth_client.get("/api/v1/me", headers={"X-API-Key": "nope"})).status_code == 401


async def test_jwks_cached_and_refreshed_on_key_rotation(auth_client, keys):
    await invite(auth_client, "ana@example.com", "viewer")
    for _ in range(3):
        assert (await auth_client.get("/api/v1/me", headers=bearer(keys.token(sub="a")))).status_code == 200
    assert keys.jwks_calls == 1
    # Supabase rotates its signing key: tokens with the new kid trigger one refresh.
    keys.private = ec.generate_private_key(ec.SECP256R1())
    keys.kid = "kid-2"
    from app import auth as auth_module

    auth_module.get_verifier()._fetched_at -= 60  # past the anti-hammering window
    assert (await auth_client.get("/api/v1/me", headers=bearer(keys.token(sub="a")))).status_code == 200
    assert keys.jwks_calls == 2
