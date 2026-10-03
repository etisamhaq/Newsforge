"""Workspaces: data isolation between teams, switching, lifecycle, and usage limits."""

import pytest
from sqlalchemy import func, select

from app.api.routes.crawls import get_dispatcher
from app.config import get_settings
from app.crawler.engine import CrawlEngine, CrawlQuota
from app.db.models import Article, Workspace
from app.db.session import get_sessionmaker
from app.services.crawl import dispatch_due_sources
from app.services.quotas import add_usage
from tests.auth_fixtures import SOURCE, bearer
from tests.helpers import make_fetcher
from tests.test_engine import HOST, build_site, make_source


@pytest.fixture
async def users(auth_client, keys):
    """Two unrelated people; each gets their own workspace on first sign-in."""
    ana = bearer(keys.token(sub="ana", email="ana@a.com"))
    bob = bearer(keys.token(sub="bob", email="bob@b.com"))
    for h in (ana, bob):
        await auth_client.get("/api/v1/me", headers=h)
    return ana, bob


async def ws_id(client, headers) -> int:
    return (await client.get("/api/v1/workspace", headers=headers)).json()["workspace"]["id"]


@pytest.fixture
def inline_crawls(auth_client):
    from app.services.crawl import run_job

    async def inline(job_id: int) -> None:
        await run_job(job_id, fetcher=make_fetcher(build_site()))

    auth_client._transport.app.dependency_overrides[get_dispatcher] = lambda: inline
    yield
    auth_client._transport.app.dependency_overrides.clear()


async def test_teams_cannot_see_each_others_data(auth_client, users, inline_crawls):
    ana, bob = users
    src = (await auth_client.post("/api/v1/sources", json=SOURCE, headers=ana)).json()
    job = (await auth_client.post(f"/api/v1/sources/{src['id']}/crawl", headers=ana)).json()
    articles = (await auth_client.get("/api/v1/articles", headers=ana)).json()
    assert articles["total"] == 3
    art = articles["items"][0]["id"]

    # Bob sees none of it, by listing or by guessing ids.
    assert (await auth_client.get("/api/v1/sources", headers=bob)).json()["total"] == 0
    assert (await auth_client.get("/api/v1/articles", headers=bob)).json()["total"] == 0
    assert (await auth_client.get("/api/v1/articles", headers=bob, params={"q": "transit"})).json()["total"] == 0
    assert (await auth_client.get("/api/v1/crawls", headers=bob)).json()["total"] == 0
    for path in (f"/sources/{src['id']}", f"/crawls/{job['id']}", f"/articles/{art}", f"/articles/{art}/duplicates", f"/articles/{art}/raw"):
        assert (await auth_client.get(f"/api/v1{path}", headers=bob)).status_code == 404, path
    stats = (await auth_client.get("/api/v1/stats", headers=bob)).json()
    assert stats["totals"]["articles"] == 0 and stats["sources"] == []
    # ...and can't change it.
    assert (await auth_client.patch(f"/api/v1/sources/{src['id']}", json={"enabled": False}, headers=bob)).status_code == 404
    assert (await auth_client.delete(f"/api/v1/sources/{src['id']}", headers=bob)).status_code == 404
    assert (await auth_client.post(f"/api/v1/sources/{src['id']}/crawl", headers=bob)).status_code == 404
    assert (await auth_client.post(f"/api/v1/crawls/{job['id']}/cancel", headers=bob)).status_code == 404
    # Naming Ana's workspace explicitly doesn't help either.
    other = {**bob, "X-Workspace-Id": str(await ws_id(auth_client, ana))}
    assert (await auth_client.get("/api/v1/sources", headers=other)).status_code == 403


