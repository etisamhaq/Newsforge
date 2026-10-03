"""Per-person access: Supabase token verification, members, roles, and the API-key fallback."""

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from tests.auth_fixtures import SOURCE, bearer, invite

API = {"X-API-Key": "machine-key"}


async def original_workspace(client) -> int:
    """The original workspace (API-key requests create it on an empty database)."""
    return (await client.get("/api/v1/workspace", headers=API)).json()["workspace"]["id"]


async def test_open_mode_without_credentials(client):
    me = (await client.get("/api/v1/me")).json()
    assert me["via"] == "open" and me["email"] is None


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
        lambda k: jwt.encode({"sub": "x"}, "secret-key-that-is-long-enough-123", algorithm="HS256", headers={"kid": k.kid}),
    ],
)
async def test_rejects_bad_tokens(auth_client, keys, make_token):
    r = await auth_client.get("/api/v1/sources", headers=bearer(make_token(keys)))
    assert r.status_code == 401


async def test_new_person_gets_their_own_workspace(auth_client, keys):
    token = bearer(keys.token(sub="new-id", email="New.Person@example.com"))
    me = (await auth_client.get("/api/v1/me", headers=token)).json()
    assert me["email"] == "new.person@example.com"
    assert len(me["workspaces"]) == 1
    ws = me["workspaces"][0]
    assert ws["role"] == "admin" and ws["owned"] is True and ws["name"] == "new person's workspace"
    # Signing in again doesn't create another one.
    me2 = (await auth_client.get("/api/v1/me", headers=token)).json()
    assert [w["id"] for w in me2["workspaces"]] == [ws["id"]]
    # They can use it straight away.
    assert (await auth_client.post("/api/v1/sources", json=SOURCE, headers=token)).status_code == 201


async def test_admin_email_joins_the_original_workspace(auth_client, keys):
    original = await original_workspace(auth_client)
    me = (await auth_client.get("/api/v1/me", headers=bearer(keys.token(sub="boss-id", email="Boss@Example.com")))).json()
    assert me["workspaces"] == [{"id": original, "name": "Newsforge", "role": "admin", "owned": False}]


async def test_invitation_links_on_first_sign_in(auth_client, keys):
    original = await original_workspace(auth_client)
    await invite(auth_client, "ana@example.com", "editor")
    me = (await auth_client.get("/api/v1/me", headers=bearer(keys.token(sub="ana-id", email="ana@example.com")))).json()
    assert [(w["id"], w["role"]) for w in me["workspaces"]] == [(original, "editor")]  # no extra empty workspace
    members = (await auth_client.get("/api/v1/members", headers=API)).json()
    assert members[0]["joined"] is True and members[0]["invited_by"] == "API key"
    # Another account using the same email can't take over Ana's seat.
    impostor = bearer(keys.token(sub="impostor", email="ana@example.com"))
    r = await auth_client.get("/api/v1/sources", headers={**impostor, "X-Workspace-Id": str(original)})
    assert r.status_code == 403


async def test_role_permissions(auth_client, keys):
    await invite(auth_client, "v@example.com", "viewer")
    await invite(auth_client, "e@example.com", "editor")
    viewer = bearer(keys.token(sub="v", email="v@example.com"))
    editor = bearer(keys.token(sub="e", email="e@example.com"))

    assert (await auth_client.get("/api/v1/sources", headers=viewer)).status_code == 200
    assert (await auth_client.get("/api/v1/stats", headers=viewer)).status_code == 200
    r = await auth_client.post("/api/v1/sources", json=SOURCE, headers=viewer)
    assert r.status_code == 403 and "editor" in r.json()["detail"]
    assert (await auth_client.post("/api/v1/debug/extract", json={"url": "https://a.com/x", "html": "<p>x</p>"}, headers=viewer)).status_code == 403

    src = (await auth_client.post("/api/v1/sources", json=SOURCE, headers=editor)).json()
    assert (await auth_client.patch(f"/api/v1/sources/{src['id']}", json={"max_pages": 5}, headers=editor)).status_code == 200
    assert (await auth_client.delete(f"/api/v1/sources/{src['id']}", headers=editor)).status_code == 403
    assert (await auth_client.get("/api/v1/members", headers=editor)).status_code == 403
    assert (await auth_client.delete(f"/api/v1/sources/{src['id']}", headers=API)).status_code == 204


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
    await original_workspace(auth_client)
    await auth_client.get("/api/v1/me", headers=boss)  # joins the original workspace as admin
    m = (await auth_client.post("/api/v1/members", json={"email": " New@Example.com ", "role": "viewer"}, headers=boss)).json()
    assert m["email"] == "new@example.com" and m["joined"] is False and m["invited_by"] == "boss@example.com"
    assert (await auth_client.post("/api/v1/members", json={"email": "new@example.com"}, headers=boss)).status_code == 409
    assert (await auth_client.post("/api/v1/members", json={"email": "not-an-email"}, headers=boss)).status_code == 422
    assert (await auth_client.patch(f"/api/v1/members/{m['id']}", json={"role": "admin"}, headers=boss)).json()["role"] == "admin"

    members = (await auth_client.get("/api/v1/members", headers=boss)).json()
    boss_id = next(x["id"] for x in members if x["email"] == "boss@example.com")
    assert (await auth_client.patch(f"/api/v1/members/{m['id']}", json={"role": "editor"}, headers=boss)).status_code == 200
    assert (await auth_client.patch(f"/api/v1/members/{boss_id}", json={"role": "viewer"}, headers=boss)).status_code == 409
    assert (await auth_client.delete(f"/api/v1/members/{boss_id}", headers=boss)).status_code == 409
    assert (await auth_client.delete(f"/api/v1/members/{m['id']}", headers=boss)).status_code == 204


async def test_removed_member_loses_access(auth_client, keys):
    original = await original_workspace(auth_client)
    m = await invite(auth_client, "temp@example.com", "viewer")
    token = {**bearer(keys.token(sub="t", email="temp@example.com")), "X-Workspace-Id": str(original)}
    assert (await auth_client.get("/api/v1/sources", headers=token)).status_code == 200
    await auth_client.delete(f"/api/v1/members/{m['id']}", headers=API)
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
