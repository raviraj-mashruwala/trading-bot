# Split Deployment and Manual Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Update 2026-10-30:** Part A is superseded by `2026-10-30-staged-manual-analysis.md` (built and merged). Two decisions since then change Part B: the plan-age limit was removed (a plan is valid for its own trade date however old, so Task 8's freshness check and `plan_max_age_hours` references are obsolete), and the sync/analysis/review schedulers were removed (only the 09:00 execution job remains, so Task 5's per-role job gating reduces to refusing live execution on role `manual`, if that role is still wanted).

**Goal:** Run the live executor alone on a deployed box (09:00 to 15:10 IST, fed by live ticks) while the analysis pipeline (data sync, screening, LLM research, plan) is triggered by hand from a laptop, with every LLM answer produced inside a Claude Code conversation instead of the Anthropic API.

**Architecture:** Analysis side: a new `"file"` `LLMProvider` writes each request as JSON into a per-trade-date queue directory and blocks until a schema-valid response file appears; a Claude Code session answers the queue via a project skill. Pipeline code and tool schemas are untouched, so plan structure is identical. Executor side: a `[deployment] role` setting switches scheduled jobs per machine, the executor resolves its own instrument tokens, and `plan push` copies a freshness-checked plan to the box over scp.

**Tech Stack:** Python 3.13, FastAPI/uvicorn, click, pytest, `jsonschema` (new dependency, used to validate responses against the existing tool schemas).

**Spec:** No separate spec document. The requirements are the user's own words from the 2026-10-22 session, quoted under Global Constraints. Background: `~/.gstack/projects/rmashruwala/rmashruwala-master-design-20261016-023146.md`.

## Global Constraints

- "have the executor turned on and fetch ticks and run during 9am to 4pm on a deployed system"
- "all the features to be run manually or semi autonomous ... triggering a script for fetching daily, then triggering basic screening then using that output to trigger claude research in this conversation ... getting the same output and structure as i am currently having"
- "i want to avoid api billing for now": the analysis side must work with no `ANTHROPIC_API_KEY`.
- Defaults stay as today: `deployment.role = "full"`, `llm.provider = "anthropic"`. Existing `config.toml` files keep working unchanged.
- Pipeline and executor logic is edited only where a task names the file and lines.
- All times are IST. Scheduled jobs fire on NSE trading days only.
- Baseline: `uv run pytest -q` passes (935 tests) before and after every task.
- Commits use git `user.email` = `raviraj.mashruwala@outlook.com` (project CLAUDE.md).

## Review Focus

1. **Duplicate live orders.** The laptop and the box both auto-start execution at 09:00 and both place live orders. Pinned in Task 5: role `manual` has no scheduled jobs and refuses live execution; role `executor` has only the execution job.
2. **Plan already stale at the open.** Plan age is `now - generated_at` against `execution.plan_max_age_hours = 14`. An analysis run at 16:30 reaches 09:00 at 16.5h and the executor blocks it. Pinned in Task 8: `plan push` refuses and names the config key.
3. **Half-written response file.** The responder writes the file while the provider polls it. Pinned in Task 1: unreadable or invalid content is rejected only after the same bytes are seen on two consecutive polls.
4. **Yesterday's answer reused today.** Responses are cached by request hash. Pinned in Task 3: each `analyze --date D` uses its own `<queue_dir>/D/` directory.
5. **Executor box cannot tick or boot.** `instruments.db` is only refreshed by sync/analysis, so an executor-only box has an empty cache and `get_token(symbol)` raises `KeyError` (`execution_intelligence.py:108`). Also `ANTHROPIC_API_KEY` is required at config load. Pinned in Tasks 2 and 6, and the escalator fallback without a key in Task 9.

---

## File Structure

| File | Responsibility |
|---|---|
| `tradingbot/core/llm/file_provider.py` (new) | `request_id`, `FileLLMProvider` |
| `tradingbot/core/llm/queue_status.py` (new) | `PendingRequest`, `pending_requests` |
| `tradingbot/api/headless.py` (new) | `build_headless_state` (AppState without FastAPI) |
| `tradingbot/core/plan_handoff.py` (new) | `age_at_open_hours`, `push_plan` |
| `tradingbot/core/config.py` | `LLMConfig` queue fields, optional Anthropic key, `DeploymentConfig` |
| `tradingbot/scheduler.py` | `ROLE_JOBS`, `jobs_for_role`, `due_jobs` |
| `tradingbot/data/instrument_cache.py` | `ensure_symbols` |
| `tradingbot/cli.py` | `pipeline` group, `llm pending`, `plan push`, `serve --host` |
| `.claude/skills/answer-llm-requests/SKILL.md` (new) | How a Claude session answers the queue |
| `docs/architecture/split-deployment.md` (new) | Runbook for the two machines |

