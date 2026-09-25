import pytest


async def test_health_endpoint_returns_ok(api_client):
    response = await api_client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "ok"
    assert "database" in body


async def test_cors_headers_present_for_localhost_3000(api_client):
    response = await api_client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_unknown_route_returns_404(api_client):
    response = await api_client.get("/api/nonexistent")
    assert response.status_code == 404
