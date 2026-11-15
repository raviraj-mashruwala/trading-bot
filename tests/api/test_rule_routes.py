async def test_rule_status_is_idle_initially(api_client):
    response = await api_client.get("/api/rules/kec/status")
    assert response.status_code == 200
    body = response.json()
    assert body["running"] is False and body["session"] is None
    assert body["defaults"]["symbol"] == "KEC" and body["defaults"]["entry_time"] == "09:20"
    assert body["defaults"]["balance_buffer"] == 2500
    assert body["defaults"]["stop_adr_mult"] == 0.65


async def test_live_start_requires_explicit_confirmation(api_client):
    response = await api_client.post("/api/rules/kec/start", json={"mode": "live"})
    assert response.status_code == 400
    assert "confirm" in response.json()["detail"]


async def test_start_rejects_bad_mode_and_buffer(api_client):
    assert (await api_client.post("/api/rules/kec/start", json={"mode": "demo"})).status_code == 400
    assert (await api_client.post("/api/rules/kec/start", json={"mode": "paper", "buffer": -1})).status_code == 400
    assert (await api_client.post("/api/rules/kec/start", json={"mode": "paper", "buffer": "x"})).status_code == 400


async def test_stop_when_not_running(api_client):
    response = await api_client.post("/api/rules/kec/stop")
    assert response.json()["status"] == "not_running"


async def test_trades_and_events_start_empty(api_client):
    assert (await api_client.get("/api/rules/kec/trades")).json() == []
    assert (await api_client.get("/api/rules/kec/events")).json() == []


async def test_start_rejects_out_of_range_stop_multiplier(api_client):
    for bad in (0, 5, "x"):
        response = await api_client.post("/api/rules/kec/start", json={"mode": "paper", "stop_adr_mult": bad})
        assert response.status_code == 400