---

## Part A: Manual analysis (works on its own; run it on the laptop)

### Task 1: FileLLMProvider

**Files:**
- Create: `tradingbot/core/llm/file_provider.py`
- Modify: `pyproject.toml` and `uv.lock` (run `uv add jsonschema`)
- Test: `tests/core/llm/test_file_provider.py`

**Interfaces:**
- Produces: `request_id(tool_name: str, system_prompt: str, user_prompt: str) -> str` (first 16 hex chars of sha256 over the three strings joined with `"\x00"`).
- Produces: `class FileLLMProvider(LLMProvider)` with `__init__(self, queue_dir: Path, wait_timeout_sec: float, poll_interval_sec: float = 1.0)`.
- Queue layout: `<queue_dir>/requests/<id>.json`, `<queue_dir>/responses/<id>.json`, `<queue_dir>/rejected/<id>.json` plus `<id>.reason.txt`. Request JSON keys: `id, tool_name, tool_description, system_prompt, user_prompt, input_schema, created_at` (ISO, IST). A response file is the bare tool-input object and nothing else.

- [ ] **Step 1: Write the failing tests** in `tests/core/llm/test_file_provider.py` (follow the async style in `test_anthropic_provider.py`; use `poll_interval_sec=0.02`):
  - `test_request_id_is_stable_and_changes_with_user_prompt`
  - `test_analyze_writes_request_file_with_schema_then_waits`: start `analyze` as a task, wait for the request file, assert all seven keys, cancel the task.
  - `test_response_written_later_is_returned`: a responder writes a valid response 0.05s later; assert the returned dict equals it.
  - `test_existing_response_is_returned_without_rewriting_request`: pre-create the response; assert no file appears in `requests/`.
  - `test_schema_violation_is_rejected_then_corrected_response_accepted`: write a response missing a required key; assert it moves to `rejected/` with a `.reason.txt` naming the key; then write a valid one and assert it is returned.
  - `test_partially_written_response_is_not_rejected_prematurely`: write truncated JSON, complete it one poll later; assert `rejected/` is empty and the result is returned.
  - `test_timeout_raises_llm_timeout_error` (`wait_timeout_sec=0.1`).
  - `test_health_check_true_for_writable_dir_and_does_not_wait`.
  - `test_production_tool_schemas_accept_minimal_valid_responses`: for `REGIME_TOOL`, `SHORTLIST_TOOL`, `DEEP_ANALYSIS_TOOL`, `ADVERSARIAL_TOOL` from `tradingbot.analysis.prompts`, hand-write a minimal valid object per schema and assert the provider returns it. This guards the "same structure" requirement.
- [ ] **Step 2: Run** `uv run pytest tests/core/llm/test_file_provider.py -q`. Expected: fail with `ModuleNotFoundError`.
- [ ] **Step 3: Implement `FileLLMProvider.analyze(...) -> dict[str, Any]` and `health_check() -> bool`.** Decisions the tests do not pin: the request file is written once, atomically (temp file plus `os.replace`), only if absent; polling uses `await asyncio.sleep(poll_interval_sec)`; a response that is unreadable or fails `jsonschema.validate(response, input_schema)` is remembered by its bytes and rejected on the second consecutive identical sighting (move to `rejected/`, write the validation message to `.reason.txt`, keep waiting); timeout raises `LLMTimeoutError(f"no response for {tool_name} {id} within {wait_timeout_sec}s")`; log INFO `awaiting LLM response: {tool_name} {id}`; the returned dict carries no `_usage` key (the pipeline only reads it when present).
- [ ] **Step 4: Run** the same command. Expected: all pass.
- [ ] **Step 5: Commit** `feat: add file-based LLM provider for conversation-driven analysis`.

### Task 2: Config and provider factory

**Files:**
- Modify: `tradingbot/core/config.py` (`LLMConfig` at ~177-182, `[llm]` parsing at ~360-366, `Secrets` at ~371-375)
- Modify: `tradingbot/core/llm/anthropic_provider.py` (`build_provider`, ~153-161)
- Test: `tests/core/test_config.py` (extend), `tests/core/llm/test_build_provider.py` (new)

