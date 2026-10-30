---
name: answer-llm-requests
description: Use when the user asks to answer the pending LLM requests for a trade date, or to run the analysis for a date. Drives the staged analysis pipeline, answering each LLM step in this conversation instead of the Anthropic API.
---

# Answer pending LLM requests

The analysis pipeline never waits on this conversation. Each script run does its work, writes the LLM questions it needs as files, and exits. You answer them, then rerun the script. Repeat until it writes the plan.

`<D>` is the trade date, `YYYY-MM-DD`. If the user gave none, omit it and the scripts use the next session; read the date from the script's output after that.

## Loop

1. **Run the script**, in the foreground, and read its exit code:

   `scripts/analysis/analyze.sh <D>`

   - **exit 0**: the plan is written. Report the plan path and leg count the script printed. Stop.
   - **exit 1**: report the error the script printed. Stop. Do not retry blindly.
   - **exit 11**: shortlist candles are missing. Run `scripts/analysis/fetch.sh <D>` with `run_in_background`, then wait for its completion notification (never poll, never sleep in a loop). When it finishes, go back to the top of this loop. If it fails, report the error and stop.
   - **exit 10**: LLM answers are needed. Continue to step 2.

2. **List what to answer:** `.venv/bin/python -m tradingbot llm pending --date <D>`. Each line is `<id>  <tool_name>  <path to the request JSON>`.

3. **Answer every pending request.** For each one, read the request JSON, then:
   - Answer as the persona in `system_prompt` and follow its rules verbatim.
   - Use only data present in `user_prompt`. Never invent prices, levels, news or indicator values. If the data is too thin, say so in the answer's reasoning fields and use the schema's no-trade or low-confidence options rather than guessing.
   - Output exactly the tool-input object for `input_schema`: every required key, exact enum strings, numbers as numbers, no extra keys, no prose around it.
   - Write it as one file, `answers/<id>.json`, next to `requests/` in the same queue directory (`llm_queue/<D>/` by default). Write the whole file in a single write so it is never half-written.

4. **Check for rejections.** The pipeline validates every answer when it reruns. If `rejected/<id>.reason.txt` exists, read the reason, fix the answer, and write `answers/<id>.json` again. `llm pending` also keeps listing a request whose answer is invalid.

5. **Deep-analysis requests are independent.** There is one per shortlisted stock (`tool_name` `submit_deep_analysis`, step `deep:<SYMBOL>`). When there are several, answer them with parallel subagents, one request file each, and give each subagent the file path and the rules in step 3. Regime, sectors, shortlist and adversarial requests depend on earlier answers, so answer those yourself.

6. **Rerun.** When `llm pending` prints `none`, go back to step 1. Never leave a script running while you answer: the script has already exited, and every rerun is a fresh, fast process.

## Notes

- A full day is about five answer rounds: regime, sectors, shortlist, deep analysis (all stocks at once), adversarial review. Candle download happens between shortlist and deep analysis, as `fetch.sh`.
- The user can run any script by hand from IntelliJ (`Analysis — Sync`, `Analyze`, `Fetch`). Each prints what is needed next, so this skill also works when they ran a step themselves.
- Nightly data sync is a separate step, `scripts/analysis/sync.sh`. Suggest it if analyze fails because the candle cache is empty or stale. Do not run it unasked: it is slow.
- These commands never call the Anthropic API, whatever `config.toml` says.
