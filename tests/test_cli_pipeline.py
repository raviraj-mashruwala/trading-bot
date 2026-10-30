import dataclasses
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.test_cli import make_plan, write_config, write_env
from tradingbot.analysis.pipeline import DataNeeded
from tradingbot.cli import cli
from tradingbot.core.llm.file_provider import AnswersNeeded
from tradingbot.core.models import IST
from tradingbot.scanner.calendar import next_trading_day

TRADE_DATE = next_trading_day(date(2026, 10, 1)).isoformat()
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    write_env(monkeypatch)
    home = tmp_path / "home"
    (home / ".tradingbot").mkdir(parents=True)
    (home / ".tradingbot" / "kite_token").write_text("token")
    monkeypatch.setattr(Path, "home", lambda: home)
    return tmp_path


def invoke(tmp_path, *args):
    config_path = write_config(tmp_path)
    return CliRunner().invoke(
        cli, ["--config", str(config_path), "--data-dir", str(tmp_path), *args],
    )


def fake_analysis(monkeypatch, behaviour):
    async def fake(state, trade_date):
        behaviour(state, trade_date)

    monkeypatch.setattr("tradingbot.api.analysis_routes._run_analysis", fake)


def add_request(queue: Path, rid="abc123", tool="submit_regime_analysis"):
    (queue / "requests").mkdir(parents=True, exist_ok=True)
    (queue / "requests" / f"{rid}.json").write_text(
        json.dumps({"id": rid, "tool_name": tool, "created_at": "2026-10-30T10:00:00+05:30"})
    )


def save_plan(state, trade_date, generated_at=None):
    plan = dataclasses.replace(
        make_plan(), trade_date=str(trade_date),
        generated_at=generated_at or datetime.now(tz=IST),
    )
    state.plan_store.save(plan)


# ----- analyze -----------------------------------------------------------------

def test_analyze_exit_10_lists_pending_requests_and_next_step(env, monkeypatch):
    def behaviour(state, trade_date):
        add_request(Path(state.config.llm.queue_dir))
        state.analysis_status = "blocked"
        state.analysis_blocked = AnswersNeeded([])

    fake_analysis(monkeypatch, behaviour)

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert result.exit_code == 10
    assert "1 LLM requests pending" in result.output
    assert "abc123" in result.output and "submit_regime_analysis" in result.output
    assert f"/answer-llm-requests {TRADE_DATE} - answer only. Don't run any scripts, I'll run them myself." in result.output
    assert f"then rerun: scripts/analysis/analyze.sh {TRADE_DATE}" in result.output


def test_analyze_exit_11_names_symbols_and_fetch_script(env, monkeypatch):
    def behaviour(state, trade_date):
        state.analysis_status = "blocked"
        state.analysis_blocked = DataNeeded(["INFY", "TCS"])

    fake_analysis(monkeypatch, behaviour)

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert result.exit_code == 11
    assert "INFY" in result.output and "TCS" in result.output
    assert f"scripts/analysis/fetch.sh {TRADE_DATE}" in result.output


def test_analyze_exit_0_prints_plan_path_and_leg_count(env, monkeypatch):
    def behaviour(state, trade_date):
        state.analysis_status = "complete"
        save_plan(state, trade_date)

    fake_analysis(monkeypatch, behaviour)

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert result.exit_code == 0, result.output
    assert f"{TRADE_DATE}.json" in result.output
    assert "1 legs" in result.output


def test_analyze_exit_1_when_no_plan_file_written(env, monkeypatch):
    fake_analysis(monkeypatch, lambda state, d: setattr(state, "analysis_status", "complete"))

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert result.exit_code == 1
    assert "no plan" in result.output.lower()


def test_analyze_does_not_accept_a_plan_left_over_from_an_earlier_run(env, monkeypatch):
    def behaviour(state, trade_date):
        state.analysis_status = "complete"
        save_plan(state, trade_date, generated_at=datetime(2026, 1, 1, tzinfo=IST))

    fake_analysis(monkeypatch, behaviour)

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert result.exit_code == 1
    assert "no plan" in result.output.lower()