**Interfaces:**
- Consumes: `FileLLMProvider` from Task 1.
- Produces: `LLMConfig.queue_dir: str = "llm_queue"` and `LLMConfig.wait_timeout_sec: int = 21600`, read from optional `[llm]` keys of the same names.
- Produces: `Secrets.anthropic_api_key` is `os.environ.get("ANTHROPIC_API_KEY", "")` when `llm.provider == "file"`, otherwise `_require_env("ANTHROPIC_API_KEY")` exactly as today.
- Produces: `build_provider(config, secrets, log_dir=None)` returns `FileLLMProvider(Path(config.queue_dir), config.wait_timeout_sec)` for `"file"`. All four existing call sites (`analysis_routes.py:92`, `review_routes.py:101`, `config_routes.py:181`, `app.py:181`) then work unchanged.

- [ ] **Step 1: Write failing tests.** Every test that deletes `ANTHROPIC_API_KEY` must also monkeypatch `tradingbot.core.config.load_dotenv` to a no-op, because `load_config` re-reads the repo `.env`.
  - `test_file_provider_config_loads_without_anthropic_key`
  - `test_anthropic_provider_config_still_requires_key` (raises `ConfigError`)
  - `test_llm_queue_settings_default_and_override`
  - `test_build_provider_returns_file_provider_for_file`
  - `test_build_provider_unknown_provider_message_lists_anthropic_and_file`
- [ ] **Step 2: Run** `uv run pytest tests/core/test_config.py tests/core/llm/test_build_provider.py -q`. Expected: the new tests fail.
- [ ] **Step 3: Implement** the three interface changes above. Import `FileLLMProvider` lazily inside `build_provider` so file mode never imports `anthropic`.
- [ ] **Step 4: Run** `uv run pytest tests/core -q`. Expected: pass.
- [ ] **Step 5: Commit** `feat: llm.provider = "file" with optional Anthropic key`.

### Task 3: Headless pipeline commands

**Files:**
- Create: `tradingbot/api/headless.py`
- Modify: `tradingbot/cli.py` (new `pipeline` group next to the retired `analyze`/`sync` stubs at ~101-118 and ~332-339; leave the stubs)
- Test: `tests/test_cli_pipeline.py`

**Interfaces:**
- Consumes: `_run_sync(state, force_full)` from `tradingbot/api/sync_routes.py:19`; `_run_analysis(state, trade_date)` from `tradingbot/api/analysis_routes.py:71`; `AppState` fields at `tradingbot/api/state.py`.
- Produces: `build_headless_state(config: Config, data_dir: Path, llm_queue_subdir: str | None = None) -> AppState`. It mirrors the `lifespan` setup in `tradingbot/api/app.py:31-45` and `:133-142` without FastAPI: `Database(data_dir/"tradingbot.db").initialise()`, `PlanStore(data_dir/"trade_plans")`, `CandleStore(data_dir/"candles.duckdb")`, `EventBus()`, `AppState(...)`. When `llm_queue_subdir` is given, replace the config with `dataclasses.replace` so `llm.queue_dir = <queue_dir>/<subdir>`.
- Produces CLI: `tradingbot pipeline sync [--full]` and `tradingbot pipeline analyze [--date YYYY-MM-DD]`.

- [ ] **Step 1: Write failing tests** (CliRunner; monkeypatch `_run_sync`/`_run_analysis` so nothing touches Kite or the network; monkeypatch `Path.home` for the token file):
  - `test_analyze_defaults_to_next_trading_day`
  - `test_analyze_uses_per_date_llm_queue_dir`: the fake `_run_analysis` captures `state.config.llm.queue_dir`; assert it ends with `/2026-10-23` for `--date 2026-10-23`.
  - `test_analyze_exits_nonzero_when_analysis_status_is_error` and prints `state.analysis_error`.
  - `test_analyze_exits_nonzero_when_no_plan_file_written`: `_run_analysis` swallows plan-build errors (`analysis_routes.py:~170`), so the CLI checks `plan_store.path_for(date)` itself.
  - `test_analyze_prints_plan_path_and_leg_count_on_success`
  - `test_sync_exits_nonzero_on_error_status`
  - `test_pipeline_commands_fail_without_kite_token` (message points to `tradingbot auth`).
