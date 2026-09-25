import asyncio

import pytest

from tradingbot.core.events import EventBus


async def test_emit_delivers_to_a_subscriber():
    bus = EventBus()
    received = []
    bus.subscribe(lambda event: received.append(event))

    await bus.emit("scan.universe", {"count": 50})

    assert len(received) == 1
    assert received[0]["type"] == "scan.universe"
    assert received[0]["data"] == {"count": 50}
    assert "timestamp" in received[0]


async def test_emit_delivers_to_multiple_subscribers():
    bus = EventBus()
    a, b = [], []
    bus.subscribe(lambda event: a.append(event))
    bus.subscribe(lambda event: b.append(event))

    await bus.emit("scan.filtered", {"passed": 38})

    assert len(a) == 1
    assert len(b) == 1


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    received = []
    sub_id = bus.subscribe(lambda event: received.append(event))

    await bus.emit("scan.universe", {"count": 50})
    bus.unsubscribe(sub_id)
    await bus.emit("scan.filtered", {"passed": 38})

    assert len(received) == 1
    assert received[0]["type"] == "scan.universe"


async def test_unsubscribe_unknown_id_is_a_noop():
    bus = EventBus()
    bus.unsubscribe("nonexistent")


async def test_emit_with_no_subscribers_does_not_raise():
    bus = EventBus()
    await bus.emit("scan.universe", {"count": 50})


async def test_emit_sync_queues_for_later_delivery():
    bus = EventBus()
    received = []
    bus.subscribe(lambda event: received.append(event))

    bus.emit_sync("exec.price_tick", {"symbol": "RELIANCE", "price": 100.0})
    assert len(received) == 0

    flush_task = asyncio.create_task(bus.flush_loop())
    await asyncio.sleep(0.1)
    await bus.shutdown()
    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert received[0]["type"] == "exec.price_tick"
    assert received[0]["data"]["symbol"] == "RELIANCE"


async def test_emit_sync_multiple_events_all_flushed():
    bus = EventBus()
    received = []
    bus.subscribe(lambda event: received.append(event))

    bus.emit_sync("exec.entry_placed", {"symbol": "A"})
    bus.emit_sync("exec.entry_filled", {"symbol": "A"})
    bus.emit_sync("exec.stop_hit", {"symbol": "A"})

    flush_task = asyncio.create_task(bus.flush_loop())
    await asyncio.sleep(0.1)
    await bus.shutdown()
    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    assert [e["type"] for e in received] == [
        "exec.entry_placed",
        "exec.entry_filled",
        "exec.stop_hit",
    ]


async def test_event_envelope_has_iso_timestamp():
    bus = EventBus()
    received = []
    bus.subscribe(lambda event: received.append(event))

    await bus.emit("test.event", {"key": "value"})

    ts = received[0]["timestamp"]
    assert "T" in ts
    assert "+" in ts or "Z" in ts


async def test_a_failing_subscriber_does_not_block_others():
    bus = EventBus()
    good = []

    def bad_subscriber(event):
        raise RuntimeError("I crash")

    bus.subscribe(bad_subscriber)
    bus.subscribe(lambda event: good.append(event))

    await bus.emit("test.event", {"key": "value"})

    assert len(good) == 1


async def test_subscribe_returns_unique_ids():
    bus = EventBus()

    id_a = bus.subscribe(lambda e: None)
    id_b = bus.subscribe(lambda e: None)

    assert id_a != id_b
    assert isinstance(id_a, str)
    assert isinstance(id_b, str)