def test_analyze_exit_1_and_prints_the_error_when_analysis_failed(env, monkeypatch):
    def behaviour(state, trade_date):
        state.analysis_status = "failed"
        state.analysis_error = "kite exploded"

    fake_analysis(monkeypatch, behaviour)

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert result.exit_code == 1
    assert "kite exploded" in result.output


def test_analyze_uses_per_date_queue_dir_and_the_file_provider(env, monkeypatch):
    seen = {}

    def behaviour(state, trade_date):
        seen["queue_dir"] = state.config.llm.queue_dir
        seen["provider"] = state.config.llm.provider
        seen["require_prefetched"] = state.require_prefetched
        state.analysis_status = "failed"
        state.analysis_error = "stop"

    fake_analysis(monkeypatch, behaviour)

    invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert seen["queue_dir"].endswith(f"llm_queue/{TRADE_DATE}")
    assert seen["provider"] == "file"  # config says anthropic; never bill the API from here
    assert seen["require_prefetched"] is True


def test_analyze_defaults_to_the_default_trade_date(env, monkeypatch):
    seen = {}
    monkeypatch.setattr("tradingbot.cli.default_trade_date", lambda: date(2026, 10, 26))

    def behaviour(state, trade_date):
        seen["date"] = trade_date
        state.analysis_status = "failed"
        state.analysis_error = "stop"

    fake_analysis(monkeypatch, behaviour)

    invoke(env, "pipeline", "analyze")

    assert seen["date"] == date(2026, 10, 26)


def test_analyze_rejects_a_non_trading_day(env, monkeypatch):
    fake_analysis(monkeypatch, lambda state, d: None)

    result = invoke(env, "pipeline", "analyze", "--date", "2026-10-25")  # a Sunday

    assert result.exit_code == 1
    assert "not a trading day" in result.output


# ----- fetch -------------------------------------------------------------------

def answered_shortlist(env, symbols):
    queue = env / "llm_queue" / TRADE_DATE
    add_request(queue, "sl1", tool="submit_shortlist")
    (queue / "answers").mkdir(parents=True, exist_ok=True)
    (queue / "answers" / "sl1.json").write_text(
        json.dumps({"shortlist": [{"symbol": s} for s in symbols]})
    )


def test_fetch_uses_shortlist_from_answered_request(env, monkeypatch):
    answered_shortlist(env, ["INFY", "TCS"])
    fetched = []

    async def fake_fetch(self, symbols, progress=None):
        fetched.extend(symbols)
        return {s: 10 for s in symbols}

    monkeypatch.setattr("tradingbot.analysis.pipeline.AnalysisPipeline.fetch_shortlist", fake_fetch)
    monkeypatch.setattr(
        "tradingbot.analysis.pipeline.AnalysisPipeline.missing_shortlist_data",
        lambda self, symbols, trade_date=None: [],
    )

    result = invoke(env, "pipeline", "fetch", "--date", TRADE_DATE)

    assert result.exit_code == 0, result.output
    assert fetched == ["INFY", "TCS"]
    assert f"next: rerun scripts/analysis/analyze.sh {TRADE_DATE}" in result.output


def test_fetch_without_shortlist_answer_exits_1_and_prints_the_chat_prompt(env):
    result = invoke(env, "pipeline", "fetch", "--date", TRADE_DATE)

    assert result.exit_code == 1
    assert "shortlist" in result.output.lower()
    assert f"/answer-llm-requests {TRADE_DATE} - answer only." in result.output


def test_fetch_exits_1_when_data_is_still_missing_afterwards(env, monkeypatch):
    answered_shortlist(env, ["INFY"])

    async def fake_fetch(self, symbols, progress=None):
        return {}

    monkeypatch.setattr("tradingbot.analysis.pipeline.AnalysisPipeline.fetch_shortlist", fake_fetch)
    monkeypatch.setattr(
        "tradingbot.analysis.pipeline.AnalysisPipeline.missing_shortlist_data",
        lambda self, symbols, trade_date=None: ["INFY"],
    )

    result = invoke(env, "pipeline", "fetch", "--date", TRADE_DATE)

    assert result.exit_code == 1
    assert "INFY" in result.output
    assert "tradingbot auth" in result.output  # an expired token is the usual cause