- [ ] **Step 2: Run** `uv run pytest tests/test_cli_pipeline.py -q`. Expected: fail (no `pipeline` command).
- [ ] **Step 3: Implement** `build_headless_state` and the two commands. `analyze` prints one line per pipeline event, using the event types already listed in `_PIPELINE_STEP_EVENTS` in `analysis_routes.py`, and runs `event_bus.flush_loop()` as a background task while the pipeline runs. `sync` prints `state.sync_status` at the end.
- [ ] **Step 4: Run** `uv run pytest tests/test_cli_pipeline.py tests/test_cli.py -q`. Expected: pass.
- [ ] **Step 5: Commit** `feat: pipeline sync/analyze commands runnable without the web server`.

### Task 4: Queue status command and the responder skill

**Files:**
- Create: `tradingbot/core/llm/queue_status.py`, `.claude/skills/answer-llm-requests/SKILL.md`
- Modify: `tradingbot/cli.py` (new `llm` group)
- Test: `tests/core/llm/test_queue_status.py`, `tests/test_cli_pipeline.py` (extend)

**Interfaces:**
- Consumes: queue layout from Task 1; `queue_dir` from Task 2.
- Produces: `@dataclass PendingRequest(id: str, tool_name: str, created_at: str, path: Path)` and `pending_requests(queue_dir: Path) -> list[PendingRequest]`, sorted by `created_at`. A request is pending when `requests/<id>.json` exists and `responses/<id>.json` does not.
- Produces CLI: `tradingbot llm pending [--date YYYY-MM-DD]` prints `<id>  <tool_name>  <path>` per line, or `none`; exit code 0 either way. Default date is the next trading day; the directory is `<llm.queue_dir>/<date>`.

- [ ] **Step 1: Write failing tests:** `test_pending_lists_unanswered_requests_oldest_first`, `test_pending_ignores_answered_requests`, `test_pending_on_missing_dir_is_empty`, `test_llm_pending_cli_prints_none_when_drained`.
- [ ] **Step 2: Run** `uv run pytest tests/core/llm/test_queue_status.py -q`. Expected: fail.
- [ ] **Step 3: Implement** `pending_requests` and the CLI command.
- [ ] **Step 4: Write `SKILL.md`** (name `answer-llm-requests`; trigger: the user asks to answer pending LLM requests). Its body must state exactly these rules:
  1. Run `uv run python -m tradingbot llm pending --date <D>`; for each id, read the request JSON.
  2. Answer as the persona in `system_prompt`, follow its rules verbatim, use only data present in `user_prompt` (the prompts already forbid invented price levels).
  3. Output exactly the tool-input object for `input_schema`: all required keys, exact enum strings, numbers as numbers, no prose. Write it to `responses/<id>.json`.
  4. After writing, check `rejected/<id>.reason.txt`; if present, fix and rewrite.
  5. Loop until `llm pending` prints `none` on two checks 10 seconds apart and the `pipeline analyze` process has exited; then report the plan path and leg count.
  6. Deep-analysis requests are independent of each other and may be answered by parallel subagents, one request file each.
- [ ] **Step 5: Run** `uv run pytest tests/core/llm tests/test_cli_pipeline.py -q`. Expected: pass.
- [ ] **Step 6: Commit** `feat: llm pending command and responder skill`.

---

## Part B: Deployable executor (works on its own; run it on the box)

### Task 5: Deployment role

**Files:**
- Modify: `tradingbot/core/config.py` (add `DeploymentConfig`, `Config.deployment`, parse `[deployment]`)
- Modify: `tradingbot/scheduler.py`
- Modify: `tradingbot/api/app.py` (`_daily_scheduler`, ~307-369)
- Modify: `tradingbot/api/health_routes.py`
- Modify: `tradingbot/api/execution_routes.py` (`start_execution`, ~351)
- Test: `tests/test_scheduler.py`, `tests/core/test_config.py`, `tests/api/test_health_routes.py`, `tests/api/test_execution_routes.py` (extend or create)

