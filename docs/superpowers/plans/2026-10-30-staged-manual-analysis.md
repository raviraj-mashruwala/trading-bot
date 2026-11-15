# Staged Manual Analysis Implementation Plan (replaces Part A of 2026-10-22-split-deployment-manual-analysis.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Run the analysis pipeline with every LLM answer produced inside a Claude Code conversation, with no process ever waiting on the conversation: no polling loop, no wait timeout. Heavy downloads run as plain scripts; the conversation only does reasoning.

**Why this replaces Part A:** the original Part A had a provider that blocks (up to 6h) until a response file appears, so a process holding the pipeline state sat idle while the conversation worked. The user rejected that: downloads must be separate scripts, and the conversation resumes only after they finish.

**Architecture:** `FileAnswerProvider` is non-blocking. A request whose answer file exists returns it; otherwise it writes the request file once and raises `AnswersNeeded`. `AnalysisPipeline.run` is therefore rerunnable: each run advances until it is blocked, then the process exits with a code that says what is needed. Tier 1 reads the local candle store, so reruns cost seconds. The one heavy step inside the pipeline (candle fetch for the shortlist) becomes its own script, and the pipeline refuses to continue until that data is present.

**Tech Stack:** Python 3.13, click, pytest, `jsonschema` (new dependency, validates answers against the existing tool schemas).

**Spec:** No separate spec. Requirements are the user's words from the 2026-10-30 session: (1) "execute via scripts or via intellij run configs ... don't want to have to run manual commands", (2) "I don't want 1 full flow with time out, because when analyze downloads the candles data it takes time, so that should be done via a script once llm conversation has shortlisted the stocks and no llm cost should be there or no loop running till that shell has finished processing, and after that only the conversation resumes."

## Global Constraints

- No process waits on a conversation. Every command exits promptly with a code (below).
- No `ANTHROPIC_API_KEY` needed with `llm.provider = "file"`. Defaults unchanged (`provider = "anthropic"`).
- Pipeline logic is edited only where a task names the function. Stage order, prompts, tool schemas and plan format are unchanged.
- Exit codes for `pipeline analyze`: `0` done (plan written), `10` answers needed, `11` shortlist data needed (run `fetch`), `1` error.
- Each user-facing step exists as a shell script in `scripts/analysis/` and as an IntelliJ shell run configuration in `.idea/runConfigurations/` (same format as `Backend___API_Server.xml`, working dir `$PROJECT_DIR$`, interpreter `$PROJECT_DIR$/.venv/bin/python`).
- Baseline: `uv run pytest -q` passes (982 tests) before and after every task.
- Commits use git `user.email` = `raviraj.mashruwala@outlook.com`.

## The flow (what the user does)

| Step | Who | Command | LLM? | Waits on chat? |
|---|---|---|---|---|
| 0 | script | `scripts/analysis/sync.sh` (nightly data sync) | no | no |
| 1 | script | `scripts/analysis/analyze.sh [DATE]` runs Tier 1, then exits 10 with the regime request pending | no | no |
| 2 | chat | "answer the pending LLM requests for DATE" (skill `answer-llm-requests`) | yes | n/a |
| 3 | script | `analyze.sh DATE` again: sectors pending (exit 10) | no | no |
| 4 | chat | answer | yes | n/a |
| 5 | script | `analyze.sh DATE`: shortlist pending (exit 10) | no | no |
| 6 | chat | answer the shortlist | yes | n/a |
| 7 | script | `analyze.sh DATE`: exit 11, shortlist candles missing | no | no |
| 8 | script | `scripts/analysis/fetch.sh DATE` (heavy download, runs to completion) | no | no |
| 9 | script | `analyze.sh DATE`: N deep-analysis requests pending, all written at once (exit 10) | no | no |
| 10 | chat | answer all N (parallel subagents allowed) | yes | n/a |
| 11 | script | `analyze.sh DATE`: backtests run, adversarial request pending (exit 10) | no | no |
| 12 | chat | answer | yes | n/a |
| 13 | script | `analyze.sh DATE`: setups saved, plan written (exit 0) | no | no |

The skill automates this: given a date it runs the scripts itself and answers in between, so the user normally types one prompt. Running the scripts by hand from IntelliJ is equally valid at any step; each prints what is needed next.

## Review Focus

