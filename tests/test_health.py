async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "x-request-id" in resp.headers


async def test_ready_reports_dependency_status(client):
    resp = await client.get("/health/ready")
    body = resp.json()
    assert body["checks"]["database"] == "ok"
    # Redis is not running on the test port, so readiness must degrade, not crash.
    assert resp.status_code in (200, 503)
    assert "redis" in body["checks"]


async def test_metrics_endpoint(client):
    await client.get("/health")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"api_requests_total" in resp.content