async def test_same_story_is_collected_separately_per_workspace(auth_client, users, inline_crawls):
    """Pages and dedup are per workspace: one team's crawl never hides a story from another."""
    ana, bob = users
    for h in (ana, bob):
        src = (await auth_client.post("/api/v1/sources", json=SOURCE, headers=h)).json()
        await auth_client.post(f"/api/v1/sources/{src['id']}/crawl", headers=h)
        assert (await auth_client.get("/api/v1/articles", headers=h)).json()["total"] == 3
    # Same source name is fine in different workspaces, but not twice in one.
    assert (await auth_client.post("/api/v1/sources", json=SOURCE, headers=ana)).status_code == 409


async def test_switching_between_workspaces(auth_client, users):
    ana, bob = users
    bob_ws = await ws_id(auth_client, bob)
    await auth_client.post("/api/v1/members", json={"email": "ana@a.com", "role": "editor"}, headers=bob)
    me = (await auth_client.get("/api/v1/me", headers=ana)).json()
    assert {(w["role"], w["owned"]) for w in me["workspaces"]} == {("admin", True), ("editor", False)}

    in_bob = {**ana, "X-Workspace-Id": str(bob_ws)}
    assert (await auth_client.post("/api/v1/sources", json=SOURCE, headers=in_bob)).status_code == 201
    assert (await auth_client.get("/api/v1/sources", headers=in_bob)).json()["total"] == 1
    assert (await auth_client.get("/api/v1/sources", headers=ana)).json()["total"] == 0  # her own workspace
    assert (await auth_client.get("/api/v1/members", headers=in_bob)).status_code == 403  # editor there, not admin
    assert (await auth_client.get("/api/v1/sources", headers={**ana, "X-Workspace-Id": "nope"})).status_code == 400


async def test_create_rename_and_delete_workspace(auth_client, users, monkeypatch):
    ana, _ = users
    monkeypatch.setattr(get_settings(), "max_owned_workspaces", 2)
    ws = (await auth_client.post("/api/v1/workspaces", json={"name": "  Side   project "}, headers=ana)).json()
    assert ws == {"id": ws["id"], "name": "Side project", "role": "admin", "owned": True}
    r = await auth_client.post("/api/v1/workspaces", json={"name": "Third"}, headers=ana)
    assert r.status_code == 429 and "up to 2" in r.json()["detail"]

    h = {**ana, "X-Workspace-Id": str(ws["id"])}
    assert (await auth_client.patch("/api/v1/workspace", json={"name": "Renamed"}, headers=h)).json()["name"] == "Renamed"
    await auth_client.post("/api/v1/sources", json=SOURCE, headers=h)
    r = await auth_client.request("DELETE", "/api/v1/workspace", json={"confirm_name": "wrong"}, headers=h)
    assert r.status_code == 422
    r = await auth_client.request("DELETE", "/api/v1/workspace", json={"confirm_name": "Renamed"}, headers=h)
    assert r.status_code == 204
    names = [w["name"] for w in (await auth_client.get("/api/v1/me", headers=ana)).json()["workspaces"]]
    assert "Renamed" not in names
    assert (await auth_client.get("/api/v1/sources", headers=h)).status_code == 403  # gone with its data


async def test_source_limits(auth_client, users, session):
    ana, _ = users
    ws = await session.get(Workspace, await ws_id(auth_client, ana))
    ws.max_sources = 1
    await session.commit()
    r = await auth_client.post("/api/v1/sources", json={**SOURCE, "max_pages": 500}, headers=ana)
    assert r.status_code == 422 and "200 pages" in str(r.json()["detail"])
    r = await auth_client.post("/api/v1/sources", json={**SOURCE, "crawl_interval_minutes": 10}, headers=ana)
    assert r.status_code == 422 and "every 30 minutes" in str(r.json()["detail"])
    assert (await auth_client.post("/api/v1/sources", json=SOURCE, headers=ana)).status_code == 201
    r = await auth_client.post("/api/v1/sources", json={**SOURCE, "name": "Second"}, headers=ana)
    assert r.status_code == 429 and "up to 1 sources" in r.json()["detail"]