1. **Duplicate or partial work on rerun.** `run` repeats Tier 1 on every run. It must not persist anything (`run_store`, `setup_store`) before the final stage, or reruns write duplicate rows. Pinned in Task 3.
2. **Stale answers.** Answers are keyed by request hash and live in a per-date directory, so a changed prompt (new data) never reuses an old answer, and a new date never sees an old directory. Pinned in Task 1.
3. **Half-written answer file.** Pinned in Task 1: an unparseable file modified within the last 3 seconds counts as pending, not rejected.
4. **Wrong-shape answer.** Rejected immediately with the reason, moved to `rejected/`, request stays pending. Pinned in Task 1.
5. **Batch.** Deep analysis must write all N requests in one run, not one per rerun. Pinned in Task 3.

---

## File Structure

| File | Responsibility |
|---|---|
| `tradingbot/core/llm/file_provider.py` (new) | `request_id`, `AnswersNeeded`, `FileAnswerProvider` |
| `tradingbot/core/llm/queue_status.py` (new) | `PendingRequest`, `pending_requests` |
| `tradingbot/core/config.py` | `LLMConfig.queue_dir`, optional Anthropic key |
| `tradingbot/core/llm/anthropic_provider.py` | `build_provider` handles `"file"` |
| `tradingbot/analysis/pipeline.py` | `DataNeeded`, batch deep analysis, `fetch_shortlist`, prefetched gate |
| `tradingbot/api/headless.py` (new) | `build_headless_state` |
| `tradingbot/cli.py` | `pipeline sync/analyze/fetch`, `llm pending` |
| `scripts/analysis/{sync,analyze,fetch}.sh` (new) | Shell entry points |
| `.idea/runConfigurations/Analysis___*.xml` (new) | IntelliJ run configurations |
| `.claude/skills/answer-llm-requests/SKILL.md` (new) | How a Claude session answers and drives the loop |

---

### Task 1: FileAnswerProvider (non-blocking)

**Files:** Create `tradingbot/core/llm/file_provider.py`; `uv add jsonschema`; Test `tests/core/llm/test_file_provider.py`.

**Interfaces:**
- Produces `request_id(tool_name, system_prompt, user_prompt) -> str`: first 16 hex chars of sha256 over the three strings joined with `"\x00"`.
- Produces `class AnswersNeeded(Exception)` with `.requests: list[Path]`.
- Produces `class FileAnswerProvider(LLMProvider)`, `__init__(self, queue_dir: Path)`.
- Layout: `<queue_dir>/requests/<id>.json`, `<queue_dir>/answers/<id>.json`, `<queue_dir>/rejected/<id>.json` plus `<id>.reason.txt`. Request JSON keys: `id, tool_name, tool_description, system_prompt, user_prompt, input_schema, created_at` (ISO IST). An answer file is the bare tool-input object.

- [ ] **Step 1: Write failing tests** (async style of `test_anthropic_provider.py`):
  - `test_request_id_is_stable_and_changes_with_user_prompt`
  - `test_missing_answer_writes_request_and_raises_answers_needed_without_waiting` (assert returns in under 0.5s, all seven keys present, exception lists the request path)
  - `test_existing_valid_answer_is_returned_and_no_request_written`
  - `test_request_file_is_written_once` (two calls, one file, unchanged `created_at`)
  - `test_schema_violation_is_rejected_with_reason_and_request_stays_pending` (reason names the missing key; request file still present; raises `AnswersNeeded`)
  - `test_corrected_answer_after_rejection_is_accepted`
  - `test_unparseable_fresh_file_is_pending_not_rejected` (mtime now), `test_unparseable_old_file_is_rejected` (mtime 10s ago)
  - `test_health_check_true_for_writable_dir_and_does_not_wait`
  - `test_production_tool_schemas_accept_minimal_valid_answers` for `REGIME_TOOL`, `SHORTLIST_TOOL`, `DEEP_ANALYSIS_TOOL`, `ADVERSARIAL_TOOL` from `tradingbot.analysis.prompts` (guards "same structure"). Also check the sectors tool used by `Tier2Analyzer.analyze_sectors`.
- [ ] **Step 2: Run** `uv run pytest tests/core/llm/test_file_provider.py -q`. Expected: `ModuleNotFoundError`.
- [ ] **Step 3: Implement.** Request file written atomically (temp file + `os.replace`) only if absent. No `_usage` key in returned dicts. `health_check` checks the directory is writable.
- [ ] **Step 4: Run** the same command. Expected: all pass.
- [ ] **Step 5: Commit** `feat: non-blocking file-based LLM answer provider`.

### Task 2: Config and provider factory

**Files:** `tradingbot/core/config.py` (`LLMConfig`, `[llm]` parsing, `Secrets`), `tradingbot/core/llm/anthropic_provider.py` (`build_provider`); Test `tests/core/test_config.py`, `tests/core/llm/test_build_provider.py`.

