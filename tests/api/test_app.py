import pytest
from httpx import ASGITransport, AsyncClient

from tradingbot.api.app import create_app

CONFIG_TEXT = """\
[general]
mode = "paper"
capital = 400000
log_level = "INFO"

[scanner]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 5000
min_atr_pct = 0.5
max_stocks_to_llm = 100
llm_pick_count = 15

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 2

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2

[execution]
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1
base_url = ""

[paper]
slippage_pct = 0.05
initial_capital = 400000
"""


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")
    (tmp_path / "config.toml").write_text(CONFIG_TEXT)
    return create_app(config_path=tmp_path / "config.toml", data_dir=tmp_path)


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Trigger the lifespan manually
        from contextlib import asynccontextmanager
        from asgi_lifespan import LifespanManager
        async with LifespanManager(app):
            yield ac


async def test_health_endpoint_returns_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "ok"
    assert "database" in body


async def test_cors_headers_present_for_localhost_3000(client):
    response = await client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_unknown_route_returns_404(client):
    response = await client.get("/api/nonexistent")
    assert response.status_code == 404
