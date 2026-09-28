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