**Interfaces:**
- Produces: `ROLE_JOBS: dict[str, frozenset[str]]` with `full` = `{"execution","sync","analysis","review"}`, `executor` = `{"execution"}`, `manual` = `frozenset()`; `jobs_for_role(role: str) -> frozenset[str]` (raises `ValueError` for an unknown role).
- Produces: `due_jobs(role: str, now_time: time, today: date, is_trading_day: bool, prev_was_trading_day: bool, last_run: Mapping[str, date | None]) -> list[str]`: job names that are due now (calls the existing `should_*` functions, then filters by role). The scheduler loop keeps one `last_run` dict and replaces each `if should_x(...)` with `if "x" in due`.
- Produces: `DeploymentConfig(role: str = "full")`; `load_config` raises `ConfigError` for a role not in `ROLE_JOBS`.
- Produces: `/api/health` gains `"role"`. `POST /api/execute` with `mode == "live"` while role is `manual` returns 409 `{"detail": "live execution is disabled on role 'manual'"}`; paper mode is allowed.

- [ ] **Step 1: Write failing tests:**
  - `test_due_jobs_full_role_at_0901_returns_execution`, `test_due_jobs_full_role_at_1631_returns_analysis`
  - `test_due_jobs_executor_role_never_returns_sync_or_analysis` (check at 16:01 and 16:31 on a trading day)
  - `test_due_jobs_manual_role_returns_nothing_at_0901`
  - `test_due_jobs_respects_last_run_for_today`
  - `test_unknown_role_raises_value_error`, `test_config_defaults_role_full`, `test_config_rejects_unknown_role`
  - `test_health_reports_role`
  - `test_live_execute_refused_on_manual_role`, `test_paper_execute_allowed_on_manual_role`
- [ ] **Step 2: Run** `uv run pytest tests/test_scheduler.py tests/core/test_config.py tests/api -q`. Expected: new tests fail.
- [ ] **Step 3: Implement** the interfaces above and rewire `_daily_scheduler` to use `due_jobs`. Keep the per-job dispatch bodies (sync, analysis, nightly review existence check) as they are.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: deployment roles gate scheduled jobs and live execution`.

### Task 6: Executor resolves its own instrument tokens

**Files:**
- Modify: `tradingbot/data/instrument_cache.py`
- Modify: `tradingbot/api/execution_routes.py` (`_run_execution`, after the `InstrumentCache` is created at ~126)
- Test: `tests/data/test_instrument_cache.py` (extend or create)

**Interfaces:**
- Produces: `ensure_symbols(cache: InstrumentCache, fetch_instruments: Callable[[str], list[dict]], symbols: Iterable[str]) -> list[str]`. It tries `cache.get_token` for every symbol; if any raises `KeyError`, it calls `cache.refresh(fetch_instruments("NSE"))` once and retries. It returns the symbols still unresolved.
- `_run_execution` calls it with the plan's leg symbols and `data_kite_client.fetch_instruments`; a non-empty result raises `RuntimeError("cannot resolve instrument token for: ...")` so the failure is visible rather than a silent stale-data wait.

- [ ] **Step 1: Write failing tests:** `test_ensure_symbols_no_fetch_when_all_resolve`, `test_ensure_symbols_refreshes_once_when_cache_empty`, `test_ensure_symbols_returns_symbols_still_missing_after_refresh`.
- [ ] **Step 2: Run** `uv run pytest tests/data/test_instrument_cache.py -q`. Expected: fail.
- [ ] **Step 3: Implement** `ensure_symbols` and the call in `_run_execution`.
- [ ] **Step 4: Run** `uv run pytest tests/data tests/api -q`. Expected: pass.
- [ ] **Step 5: Commit** `fix: executor refreshes instrument tokens when its cache lacks a plan symbol`.

### Task 7: Safer `serve` on the box

**Files:**
- Modify: `tradingbot/cli.py` (`serve`, ~342-370)
- Test: `tests/test_cli_serve.py`

**Interfaces:**
- Produces: `serve --host TEXT`. The resolved host is the option if given, else `"127.0.0.1"` when `config.deployment.role == "executor"`, else `"0.0.0.0"` (current behavior). The startup message and `uvicorn.run(host=...)` use the resolved host. No authentication is added (out of scope); the runbook requires an SSH tunnel.

- [ ] **Step 1: Write failing tests** (monkeypatch `uvicorn.run` and capture `host`): `test_serve_explicit_host_wins`, `test_serve_executor_role_defaults_to_loopback`, `test_serve_full_and_manual_roles_keep_all_interfaces`.
- [ ] **Step 2: Run** `uv run pytest tests/test_cli_serve.py -q`. Expected: fail.
- [ ] **Step 3: Implement** the option and host resolution.
- [ ] **Step 4: Run** `uv run pytest tests/test_cli_serve.py tests/test_cli.py -q`. Expected: pass.
- [ ] **Step 5: Commit** `feat: serve --host, loopback by default on the executor role`.

### Task 8: Plan handoff

**Files:**
- Create: `tradingbot/core/plan_handoff.py`
- Modify: `tradingbot/cli.py` (`plan` group at ~238, add `push`)
- Test: `tests/core/test_plan_handoff.py`, `tests/test_cli_plan_push.py`

**Interfaces:**
- Produces: `age_at_open_hours(plan: TradePlan, open_time: time = time(9, 0)) -> float`: hours from `plan.generated_at` to `plan.trade_date` at `open_time` IST.
- Produces: `push_plan(plan_path: Path, destination: str, runner: Callable[..., Any] = subprocess.run) -> None`: runs `["scp", "-p", str(plan_path), destination]`; raises `PlanPushError` on a non-zero return code.
- Produces CLI: `tradingbot plan push --to DEST [--date YYYY-MM-DD] [--force]`. It loads the plan via `PlanStore` (latest by default), computes the age at open, and if the age exceeds `config.execution.plan_max_age_hours` and `--force` is absent, exits 1 with: `plan will be {age:.1f}h old at the 09:00 open; execution.plan_max_age_hours is {limit:g}. Raise it in the executor box's config.toml, or regenerate later (--force to push anyway)`.

