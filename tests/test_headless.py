from datetime import datetime
from pathlib import Path

from tradingbot.api.headless import build_headless_state, default_review_date, default_trade_date
from tradingbot.core.config import load_config
from tradingbot.core.models import IST
from tests.test_cli import write_config, write_env


def load(tmp_path, monkeypatch):
    write_env(monkeypatch)
    return load_config(write_config(tmp_path))


def test_state_has_the_stores_the_pipeline_needs(tmp_path, monkeypatch):
    config = load(tmp_path, monkeypatch)

    state = build_headless_state(config, tmp_path)

    assert state.database is not None
    assert state.plan_store.path_for("2026-10-30") == tmp_path / "trade_plans" / "2026-10-30.json"
    assert state.candle_store is not None
    assert state.data_dir == str(tmp_path)


def test_relative_queue_dir_lives_under_the_data_dir_with_a_per_date_subdir(tmp_path, monkeypatch):
    config = load(tmp_path, monkeypatch)

    state = build_headless_state(config, tmp_path, llm_queue_subdir="2026-10-30")

    assert Path(state.config.llm.queue_dir) == tmp_path / "llm_queue" / "2026-10-30"


def test_absolute_queue_dir_is_kept(tmp_path, monkeypatch):
    import dataclasses

    config = load(tmp_path, monkeypatch)
    config = dataclasses.replace(config, llm=dataclasses.replace(config.llm, queue_dir="/tmp/q"))

    state = build_headless_state(config, tmp_path, llm_queue_subdir="2026-10-30")

    assert Path(state.config.llm.queue_dir) == Path("/tmp/q/2026-10-30")


def test_default_trade_date_is_today_before_post_close_on_a_trading_day():
    friday_noon = datetime(2026, 10, 23, 12, 0, tzinfo=IST)

    assert default_trade_date(friday_noon).isoformat() == "2026-10-23"


def test_default_trade_date_is_next_trading_day_after_close():
    friday_evening = datetime(2026, 10, 23, 18, 0, tzinfo=IST)

    assert default_trade_date(friday_evening).isoformat() == "2026-10-26"


def test_default_review_date_is_today_once_the_session_is_over():
    friday_evening = datetime(2026, 10, 23, 18, 0, tzinfo=IST)

    assert default_review_date(friday_evening).isoformat() == "2026-10-23"


def test_default_review_date_is_the_previous_trading_day_before_the_close():
    friday_noon = datetime(2026, 10, 23, 12, 0, tzinfo=IST)

    assert default_review_date(friday_noon).isoformat() == "2026-10-22"


def test_default_review_date_skips_the_weekend():
    monday_morning = datetime(2026, 10, 26, 9, 0, tzinfo=IST)
    saturday = datetime(2026, 10, 24, 11, 0, tzinfo=IST)

    assert default_review_date(monday_morning).isoformat() == "2026-10-23"
    assert default_review_date(saturday).isoformat() == "2026-10-23"