# ----- sync --------------------------------------------------------------------

def test_sync_prints_status_and_exits_0_on_success(env, monkeypatch):
    async def fake(state, force_full=False):
        state.sync_status = {"status": "complete", "stocks_synced": 12}

    monkeypatch.setattr("tradingbot.api.sync_routes._run_sync", fake)

    result = invoke(env, "pipeline", "sync")

    assert result.exit_code == 0
    assert "complete" in result.output


def test_sync_exits_nonzero_on_error_status(env, monkeypatch):
    async def fake(state, force_full=False):
        state.sync_status = {"status": "error", "error": "no network"}

    monkeypatch.setattr("tradingbot.api.sync_routes._run_sync", fake)

    result = invoke(env, "pipeline", "sync")

    assert result.exit_code == 1
    assert "no network" in result.output


@pytest.mark.parametrize("command", [["sync"], ["analyze"], ["fetch"]])
def test_pipeline_commands_fail_without_kite_token(tmp_path, monkeypatch, command):
    write_env(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-home")

    result = invoke(tmp_path, "pipeline", *command)

    assert result.exit_code == 1
    assert "tradingbot auth" in result.output


# ----- llm pending -------------------------------------------------------------

def test_llm_pending_prints_none_when_drained(env):
    result = invoke(env, "llm", "pending", "--date", TRADE_DATE)

    assert result.exit_code == 0
    assert result.output.strip() == "none"


def test_llm_pending_lists_requests(env):
    add_request(env / "llm_queue" / TRADE_DATE, "abc123")

    result = invoke(env, "llm", "pending", "--date", TRADE_DATE)

    assert result.exit_code == 0
    assert "abc123  submit_regime_analysis" in result.output


# ----- scripts and run configurations -------------------------------------------

@pytest.mark.parametrize("name,command", [
    ("sync", "pipeline sync"), ("analyze", "pipeline analyze"), ("fetch", "pipeline fetch"),
    ("review", "pipeline review"),
])
def test_scripts_exist_are_executable_and_call_the_cli(name, command):
    script = ROOT / "scripts" / "analysis" / f"{name}.sh"

    assert script.exists()
    assert script.stat().st_mode & 0o111
    text = script.read_text()
    assert text.startswith("#!/usr/bin/env bash")
    assert f"-m tradingbot {command}" in text
    assert '"$@"' in text


@pytest.mark.parametrize("name", ["Sync", "Analyze", "Fetch", "Review"])
def test_intellij_run_configurations_point_at_the_scripts(name):
    config = (ROOT / ".idea" / "runConfigurations" / f"Analysis___{name}.xml").read_text()

    assert f"scripts/analysis/{name.lower()}.sh" in config
    assert "$PROJECT_DIR$" in config


@pytest.mark.parametrize("name", ["analyze", "fetch", "review"])
def test_scripts_accept_a_bare_date_argument(name):
    import os
    import subprocess

    def run(*args):
        result = subprocess.run(
            [str(ROOT / "scripts" / "analysis" / f"{name}.sh"), *args],
            capture_output=True, text=True, env={**os.environ, "PYTHON": "echo"},
        )
        return result.stdout.strip()

    assert run("2026-10-30") == f"-m tradingbot pipeline {name} --date 2026-10-30"
    assert run("--date", "2026-10-30") == f"-m tradingbot pipeline {name} --date 2026-10-30"
    assert run() == f"-m tradingbot pipeline {name}"


def test_sync_script_passes_flags_through():
    import os
    import subprocess

    result = subprocess.run(
        [str(ROOT / "scripts" / "analysis" / "sync.sh"), "--full"],
        capture_output=True, text=True, env={**os.environ, "PYTHON": "echo"},
    )

    assert result.stdout.strip() == "-m tradingbot pipeline sync --full"


def test_pipeline_and_llm_commands_work_without_an_anthropic_key(tmp_path, monkeypatch):
    # config.toml ships provider = "anthropic"; these commands never use it.
    monkeypatch.setattr("tradingbot.core.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")

    result = invoke(tmp_path, "llm", "pending", "--date", TRADE_DATE)

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "none"


def test_other_commands_still_require_the_anthropic_key(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingbot.core.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")

    result = invoke(tmp_path, "history")

    assert result.exit_code != 0
    assert "ANTHROPIC_API_KEY" in result.output


# ----- review ------------------------------------------------------------------

def fake_review(monkeypatch, behaviour):
    async def fake(database, llm, trade_date=None, setup_store=None, candle_store=None, jev_client=None):
        return await behaviour(llm, trade_date)

    monkeypatch.setattr("tradingbot.analysis.nightly_reviewer.run_nightly_review", fake)


async def ask_the_llm(llm, trade_date):
    return await llm.analyze(
        system_prompt="s", user_prompt="u", tool_name="nightly_review",
        tool_description="d", input_schema={"type": "object"},
    )


def test_review_exit_10_lists_the_pending_request_and_next_step(env, monkeypatch):
    fake_review(monkeypatch, ask_the_llm)

    result = invoke(env, "pipeline", "review", "--date", TRADE_DATE)

    assert result.exit_code == 10, result.output
    assert "1 LLM requests pending" in result.output
    assert "nightly_review" in result.output
    assert f"/answer-llm-requests {TRADE_DATE} - answer only. Don't run any scripts, I'll run them myself." in result.output
    assert f"then rerun: scripts/analysis/review.sh {TRADE_DATE}" in result.output
    assert "nightly review" in result.output  # round label


def test_review_exit_0_prints_grade_trades_and_pnl(env, monkeypatch):
    async def done(llm, trade_date):
        return {"trade_date": trade_date, "grade": "B", "trades_count": 3, "total_pnl": 1234.5}

    fake_review(monkeypatch, done)

    result = invoke(env, "pipeline", "review", "--date", TRADE_DATE)

    assert result.exit_code == 0, result.output
    assert "grade B" in result.output
    assert "3 trades" in result.output
    assert "1,234.50" in result.output


def test_review_with_no_activity_says_so_and_exits_0(env, monkeypatch):
    async def skipped(llm, trade_date):
        return {"trade_date": trade_date, "skipped": True, "reason": "no activity"}

    fake_review(monkeypatch, skipped)

    result = invoke(env, "pipeline", "review", "--date", TRADE_DATE)

    assert result.exit_code == 0
    assert "no activity" in result.output


def test_review_uses_the_file_provider_a_per_date_queue_and_the_review_step(env, monkeypatch):
    from tradingbot.core.llm.file_provider import FileAnswerProvider, _current_step

    seen = {}

    async def inspect(llm, trade_date):
        seen["provider"] = llm
        seen["step"] = _current_step.get()
        return {"skipped": True, "reason": "x", "trade_date": trade_date}

    fake_review(monkeypatch, inspect)

    invoke(env, "pipeline", "review", "--date", TRADE_DATE)

    assert isinstance(seen["provider"], FileAnswerProvider)  # never the Anthropic API
    assert str(seen["provider"].queue_dir).endswith(f"llm_queue/{TRADE_DATE}")
    assert seen["step"] == "review"


def test_review_does_not_need_a_kite_token(tmp_path, monkeypatch):
    write_env(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-home")

    async def skipped(llm, trade_date):
        return {"skipped": True, "reason": "no activity", "trade_date": trade_date}

    fake_review(monkeypatch, skipped)

    result = invoke(tmp_path, "pipeline", "review", "--date", TRADE_DATE)

    assert result.exit_code == 0, result.output


def test_review_failure_exits_1_with_the_message(env, monkeypatch):
    async def boom(llm, trade_date):
        raise RuntimeError("db locked")

    fake_review(monkeypatch, boom)

    result = invoke(env, "pipeline", "review", "--date", TRADE_DATE)

    assert result.exit_code == 1
    assert "db locked" in result.output


def test_review_defaults_to_the_default_review_date(env, monkeypatch):
    seen = {}
    monkeypatch.setattr("tradingbot.cli.default_review_date", lambda: date(2026, 10, 22))

    async def capture(llm, trade_date):
        seen["date"] = trade_date
        return {"skipped": True, "reason": "x", "trade_date": trade_date}

    fake_review(monkeypatch, capture)

    invoke(env, "pipeline", "review")

    assert seen["date"] == "2026-10-22"


# ----- the chosen date is announced up front ---------------------------------------

def stop_after_start(monkeypatch):
    fake_analysis(monkeypatch, lambda state, d: (
        setattr(state, "analysis_status", "failed"), setattr(state, "analysis_error", "stop"),
    ))


def test_analyze_announces_an_explicit_date(env, monkeypatch):
    stop_after_start(monkeypatch)

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert f"analyze: trade date {TRADE_DATE} (from --date)" in result.output


def test_analyze_announces_a_defaulted_date(env, monkeypatch):
    stop_after_start(monkeypatch)
    monkeypatch.setattr("tradingbot.cli.default_trade_date", lambda: date(2026, 10, 26))

    result = invoke(env, "pipeline", "analyze")

    assert "analyze: trade date 2026-10-26 (default: next session)" in result.output


def test_fetch_announces_the_date_before_doing_anything(env):
    result = invoke(env, "pipeline", "fetch", "--date", TRADE_DATE)  # fails: no shortlist yet

    assert f"fetch: trade date {TRADE_DATE} (from --date)" in result.output


def test_review_announces_a_defaulted_date(env, monkeypatch):
    monkeypatch.setattr("tradingbot.cli.default_review_date", lambda: date(2026, 10, 22))

    async def skipped(llm, trade_date):
        return {"skipped": True, "reason": "x", "trade_date": trade_date}

    fake_review(monkeypatch, skipped)

    result = invoke(env, "pipeline", "review")

    assert "review: session 2026-10-22 (default: latest finished session)" in result.output


@pytest.mark.parametrize("tool,label", [
    ("submit_regime_analysis", "regime"),
    ("submit_sector_analysis", "sectors"),
    ("submit_shortlist", "shortlist"),
    ("submit_deep_analysis", "deep analysis"),
    ("submit_validation", "adversarial review"),
])
def test_analyze_exit_10_says_which_round_it_is(env, monkeypatch, tool, label):
    def behaviour(state, trade_date):
        add_request(Path(state.config.llm.queue_dir), tool=tool)
        state.analysis_status = "blocked"
        state.analysis_blocked = AnswersNeeded([])

    fake_analysis(monkeypatch, behaviour)

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert f"(round: {label})" in result.output


def test_shortlist_round_points_at_fetch_before_analyze(env, monkeypatch):
    def behaviour(state, trade_date):
        add_request(Path(state.config.llm.queue_dir), tool="submit_shortlist")
        state.analysis_status = "blocked"
        state.analysis_blocked = AnswersNeeded([])

    fake_analysis(monkeypatch, behaviour)

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert (
        f"then run: scripts/analysis/fetch.sh {TRADE_DATE}, "
        f"then rerun scripts/analysis/analyze.sh {TRADE_DATE}"
    ) in result.output


@pytest.mark.parametrize("tool", ["submit_deep_analysis", "submit_validation", "submit_regime_analysis"])
def test_other_rounds_still_point_straight_back_at_analyze(env, monkeypatch, tool):
    def behaviour(state, trade_date):
        add_request(Path(state.config.llm.queue_dir), tool=tool)
        state.analysis_status = "blocked"
        state.analysis_blocked = AnswersNeeded([])

    fake_analysis(monkeypatch, behaviour)

    result = invoke(env, "pipeline", "analyze", "--date", TRADE_DATE)

    assert f"then rerun: scripts/analysis/analyze.sh {TRADE_DATE}" in result.output
    assert "fetch.sh" not in result.output