- [ ] **Step 1: Write failing tests:**
  - `test_age_at_open_for_plan_generated_previous_evening_2000` equals 13.0
  - `test_age_at_open_for_plan_generated_at_1630` equals 16.5
  - `test_push_plan_runs_scp_with_preserve_flag`, `test_push_plan_raises_on_nonzero_exit`
  - `test_plan_push_refuses_stale_plan_without_force` (exit 1; output contains `execution.plan_max_age_hours`)
  - `test_plan_push_force_pushes_stale_plan`, `test_plan_push_defaults_to_latest_plan`
- [ ] **Step 2: Run** `uv run pytest tests/core/test_plan_handoff.py tests/test_cli_plan_push.py -q`. Expected: fail.
- [ ] **Step 3: Implement** the module and the command. Never alter `generated_at`.
- [ ] **Step 4: Run** the same command. Expected: pass.
- [ ] **Step 5: Commit** `feat: plan push with pre-open freshness check`.

### Task 9: Runbook and escalator-without-key guard

**Files:**
- Create: `docs/architecture/split-deployment.md`
- Test: `tests/executor/test_llm_escalator.py` (extend or create)

- [ ] **Step 1: Write the test** `test_escalator_without_api_key_returns_fallback`: delete `ANTHROPIC_API_KEY`, call `LLMEscalator()._call("p", {"ENTER", "WAIT"}, "WAIT")` and assert `fallback_used is True` and `action == "WAIT"` (the client is created inside the `try`, `llm_escalator.py:62-64`, so this should already pass; the test locks it in).
- [ ] **Step 2: Run** `uv run pytest tests/executor/test_llm_escalator.py -q`. Expected: pass.
- [ ] **Step 3: Write the runbook** with these sections: (a) roles and the `config.toml` for each machine (laptop: `role = "manual"`, `provider = "file"`; box: `role = "executor"`, `provider = "file"` so no Anthropic key is needed at boot); (b) env vars per machine (box: Kite key/secret, `TYPESAFE_API_KEY` for Jev, Telegram vars, `ANTHROPIC_API_KEY` optional because entry escalation falls back to WAIT); (c) the daily timeline (laptop after 16:00: `pipeline sync`, `pipeline analyze`, answer the queue, `plan push`; box before 09:00: Kite login through the Telegram `/login` and `/token` commands in `telegram_commands.py`; the auto-start window is 09:00 to 09:05, so the server must be up by then); (d) access through `ssh -L 8000:localhost:8000` only; (e) never run roles `full` or `executor` on two machines at once; (f) known gaps: no API authentication, Telegram `/analyze` still exists on the box, `plan_max_age_hours` interaction, nightly review is not scheduled under `manual`.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `docs: split deployment runbook`.

---

## Not in this plan (deliberate)

- API authentication for `serve` (the runbook relies on loopback plus an SSH tunnel).
- A separate screening-only preview command: `pipeline analyze` already runs Tier 1 first and prints its progress.
- Scheduling or answering the nightly review in manual mode.
- Hosting choice, Docker or systemd units.
- Whether any strategy has an edge; this plan changes how the system runs, not what it trades.