**Interfaces:** `LLMConfig.queue_dir: str = "llm_queue"` (optional `[llm] queue_dir`). `Secrets.anthropic_api_key` is `os.environ.get("ANTHROPIC_API_KEY", "")` when `llm.provider == "file"`, else `_require_env` as today. `build_provider` returns `FileAnswerProvider(Path(config.queue_dir))` for `"file"`; import it lazily so file mode never imports `anthropic`.

- [ ] **Step 1: Write failing tests** (every test that deletes `ANTHROPIC_API_KEY` must also monkeypatch `tradingbot.core.config.load_dotenv` to a no-op): `test_file_provider_config_loads_without_anthropic_key`, `test_anthropic_provider_config_still_requires_key`, `test_llm_queue_dir_defaults_and_overrides`, `test_build_provider_returns_file_provider_for_file`, `test_build_provider_unknown_provider_message_lists_anthropic_and_file`.
- [ ] **Step 2: Run** `uv run pytest tests/core/test_config.py tests/core/llm/test_build_provider.py -q`. Expected: new tests fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/core -q`. Expected: pass.
- [ ] **Step 5: Commit** `feat: llm.provider = "file" with optional Anthropic key`.

### Task 3: Rerunnable pipeline

**Files:** `tradingbot/analysis/pipeline.py` (`run`, lines ~239-272 fetch block, ~279-336 deep-analysis loop); Test `tests/analysis/test_pipeline_resumable.py`.

**Interfaces:**
- Produces `class DataNeeded(Exception)` with `.symbols: list[str]`.
- `AnalysisPipeline.__init__` gains `require_prefetched: bool = False`.
- Produces `async def fetch_shortlist(self, symbols: list[str], progress=None) -> dict[str, int]`: the existing fetch block, extracted unchanged (Kite token and `KiteDataSync.fetch_shortlist_data`).
- Produces `def shortlist_data_ready(self, symbols) -> list[str]`: symbols whose `duckdb.last_date(symbol, "15m")` is missing. (Gap freshness is the sync script's job; this only blocks first-time stocks.)
- Behaviour: with `require_prefetched=False` (default, web API path) the inline fetch runs exactly as today. With `True`, a non-empty missing list raises `DataNeeded` instead of fetching.
- Deep analysis: wrap each `deep_analyze` in `try/except AnswersNeeded`, remember it, continue; after the loop, if any were pending, re-raise one `AnswersNeeded` listing all request paths. Nothing is saved (`run_store.save`, `setup_store.save`) before the final stage, so an interrupted run persists nothing.

- [ ] **Step 1: Write failing tests** using fakes for screener, tier2, tier3, stores (look at existing `tests/analysis/test_pipeline*.py` for the fakes): `test_missing_regime_answer_exits_before_any_persistence` (run_store and setup_store untouched), `test_all_deep_analysis_requests_written_in_one_run` (3 shortlisted symbols give 3 requests), `test_require_prefetched_raises_data_needed_for_new_symbol`, `test_require_prefetched_false_still_fetches_inline`, `test_complete_answers_produce_the_same_run_as_before` (regression: file provider with every answer pre-written equals the existing anthropic-fake result).
- [ ] **Step 2: Run** `uv run pytest tests/analysis/test_pipeline_resumable.py -q`. Expected: fail.
- [ ] **Step 3: Implement** the interfaces above; extract `fetch_shortlist` without changing its body.
- [ ] **Step 4: Run** `uv run pytest tests/analysis -q`. Expected: pass.
- [ ] **Step 5: Commit** `feat: pipeline can stop at missing LLM answers or shortlist data and be rerun`.

### Task 4: Headless stage commands, scripts, IntelliJ configs

**Files:** Create `tradingbot/api/headless.py`, `tradingbot/core/llm/queue_status.py`, `scripts/analysis/{sync,analyze,fetch}.sh`, `.idea/runConfigurations/Analysis___Sync.xml`, `Analysis___Analyze.xml`, `Analysis___Fetch.xml`; modify `tradingbot/cli.py` (new `pipeline` and `llm` groups beside the retired stubs; leave the stubs); Test `tests/test_cli_pipeline.py`, `tests/core/llm/test_queue_status.py`.

**Interfaces:**
- `build_headless_state(config, data_dir, llm_queue_subdir=None) -> AppState`: mirrors `tradingbot/api/app.py` lifespan setup without FastAPI; when `llm_queue_subdir` is given, `llm.queue_dir = <queue_dir>/<subdir>` via `dataclasses.replace`.
- `PendingRequest(id, tool_name, created_at, path)`, `pending_requests(queue_dir) -> list[PendingRequest]` sorted by `created_at`; pending = request file exists and answer file does not.
- CLI: `tradingbot pipeline sync [--full]`; `pipeline analyze [--date D]` (exit codes in Global Constraints; on 10 prints `<n> LLM requests pending for D:` then `<id>  <tool_name>  <path>` lines and `next: ask Claude to "answer the pending LLM requests for D", then rerun analyze`; on 11 prints the missing symbols and `next: run scripts/analysis/fetch.sh D`); `pipeline fetch [--date D]` reads the shortlist from the answered shortlist request in `<queue_dir>/D/` and calls `fetch_shortlist`; `llm pending [--date D]`. Default date is the next trading day. `analyze` builds the pipeline with `require_prefetched=True`, and on success writes the plan with the same builder call as `_run_analysis` (`analysis_routes.py` ~164-179) and prints plan path and leg count; if no plan file results it exits 1.
- Scripts: `#!/usr/bin/env bash`, `cd "$(dirname "$0")/../.."`, `exec .venv/bin/python -m tradingbot pipeline <cmd> "$@"`, mode 755. Each IntelliJ config calls its script with `$Prompt$` not used: date optional, defaults to next trading day.

