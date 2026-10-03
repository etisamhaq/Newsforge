import pytest

from app.api.routes.crawls import get_dispatcher
from app.api.routes.debug import get_fetcher
from app.services.crawl import run_job
from tests.conftest import fixture_text
from tests.helpers import make_fetcher
from tests.test_engine import HOST, build_site

SOURCE = {"name": "Example", "base_url": f"{HOST}/", "min_delay_seconds": 0, "render_mode": "never", "max_depth": 2}


@pytest.fixture
async def api(client):
    """Client whose crawls run inline against the simulated site, and debug fetches hit it too."""
    app = client._transport.app

    async def inline_dispatch(job_id: int) -> None:
        await run_job(job_id, fetcher=make_fetcher(build_site()))

    async def fake_fetcher():
        f = make_fetcher(build_site())
        yield f
        await f.aclose()

    app.dependency_overrides[get_dispatcher] = lambda: inline_dispatch
    app.dependency_overrides[get_fetcher] = fake_fetcher
    yield client
    app.dependency_overrides.clear()


async def test_source_crud(api):
    r = await api.post("/api/v1/sources", json=SOURCE)
    assert r.status_code == 201, r.text
    src = r.json()
    assert src["domain"] == "news.example.com" and src["allowed_domains"] == ["news.example.com"]
    assert (await api.post("/api/v1/sources", json=SOURCE)).status_code == 409

    r = await api.patch(f"/api/v1/sources/{src['id']}", json={"max_pages": 10, "enabled": False})
    assert r.json()["max_pages"] == 10 and r.json()["enabled"] is False
    listing = (await api.get("/api/v1/sources", params={"enabled": False})).json()
    assert listing["total"] == 1

    assert (await api.delete(f"/api/v1/sources/{src['id']}")).status_code == 204
    assert (await api.get(f"/api/v1/sources/{src['id']}")).status_code == 404


@pytest.mark.parametrize(
    "patch",
    [
        {"base_url": "http://localhost:8000/"},
        {"base_url": "file:///etc/passwd"},
        {"feed_urls": ["http://10.0.0.1/feed"]},
        {"exclude_patterns": ["(unclosed"]},
        {"max_pages": 0},
        {"crawl_interval_minutes": 1},
    ],
)
async def test_source_validation(api, patch):
    r = await api.post("/api/v1/sources", json={**SOURCE, **patch})
    assert r.status_code == 422


async def test_crawl_and_query_articles(api):
    src = (await api.post("/api/v1/sources", json=SOURCE)).json()
    r = await api.post(f"/api/v1/sources/{src['id']}/crawl")
    assert r.status_code == 202, r.text
    job = (await api.get(f"/api/v1/crawls/{r.json()['id']}")).json()
    assert job["status"] == "succeeded" and job["articles_new"] == 3

    page = (await api.get("/api/v1/articles")).json()
    assert page["total"] == 3
    assert page["items"][0]["published_at"] is not None
    assert "body" not in page["items"][0]

    hits = (await api.get("/api/v1/articles", params={"q": "budgets", "sort": "relevance"})).json()
    assert hits["total"] == 1 and hits["items"][0]["title"] == "Budget vote delayed"
    assert (await api.get("/api/v1/articles", params={"q": "nonexistentword"})).json()["total"] == 0
    assert (await api.get("/api/v1/articles", params={"language": "en", "since": "2024-01-01T00:00:00Z"})).json()["total"] == 3
    assert (await api.get("/api/v1/articles", params={"source_id": src["id"] + 99})).json()["total"] == 0

    detail = (await api.get(f"/api/v1/articles/{page['items'][0]['id']}")).json()
    assert detail["body"] and detail["extra"]["field_sources"]
    assert (await api.get(f"/api/v1/articles/{detail['id']}/raw")).status_code == 404

    jobs = (await api.get("/api/v1/crawls", params={"source_id": src["id"]})).json()
    assert jobs["total"] == 1


async def test_raw_html_endpoint(api):
    src = (await api.post("/api/v1/sources", json={**SOURCE, "store_raw_html": True})).json()
    await api.post(f"/api/v1/sources/{src['id']}/crawl")
    art = (await api.get("/api/v1/articles", params={"limit": 1})).json()["items"][0]
    r = await api.get(f"/api/v1/articles/{art['id']}/raw")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "<html" in r.text.lower()


