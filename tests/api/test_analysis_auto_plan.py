"""Test that plan generation emits plan.generated event."""

from __future__ import annotations

import pytest


async def test_generate_plan_emits_plan_generated_event(api_client):
    state = api_client._app.state.app_state

    events_received = []
    state.event_bus.subscribe(lambda e: events_received.append(e))

    response = await api_client.post("/api/plans/generate?date=2026-10-01")
    assert response.status_code == 200

    plan_events = [e for e in events_received if e["type"] == "plan.generated"]
    assert len(plan_events) == 1
    assert plan_events[0]["data"]["trade_date"] == "2026-10-01"