- [ ] **Step 1: Write failing tests** (CliRunner; monkeypatch pipeline, `_run_sync` and `Path.home`; nothing touches Kite or network): `test_analyze_exit_10_lists_pending_requests_and_next_step`, `test_analyze_exit_11_names_symbols_and_fetch_script`, `test_analyze_exit_0_prints_plan_path_and_leg_count`, `test_analyze_exit_1_when_no_plan_file_written`, `test_analyze_uses_per_date_queue_dir`, `test_analyze_defaults_to_next_trading_day`, `test_fetch_uses_shortlist_from_answered_request`, `test_fetch_without_shortlist_answer_exits_1_with_message`, `test_sync_exits_nonzero_on_error_status`, `test_pipeline_commands_fail_without_kite_token` (message points to `tradingbot auth`), `test_llm_pending_prints_none_when_drained`, plus the queue_status tests: `test_pending_lists_unanswered_requests_oldest_first`, `test_pending_ignores_answered_requests`, `test_pending_on_missing_dir_is_empty`; and `test_scripts_exist_are_executable_and_call_the_cli` (the three `.sh` files).
- [ ] **Step 2: Run** `uv run pytest tests/test_cli_pipeline.py tests/core/llm/test_queue_status.py -q`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/test_cli_pipeline.py tests/test_cli.py tests/core -q`. Expected: pass.
- [ ] **Step 5: Commit** `feat: pipeline sync/analyze/fetch commands, scripts and IntelliJ run configs`.

### Task 5: The responder skill

**Files:** Create `.claude/skills/answer-llm-requests/SKILL.md`; Test `tests/test_skill_answer_llm_requests.py` (asserts the file exists, front matter has `name: answer-llm-requests` and a description naming "pending LLM requests", and the body contains each rule marker below).

The body states exactly these rules:
1. Trigger: the user asks to answer pending LLM requests, or to run the analysis for a date.
2. Run `scripts/analysis/analyze.sh <D>`. Exit 0: report plan path and leg count, stop. Exit 1: show the error, stop. Exit 11: run `scripts/analysis/fetch.sh <D>` with `run_in_background`, wait for its completion notification (never poll or sleep), then rerun analyze. Exit 10: continue to rule 3.
3. For each pending id (`llm pending --date <D>`), read the request JSON, answer as the persona in `system_prompt`, use only data in `user_prompt`, output exactly the tool-input object for `input_schema` (all required keys, exact enum strings, numbers as numbers, no prose), write it to `answers/<id>.json` in one write.
4. After writing, check `rejected/<id>.reason.txt`; if present, fix and rewrite.
5. Deep-analysis requests are independent and may be answered by parallel subagents, one request file each.
6. When `llm pending` prints `none`, go back to rule 2. Repeat until exit 0. Never leave a script running while answering; the script has already exited.

- [ ] **Step 1: Write the test.** **Step 2: Run** it, expected fail. **Step 3: Write `SKILL.md`.** **Step 4: Run** `uv run pytest -q`, expected all pass. **Step 5: Commit** `feat: answer-llm-requests skill drives the staged analysis`.

---

## Not in this plan

- Part B of the original plan (deployment roles, executor token refresh, `serve --host`, `plan push`, runbook). Unchanged and still pending; it needs a hosting decision.
- Caching Tier 1 results between reruns (they are local and take seconds; revisit only if a rerun measures slow).
- Scheduling any of these scripts.
