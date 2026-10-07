# Shortlist Prompt Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Claude shortlist quality by surfacing all available data, adding structure, rubric, self-check, and a few-shot example to the shortlisting prompts.

**Architecture:** Two files change: `tradingbot/analysis/prompts.py` (system prompt `SHORTLIST_SYSTEM` and user prompt builder `build_shortlist_user_prompt`) and `tests/analysis/test_prompts.py` (test updates). The tool schema (`SHORTLIST_SCHEMA`) stays unchanged — the structured output format is already good. We're improving what Claude sees and how it reasons, not what it returns.

**Tech Stack:** Python, pytest

**Spec:** Research findings from web search on Claude prompting best practices (2026), Anthropic docs, and financial LLM literature. Key techniques: XML structure, rubric-based evaluation, few-shot examples, self-check instructions.

## Global Constraints

- No changes to `SHORTLIST_SCHEMA` or `SHORTLIST_TOOL` — downstream consumers depend on the current output shape.
- No changes to `tier2_analyzer.py` — prompt construction stays in `prompts.py`.
- Factor scores are floats on 0–100 scale (default 50.0 for missing).
- Jev fields (`jev_composite`, `jev_setup_confidence`) are floats added by `jev_shortlist_scorer.py`; may not exist on all stock dicts (pre-Jev path).
- System prompt must remain a plain string (no f-strings) — it's static.
- User prompt builder signature `build_shortlist_user_prompt(regime_analysis, sector_analysis, scored_stocks)` must not change.

## Review Focus