async def test_crawl_limits(auth_client, users, session):
    ana, _ = users
    app = auth_client._transport.app

    async def noop(job_id):
        return None

    app.dependency_overrides[get_dispatcher] = lambda: noop
    try:
        wid = await ws_id(auth_client, ana)
        ids = []
        for name in ("One", "Two", "Three"):
            ids.append((await auth_client.post("/api/v1/sources", json={**SOURCE, "name": name}, headers=ana)).json()["id"])
        assert (await auth_client.post(f"/api/v1/sources/{ids[0]}/crawl", headers=ana)).status_code == 202
        assert (await auth_client.post(f"/api/v1/sources/{ids[1]}/crawl", headers=ana)).status_code == 202
        r = await auth_client.post(f"/api/v1/sources/{ids[2]}/crawl", headers=ana)
        assert r.status_code == 429 and "2 crawls at once" in r.json()["detail"]

        # Use up the day's pages: no new crawls, no debugger fetches.
        await add_usage(session, wid, pages=500)
        await session.commit()
        for jid in (1, 2):
            await auth_client.post(f"/api/v1/crawls/{jid}/cancel", headers=ana)
        r = await auth_client.post(f"/api/v1/sources/{ids[2]}/crawl", headers=ana)
        assert r.status_code == 429 and "500 page fetches" in r.json()["detail"]
        r = await auth_client.post("/api/v1/debug/extract", json={"url": f"{HOST}/x"}, headers=ana)
        assert r.status_code == 429

        usage = (await auth_client.get("/api/v1/workspace", headers=ana)).json()
        assert usage["today"]["pages"] == 500 and usage["today"]["crawls"] == 2
        assert usage["limits"]["max_pages_per_day"] == 500 and usage["counts"]["sources"] == 3
    finally:
        app.dependency_overrides.clear()


async def test_member_limit(auth_client, users, session):
    ana, _ = users
    ws = await session.get(Workspace, await ws_id(auth_client, ana))
    ws.max_members = 2
    await session.commit()
    assert (await auth_client.post("/api/v1/members", json={"email": "x@a.com"}, headers=ana)).status_code == 201
    r = await auth_client.post("/api/v1/members", json={"email": "y@a.com"}, headers=ana)
    assert r.status_code == 429


async def test_engine_stops_at_daily_page_quota(session):
    source = await make_source(session, feed_urls=[f"{HOST}/feed"], discover_links=False)
    fetcher = make_fetcher(build_site())
    quota = CrawlQuota(pages_left=2, llm_calls_left=0)
    stats = await CrawlEngine(get_sessionmaker(), fetcher, quota=quota).crawl(source)
    await fetcher.aclose()
    assert stats.stopped_reason == "daily_quota"
    assert stats.fetches == 2 and quota.pages_left == 0


async def test_engine_caps_pages_per_crawl(session):
    source = await make_source(session, max_pages=50, discover_links=False, feed_urls=[f"{HOST}/feed"])
    fetcher = make_fetcher(build_site())
    stats = await CrawlEngine(get_sessionmaker(), fetcher, quota=CrawlQuota(max_pages_per_crawl=1)).crawl(source)
    await fetcher.aclose()
    assert stats.pages_fetched == 1 and stats.stopped_reason == "max_pages"


async def test_scheduler_skips_workspaces_over_their_limit(session):
    source = await make_source(session)
    await add_usage(session, source.workspace_id, pages=10_000)
    await session.commit()
    assert await dispatch_due_sources() == []
    # A fresh day (no usage) is dispatched normally.
    other = Workspace(name="Other")
    session.add(other)
    await session.flush()
    await make_source(session, name="Fresh", workspace_id=other.id)
    await session.commit()
    assert len(await dispatch_due_sources()) == 1
    count = (await session.execute(select(func.count(Article.id)))).scalar_one()
    assert count == 0
