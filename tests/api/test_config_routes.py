import pytest


async def test_get_config_returns_all_sections(api_client):
    response = await api_client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["general"]["mode"] == "paper"
    assert body["general"]["capital"] == 400000
    assert body["screening"]["min_volume"] == 500000
    assert body["llm"]["provider"] == "anthropic"


async def test_get_config_masks_secrets(api_client):
    response = await api_client.get("/api/config")
    body = response.json()
    assert body["secrets"]["anthropic_api_key"].startswith("***")
    assert body["secrets"]["anthropic_api_key"].endswith("123")
    assert "sk-ant-secret" not in body["secrets"]["anthropic_api_key"]


async def test_get_config_providers_lists_available(api_client):
    response = await api_client.get("/api/config/providers")
    assert response.status_code == 200
    names = [p["name"] for p in response.json()]
    assert "anthropic" in names


async def test_put_config_updates_a_section(api_client):
    response = await api_client.put("/api/config", json={"general": {"capital": 500000}})
    assert response.status_code == 200

    updated = await api_client.get("/api/config")
    assert updated.json()["general"]["capital"] == 500000


async def test_put_config_rejects_invalid_mode(api_client):
    response = await api_client.put("/api/config", json={"general": {"mode": "turbo"}})
    assert response.status_code == 400
    assert "mode" in response.json()["detail"].lower()


CONFIG_WITHOUT_RISK = """\
[general]
mode = "paper"
capital = 20000
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
initial_capital = 20000
"""


@pytest.fixture()
def config_text_no_risk():
    return CONFIG_WITHOUT_RISK


async def test_put_config_accepts_risk_override_when_section_absent(
    tmp_path, monkeypatch, config_text_no_risk,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret123")
    monkeypatch.setenv("KITE_API_KEY", "kite-key-abc")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret-xyz")
    (tmp_path / "config.toml").write_text(config_text_no_risk)

    from tradingbot.api.app import create_app
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    app = create_app(config_path=tmp_path / "config.toml", data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with LifespanManager(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/config", json={"risk": {"max_concurrent_positions": 5}}
            )
            assert response.status_code == 200

            updated = await client.get("/api/config")
            assert updated.json()["risk"]["max_concurrent_positions"] == 5