async def test_conflicting_crawl_and_cancel(api):
    app = api._transport.app

    async def noop(job_id):
        return None

    app.dependency_overrides[get_dispatcher] = lambda: noop
    src = (await api.post("/api/v1/sources", json=SOURCE)).json()
    job = (await api.post(f"/api/v1/sources/{src['id']}/crawl")).json()
    assert job["status"] == "pending"
    assert (await api.post(f"/api/v1/sources/{src['id']}/crawl")).status_code == 409
    cancelled = (await api.post(f"/api/v1/crawls/{job['id']}/cancel")).json()
    assert cancelled["status"] == "cancelled"
    assert (await api.post(f"/api/v1/crawls/{job['id']}/cancel")).status_code == 409


async def test_dispatch_failure_marks_job_failed(api):
    app = api._transport.app

    async def broken(job_id):
        raise ConnectionError("broker down")

    app.dependency_overrides[get_dispatcher] = lambda: broken
    src = (await api.post("/api/v1/sources", json=SOURCE)).json()
    assert (await api.post(f"/api/v1/sources/{src['id']}/crawl")).status_code == 503
    assert (await api.get("/api/v1/crawls", params={"status": "failed"})).json()["total"] == 1


async def test_debug_extract_by_url(api):
    r = await api.post("/api/v1/debug/extract", json={"url": f"{HOST}/2024/05/14/city-approves-transit-plan"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["article"]["is_article"] and body["article"]["title"] == "City approves sweeping transit plan"
    assert body["classification"]["score"] > 0.9
    assert {s["strategy"] for s in body["strategies"]} >= {"jsonld", "metatags", "trafilatura", "density"}
    assert body["fetch"]["status_code"] == 200 and body["fingerprints"]["content_hash"]
    assert "https://news.example.com/feed" in body["discovery"]["feeds"]


async def test_debug_extract_with_html(api):
    r = await api.post("/api/v1/debug/extract", json={"url": "https://gazette.example.org/news/storm-knocks-out-power-to-thousands",
                                                       "html": fixture_text("article_plain.html")})
    assert r.json()["article"]["authors"] == ["Sam Lee"]


@pytest.mark.parametrize("url,code", [("http://169.254.169.254/latest", 422), (f"{HOST}/private/secret-story-here-now", 403),
                                      (f"{HOST}/missing", 502)])
async def test_debug_extract_errors(api, url, code):
    r = await api.post("/api/v1/debug/extract", json={"url": url})
    assert r.status_code == code, r.text


async def test_debug_robots_and_normalize(api):
    r = (await api.get("/api/v1/debug/robots", params={"url": f"{HOST}/private/x"})).json()
    assert r["allowed"] is False
    n = (await api.get("/api/v1/debug/normalize", params={"url": "HTTPS://A.com/x?utm_source=y&b=1"})).json()
    assert n["normalized"] == "https://a.com/x?b=1"


async def test_api_key_required_when_configured(api, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "api_key", "s3cret")
    assert (await api.get("/api/v1/sources")).status_code == 401
    assert (await api.get("/api/v1/sources", headers={"X-API-Key": "wrong"})).status_code == 401
    assert (await api.get("/api/v1/sources", headers={"X-API-Key": "s3cret"})).status_code == 200
    assert (await api.get("/health")).status_code == 200  # probes stay open


async def test_stats(api):
    src = (await api.post("/api/v1/sources", json=SOURCE)).json()
    await api.post(f"/api/v1/sources/{src['id']}/crawl")
    s = (await api.get("/api/v1/stats", params={"days": 7})).json()
    assert s["totals"]["articles"] == 3 and s["totals"]["sources"] == 1
    assert s["last_24h"]["new"] == 3 and s["last_24h"]["fetched"] >= 3
    assert len(s["articles_per_day"]) == 7 and s["articles_per_day"][-1]["count"] == 3
    assert s["languages"][0] == {"language": "en", "count": 3}
    assert s["jobs_by_status"] == {"succeeded": 1}
    assert s["sources"][0]["articles"] == 3 and s["sources"][0]["last_status"] == "succeeded"


async def test_cors_preflight(engine, monkeypatch):
    import httpx

    from app.api.main import create_app
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "cors_origins", ["https://ui.example.com"])
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.options("/api/v1/sources", headers={"Origin": "https://ui.example.com",
                                                         "Access-Control-Request-Method": "GET",
                                                         "Access-Control-Request-Headers": "x-api-key"})
        assert r.headers["access-control-allow-origin"] == "https://ui.example.com"
        r = await c.options("/api/v1/sources", headers={"Origin": "https://evil.example",
                                                         "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in r.headers
