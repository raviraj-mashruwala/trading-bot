import logging
import threading
import time

from tradingbot.executor.loop_watchdog import LoopWatchdog


def make(alerts, stall_seconds=60.0):
    return LoopWatchdog(stall_seconds=stall_seconds, alert=alerts.append)


def test_no_alert_while_the_loop_keeps_beating():
    alerts = []
    dog = make(alerts)
    dog.beat(now=100.0)

    assert dog.check(now=130.0) is False
    assert alerts == []


def test_stalled_loop_alerts_once_per_episode():
    alerts = []
    dog = make(alerts)
    dog.beat(now=100.0)

    assert dog.check(now=170.0) is True
    assert dog.check(now=200.0) is False  # same episode, already alerted
    assert len(alerts) == 1
    assert "70s" in alerts[0]


def test_alert_rearms_after_the_loop_recovers():
    alerts = []
    dog = make(alerts)
    dog.beat(now=100.0)
    dog.check(now=170.0)

    dog.beat(now=180.0)
    assert dog.check(now=190.0) is False
    assert dog.check(now=250.0) is True
    assert len(alerts) == 2


def test_stall_logs_stacks_of_every_thread(caplog):
    alerts = []
    dog = make(alerts)
    dog.beat(now=0.0)

    with caplog.at_level(logging.ERROR):
        dog.check(now=120.0)

    assert "MainThread" in caplog.text
    assert "test_stall_logs_stacks_of_every_thread" in caplog.text


def test_not_armed_before_the_first_beat():
    alerts = []
    dog = make(alerts)

    assert dog.check(now=10_000.0) is False


def test_alert_failure_does_not_break_the_watchdog():
    def boom(_message):
        raise RuntimeError("telegram down")

    dog = LoopWatchdog(stall_seconds=60.0, alert=boom)
    dog.beat(now=0.0)

    assert dog.check(now=120.0) is True


def test_background_thread_detects_a_real_stall():
    alerts = []
    dog = LoopWatchdog(stall_seconds=0.2, alert=alerts.append, check_interval=0.05)
    dog.start()
    try:
        dog.beat()
        deadline = time.monotonic() + 3
        while not alerts and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        dog.stop()

    assert len(alerts) == 1


def test_stop_ends_the_thread():
    dog = LoopWatchdog(stall_seconds=60.0, alert=lambda m: None, check_interval=0.05)
    dog.start()
    dog.stop()

    assert not any(t.name == "loop-watchdog" and t.is_alive() for t in threading.enumerate())