1. **Stocks without Jev scores** — when Jev is disabled or unavailable, `jev_composite`/`jev_setup_confidence` won't exist on stock dicts. The prompt builder must handle missing keys gracefully with `dict.get()` defaults, not KeyError.
2. **Empty scored_stocks list** — prompt builder should produce valid output even with zero candidates (pipeline guards against this upstream, but the prompt function shouldn't crash).
3. **Factor scores with default 50.0** — a stock that wasn't scored on a factor gets 50.0. The prompt should not present 50.0 as meaningful signal. Consider labeling it "N/A" or omitting it.
4. **Prompt token budget** — 30 stocks × richer per-stock data could push the user prompt large. Verify that the expanded format stays under ~4K tokens (well within Claude's window but worth checking).
5. **Existing test assertions on prompt content** — `test_build_shortlist_user_prompt` and `test_shortlist_prompt_counter_argument` must still pass or be updated to match new format.

---

### Task 1: Rewrite `build_shortlist_user_prompt` — XML structure, all factor scores, Jev scores, cap at 30

**Files:**
- Modify: `tradingbot/analysis/prompts.py:374-396` (`build_shortlist_user_prompt` function)
- Test: `tests/analysis/test_prompts.py:148-158` (update existing test + add new tests)

**Interfaces:**
- Consumes: `regime_analysis: dict` (keys: `regime`, `regime_confidence`, `bias`, `risk_appetite`, `sectors_in_play`, `sectors_to_avoid`), `sector_analysis: dict`, `scored_stocks: list[dict]` (keys: `symbol`, `composite_score`, `sector`, `last_price`, `factor_scores` dict with 9 keys, optional `jev_composite`, `jev_setup_confidence`)
- Produces: `str` — XML-structured user prompt consumed by `tier2_analyzer.py:88`

- [ ] **Step 1: Write failing tests for new prompt format**

```python
# In tests/analysis/test_prompts.py — replace existing test_build_shortlist_user_prompt
# and add new tests

def _make_stock(symbol="RELIANCE", composite=85, sector="energy", price=2500,
                factor_scores=None, jev_composite=None, jev_setup_confidence=None):
    """Helper to build a scored stock dict for prompt tests."""
    fs = factor_scores or {
        "volume_surge": 72.0, "relative_strength": 68.0,
        "atr_expansion": 61.0, "price_structure": 75.0,
        "delivery_pct": 55.0, "sector_momentum": 80.0,
        "gap_analysis": 45.0, "candlestick_pattern": 82.0,
        "volume_profile": 70.0,
    }
    d = {"symbol": symbol, "composite_score": composite, "sector": sector,
         "last_price": price, "factor_scores": fs}
    if jev_composite is not None:
        d["jev_composite"] = jev_composite
    if jev_setup_confidence is not None:
        d["jev_setup_confidence"] = jev_setup_confidence
    return d


def test_build_shortlist_user_prompt_xml_structure():
    regime = {"regime": "trending_up", "regime_confidence": 0.82,
              "bias": "bullish", "sectors_in_play": ["banking"],
              "sectors_to_avoid": ["pharma"], "risk_appetite": "moderate"}
    stocks = [_make_stock()]
    prompt = build_shortlist_user_prompt(regime, {}, stocks)
    assert "<regime>" in prompt
    assert "</regime>" in prompt
    assert "<candidates>" in prompt
    assert "</candidates>" in prompt
    assert "<task>" in prompt
    assert "</task>" in prompt


def test_build_shortlist_user_prompt_includes_all_factor_scores():
    stocks = [_make_stock()]
    prompt = build_shortlist_user_prompt({"regime": "range_bound"}, {}, stocks)
    assert "atr_expansion" in prompt
    assert "price_structure" in prompt
    assert "candlestick_pattern" in prompt
    assert "volume_profile" in prompt
    assert "delivery_pct" in prompt
    assert "sector_momentum" in prompt
    assert "gap_analysis" in prompt


def test_build_shortlist_user_prompt_includes_jev_scores():
    stocks = [_make_stock(jev_composite=0.78, jev_setup_confidence=0.85)]
    prompt = build_shortlist_user_prompt({"regime": "range_bound"}, {}, stocks)
    assert "jev_composite" in prompt or "0.78" in prompt
    assert "jev_setup_confidence" in prompt or "0.85" in prompt


def test_build_shortlist_user_prompt_handles_missing_jev():
    stocks = [_make_stock()]  # no jev fields
    prompt = build_shortlist_user_prompt({"regime": "range_bound"}, {}, stocks)
    # Should not crash and should not show jev lines
    assert "RELIANCE" in prompt


def test_build_shortlist_user_prompt_caps_at_30():
    stocks = [_make_stock(symbol=f"STOCK{i}", composite=100 - i) for i in range(50)]
    prompt = build_shortlist_user_prompt({"regime": "range_bound"}, {}, stocks)
    assert "STOCK0" in prompt
    assert "STOCK29" in prompt
    assert "STOCK30" not in prompt


def test_build_shortlist_user_prompt_default_factor_scores():
    stocks = [_make_stock(factor_scores={"volume_surge": 50.0, "relative_strength": 50.0})]
    prompt = build_shortlist_user_prompt({"regime": "range_bound"}, {}, stocks)
    # Default 50.0 values should still appear (they're valid scores)
    assert "RELIANCE" in prompt


def test_build_shortlist_user_prompt_empty_stocks():
    prompt = build_shortlist_user_prompt({"regime": "range_bound"}, {}, [])
    assert "<candidates>" in prompt
    assert "</candidates>" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/analysis/test_prompts.py -v -k "shortlist_user_prompt" --tb=short`
Expected: FAIL — current prompt doesn't contain XML tags or all factor scores.

- [ ] **Step 3: Implement the new `build_shortlist_user_prompt`**

Replace the function at `prompts.py:374-396` with:

```python
def build_shortlist_user_prompt(
    regime_analysis: dict,
    sector_analysis: dict,
    scored_stocks: list[dict],
) -> str:
    """Build XML-structured user prompt for candidate shortlisting."""
    regime_block = (
        f"<regime>\n"
        f"  regime: {regime_analysis.get('regime', 'unknown')}\n"
        f"  confidence: {regime_analysis.get('regime_confidence', 0):.0%}\n"
        f"  bias: {regime_analysis.get('bias', 'neutral')}\n"
        f"  risk_appetite: {regime_analysis.get('risk_appetite', 'moderate')}\n"
        f"  sectors_in_play: {regime_analysis.get('sectors_in_play', [])}\n"
        f"  sectors_to_avoid: {regime_analysis.get('sectors_to_avoid', [])}\n"
        f"</regime>"
    )

    sector_block = ""
    if sector_analysis:
        sectors = sector_analysis.get("sectors", [])
        if sectors:
            sector_lines = "\n".join(
                f"  {s.get('name', '?')}: bias={s.get('intraday_bias', '?')}, "
                f"theme={s.get('theme', '?')}"
                for s in sectors[:10]
            )
            sector_block = f"\n\n<sectors>\n{sector_lines}\n</sectors>"

    stock_lines = []
    for s in scored_stocks[:30]:
        fs = s.get("factor_scores", {})
        parts = [
            f"  <stock symbol=\"{s['symbol']}\" composite_score=\"{s['composite_score']:.0f}\" "
            f"sector=\"{s['sector']}\" price=\"{s['last_price']:.0f}\">",
            f"    vol_surge={fs.get('volume_surge', 'N/A')}, "
            f"RS={fs.get('relative_strength', 'N/A')}, "
            f"atr_expansion={fs.get('atr_expansion', 'N/A')}, "
            f"price_structure={fs.get('price_structure', 'N/A')}",
            f"    delivery_pct={fs.get('delivery_pct', 'N/A')}, "
            f"sector_momentum={fs.get('sector_momentum', 'N/A')}, "
            f"gap_analysis={fs.get('gap_analysis', 'N/A')}",
            f"    candlestick_pattern={fs.get('candlestick_pattern', 'N/A')}, "
            f"volume_profile={fs.get('volume_profile', 'N/A')}",
        ]
        if "jev_composite" in s:
            parts.append(
                f"    jev_composite={s['jev_composite']:.4f}, "
                f"jev_setup_confidence={s.get('jev_setup_confidence', 0):.4f}"
            )
        parts.append("  </stock>")
        stock_lines.append("\n".join(parts))

    candidates_block = "<candidates>\n" + "\n".join(stock_lines) + "\n</candidates>"

    task_block = (
        "<task>\n"
        "  Select 10-15 high-conviction intraday candidates with direction and reasoning.\n"
        "  Use all factor scores and Jev AI scores (when present) to inform your selection.\n"
        "  Higher composite_score, volume_surge, and candlestick_pattern scores suggest stronger setups.\n"
        "</task>"
    )

    return f"{regime_block}{sector_block}\n\n{candidates_block}\n\n{task_block}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/analysis/test_prompts.py -v -k "shortlist_user_prompt" --tb=short`
Expected: All PASS.

- [ ] **Step 5: Run full prompt test suite to catch regressions**

Run: `python3 -m pytest tests/analysis/test_prompts.py -v --tb=short`
Expected: All PASS. If `test_build_shortlist_user_prompt` (old test) was replaced, no regression.

- [ ] **Step 6: Commit**

```bash
git add tradingbot/analysis/prompts.py tests/analysis/test_prompts.py
git commit -m "feat(prompts): XML-structured shortlist prompt with all factor scores and Jev data"
```

---

### Task 2: Rewrite `SHORTLIST_SYSTEM` — scoring rubric, self-check, few-shot example

**Files:**
- Modify: `tradingbot/analysis/prompts.py:119-133` (`SHORTLIST_SYSTEM` constant)
- Test: `tests/analysis/test_prompts.py` (update content checks + add new tests)

**Interfaces:**
- Consumes: nothing (static string constant)
- Produces: `str` — system prompt consumed by `tier2_analyzer.py:93`

- [ ] **Step 1: Write failing tests for new system prompt features**

```python
def test_shortlist_system_has_xml_output_instruction():
    assert "<analysis>" in SHORTLIST_SYSTEM or "XML" in SHORTLIST_SYSTEM or "analysis" in SHORTLIST_SYSTEM.lower()


def test_shortlist_system_has_rubric():
    assert "Regime Alignment" in SHORTLIST_SYSTEM or "regime alignment" in SHORTLIST_SYSTEM.lower()
    assert "Volume" in SHORTLIST_SYSTEM
    assert "Risk:Reward" in SHORTLIST_SYSTEM or "risk:reward" in SHORTLIST_SYSTEM.lower() or "risk-reward" in SHORTLIST_SYSTEM.lower()


def test_shortlist_system_has_self_check():
    assert "verify" in SHORTLIST_SYSTEM.lower() or "self-check" in SHORTLIST_SYSTEM.lower() or "before finalizing" in SHORTLIST_SYSTEM.lower()


def test_shortlist_system_has_example():
    assert "<example>" in SHORTLIST_SYSTEM or "Example:" in SHORTLIST_SYSTEM or "EXAMPLE" in SHORTLIST_SYSTEM


def test_shortlist_system_has_scoring_weights():
    # Rubric should mention percentage weights or point allocations
    assert "%" in SHORTLIST_SYSTEM or "weight" in SHORTLIST_SYSTEM.lower() or "points" in SHORTLIST_SYSTEM.lower()


def test_shortlist_system_counter_argument():
    # Preserve existing behavior
    assert "counter" in SHORTLIST_SYSTEM.lower() or "COUNTER" in SHORTLIST_SYSTEM
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/analysis/test_prompts.py -v -k "shortlist_system" --tb=short`
Expected: FAIL — current system prompt lacks rubric, self-check, example.

- [ ] **Step 3: Implement the new `SHORTLIST_SYSTEM`**

Replace the constant at `prompts.py:119-133` with:

```python
SHORTLIST_SYSTEM = (
    "You are a senior proprietary trader at a top Indian brokerage with 15 years "
    "of NSE intraday experience managing institutional capital.\n\n"

    "## Task\n"
    "From the scored stock list in <candidates>, select 10-15 high-conviction "
    "intraday candidates. Include BOTH long AND short opportunities — individual "
    "stocks can have strong setups regardless of the broader market regime.\n\n"

    "## Scoring Rubric (evaluate each candidate on these criteria)\n"
    "1. **Regime Alignment (25%)** — Does the stock's setup match the current "
    "market regime and sector momentum? A long in a trending_up regime with "
    "strong sector_momentum scores higher.\n"
    "2. **Volume & Delivery Conviction (25%)** — High volume_surge + high "
    "delivery_pct = institutional participation. Low volume = avoid.\n"
    "3. **Technical Setup Quality (25%)** — Combine price_structure, "
    "candlestick_pattern, and atr_expansion. Strong patterns at key levels "
    "with expanding ATR = actionable.\n"
    "4. **Risk:Reward (25%)** — Based on price_structure and gap_analysis, "
    "is there a clear 2:1+ R:R? Tight stops with room to run.\n\n"

    "When Jev AI scores are present (jev_composite, jev_setup_confidence), "
    "use them as a confirming signal. jev_composite > 0.6 = strong AI conviction. "
    "Disagreement between your analysis and Jev should be noted in reasoning.\n\n"

    "## Process\n"
    "1. Read <regime> to understand the market environment.\n"
    "2. Scan all <candidates> using the rubric above.\n"
    "3. For each pick, explain WHY this stock today — what specific setup or "
    "catalyst makes it actionable, not just that it scores well.\n"
    "4. For each pick, state the strongest COUNTER-ARGUMENT — the bear case "
    "for longs, the bull case for shorts.\n"
    "5. **Self-check before finalizing:** Review your shortlist and remove any "
    "pick that fails 2+ rubric criteria. Verify you have both long and short "
    "candidates. Confirm at least 5 remain.\n\n"

    "## Rules\n"
    "- Use ONLY the data provided. Do NOT invent price levels, volumes, or news.\n"
    "- Confidence: high = would bet own capital. medium = worth watching.\n"
    "- Do not include low-conviction picks.\n"
    "- You MUST return at least 5 candidates.\n\n"

    "## Example\n"
    "<example>\n"
    "Given: HDFCBANK with composite_score=88, vol_surge=85, RS=72, "
    "candlestick_pattern=90, price_structure=78, delivery_pct=65, "
    "sector_momentum=80, regime=trending_up\n\n"
    "Analysis:\n"
    "- Regime Alignment: Strong — banking sector in play, trending_up regime "
    "favors quality longs. sector_momentum=80 confirms. (Score: high)\n"
    "- Volume: vol_surge=85 with delivery_pct=65 suggests institutional buying, "
    "not just retail churn. (Score: high)\n"
    "- Technical: candlestick_pattern=90 (bullish engulfing at support), "
    "price_structure=78 (clear support/resistance). (Score: high)\n"
    "- Risk:Reward: Price near support with resistance 2.5% away, stop 0.8% "
    "below = 3:1 R:R. (Score: high)\n\n"
    "Decision: LONG, conviction=high. Primary strategy: breakout_momentum.\n"
    "Counter-argument: RSI at 68 approaching overbought; a failed breakout "
    "above resistance traps longs with a fast reversal.\n"
    "</example>"
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/analysis/test_prompts.py -v -k "shortlist_system" --tb=short`
Expected: All PASS.

- [ ] **Step 5: Run full prompt test suite**

Run: `python3 -m pytest tests/analysis/test_prompts.py -v --tb=short`
Expected: All PASS. The existing `test_shortlist_prompt_counter_argument` should still pass since "counter" is still in the prompt.

- [ ] **Step 6: Verify prompt token size is reasonable**

```bash
python3 -c "
from tradingbot.analysis.prompts import SHORTLIST_SYSTEM, build_shortlist_user_prompt
stocks = [{'symbol': f'STOCK{i}', 'composite_score': 80-i, 'sector': 'banking',
           'last_price': 1000+i*10, 'factor_scores': {
               'volume_surge': 70, 'relative_strength': 65, 'atr_expansion': 55,
               'price_structure': 72, 'delivery_pct': 60, 'sector_momentum': 75,
               'gap_analysis': 45, 'candlestick_pattern': 80, 'volume_profile': 68,
           }, 'jev_composite': 0.72, 'jev_setup_confidence': 0.81} for i in range(30)]
regime = {'regime': 'trending_up', 'regime_confidence': 0.82, 'bias': 'bullish',
          'sectors_in_play': ['banking', 'IT'], 'sectors_to_avoid': ['pharma'],
          'risk_appetite': 'moderate'}
user = build_shortlist_user_prompt(regime, {}, stocks)
# Rough token estimate: ~4 chars per token
sys_tokens = len(SHORTLIST_SYSTEM) / 4
user_tokens = len(user) / 4
print(f'System prompt: ~{sys_tokens:.0f} tokens ({len(SHORTLIST_SYSTEM)} chars)')
print(f'User prompt (30 stocks): ~{user_tokens:.0f} tokens ({len(user)} chars)')
print(f'Total: ~{sys_tokens + user_tokens:.0f} tokens')
"
```

Expected: Total under 5K tokens (well within Claude's context).

- [ ] **Step 7: Commit**

```bash
git add tradingbot/analysis/prompts.py tests/analysis/test_prompts.py
git commit -m "feat(prompts): add scoring rubric, self-check, and few-shot example to shortlist system prompt"
```
