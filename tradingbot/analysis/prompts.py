"""LLM prompt templates and JSON schemas for all analysis calls.

Provider-agnostic: works with OpenAI function calling and Anthropic tool_use.
Each prompt set has three parts:
  - *_SYSTEM: system prompt string
  - *_SCHEMA: JSON schema dict for structured output
  - *_TOOL: (name, description, schema) tuple for provider.analyze()
"""

from __future__ import annotations

from typing import Any

# ── Call 1: Market Regime ────────────────────────────────────────────────────

REGIME_SYSTEM = (
    "You are a senior proprietary trader at a top Indian brokerage with 15 years "
    "of NSE intraday experience managing institutional capital.\n\n"
    "Analyze the market data provided and determine the current market regime. "
    "Think step by step. Show your reasoning before conclusions.\n\n"
    "Use ONLY the data provided. Do NOT invent price levels, volumes, or news. "
    "If data is insufficient for a conclusion, say so and lower your confidence.\n\n"
    "Confidence calibration:\n"
    "- 0.8+ means you would bet your own capital on this read\n"
    "- 0.6-0.8 means directional lean but not high conviction\n"
    "- Below 0.6 means uncertain, recommend defensive positioning"
)

REGIME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "regime": {
            "type": "string",
            "enum": [
                "trending_up", "trending_down", "range_bound",
                "volatile", "low_vol_squeeze"
            ]
        },
        "regime_confidence": {"type": "number"},
        "bias": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "key_levels": {
            "type": "object",
            "properties": {
                "nifty_support": {"type": "number"},
                "nifty_resistance": {"type": "number"},
                "banknifty_support": {"type": "number"},
                "banknifty_resistance": {"type": "number"}
            },
            "required": ["nifty_support", "nifty_resistance", "banknifty_support", "banknifty_resistance"],
            "additionalProperties": False
        },
        "sectors_in_play": {
            "type": "array", "items": {"type": "string"}
        },
        "sectors_to_avoid": {
            "type": "array", "items": {"type": "string"}
        },
        "risk_appetite": {
            "type": "string", "enum": ["aggressive", "moderate", "defensive"]
        },
        "session_expectation": {"type": "string"},
        "reasoning": {"type": "string"}
    },
    "required": [
        "regime", "regime_confidence", "bias", "key_levels",
        "sectors_in_play", "risk_appetite", "reasoning"
    ],
    "additionalProperties": False
}

REGIME_TOOL = ("submit_regime_analysis", "Submit market regime analysis", REGIME_SCHEMA)

# ── Call 2: Sector Deep-Dive ─────────────────────────────────────────────────

SECTOR_SYSTEM = (
    "You are a senior proprietary trader at a top Indian brokerage with 15 years "
    "of NSE intraday experience managing institutional capital.\n\n"
    "Analyze the sector data provided in the context of the market regime. "
    "Identify which sectors offer the best intraday opportunities today.\n\n"
    "Think step by step. Use ONLY the data provided. Do NOT invent sector "
    "movements or news catalysts. If you see correlations between sectors, "
    "flag them to avoid doubled exposure.\n\n"
    "For each pick, state the strongest COUNTER-ARGUMENT against the thesis."
)

SECTOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sectors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "theme": {"type": "string"},
                    "intraday_bias": {
                        "type": "string",
                        "enum": ["bullish", "bearish", "neutral"]
                    },
                    "catalyst": {"type": "string"}
                },
                "required": ["name", "intraday_bias", "theme", "catalyst"],
                "additionalProperties": False
            }
        },
        "sector_pairs": {"type": "array", "items": {"type": "string"}},
        "sector_divergences": {"type": "array", "items": {"type": "string"}},
        "cross_sector_picks": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"}
    },
    "required": ["sectors", "reasoning"],
    "additionalProperties": False
}

SECTOR_TOOL = ("submit_sector_analysis", "Submit sector analysis", SECTOR_SCHEMA)

# ── Call 3: Candidate Shortlisting ───────────────────────────────────────────

SHORTLIST_SYSTEM = (
    "You are a senior proprietary trader at a top Indian brokerage with 15 years "
    "of NSE intraday experience managing institutional capital.\n\n"

    "## Task\n"
    "From the scored stock list in <candidates>, select 10-15 high-conviction "
    "intraday candidates. Include BOTH long AND short opportunities — individual "
    "stocks can have strong setups regardless of the broader market regime.\n\n"

    "## Scoring Rubric (evaluate each candidate on these criteria)\n"
    "1. **Regime Alignment (25%)** — Consider the regime as context, not a "
    "direction filter. In trending_down, a stock up 15% with RSI>70 may be "
    "a high-conviction SHORT (mean-reversion/pullback) rather than a long. "
    "In trending_up, a beaten-down stock at support may be a long. Evaluate "
    "where the NEXT move is, not where the stock has been.\n"
    "2. **Volume & Delivery Conviction (25%)** — High volume_surge + high "
    "delivery_pct = institutional participation. Low volume = avoid.\n"
    "3. **Technical Setup Quality (25%)** — Combine price_structure, "
    "candlestick_pattern, and atr_expansion. Strong patterns at key levels "
    "with expanding ATR = actionable.\n"
    "4. **Setup Potential (25%)** — Based on price_structure, gap_analysis, "
    "and volume_profile, does this stock look like it has room to move? "
    "Stocks at extremes (far from VWAP/SMA, overbought/oversold) or at "
    "key levels (breakout/breakdown) have higher potential. Exact R:R "
    "is assessed later with intraday data — at this stage, focus on "
    "whether a meaningful move is plausible.\n\n"


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
    "</example>\n\n"
    "<example>\n"
    "Given: TATAMOTORS with composite_score=82, vol_surge=78, RS=88, "
    "RSI=81, candlestick_pattern=75, price_structure=72, delivery_pct=45, "
    "sector_momentum=60, regime=trending_down\n\n"
    "Analysis:\n"
    "- Regime: trending_down — stock up 12% against the trend, overbought. "
    "This is a reversal/short candidate, not a continuation long. (Score: high)\n"
    "- Volume: vol_surge=78 but delivery_pct=45 — speculative, not institutional. "
    "Suggestive of retail chase. (Score: medium)\n"
    "- Technical: RSI=81 overbought, extended above VWAP, potential "
    "double-top forming at resistance. (Score: high for short)\n"
    "- Risk:Reward: Short entry near resistance with stop above high, "
    "target VWAP = 2.5:1 R:R. (Score: high)\n\n"
    "Decision: SHORT, conviction=high. Primary strategy: mean_reversion.\n"
    "Counter-argument: Strong ADX could mean trend continuation; if stock "
    "breaks above resistance with volume, the short is invalidated.\n"
    "</example>"
)

SHORTLIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shortlist": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "direction": {
                        "type": "string", "enum": ["long", "short"]
                    },
                    "conviction": {
                        "type": "string", "enum": ["high", "medium"]
                    },
                    "primary_strategy": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "key_levels": {
                        "type": "object",
                        "properties": {
                            "support": {"type": "number"},
                            "resistance": {"type": "number"},
                            "vwap": {"type": "number"}
                        },
                        "required": ["support", "resistance", "vwap"],
                        "additionalProperties": False
                    },
                    "risk_flag": {"type": "string"},
                    "counter_argument": {"type": "string"}
                },
                "required": ["symbol", "direction", "conviction", "reasoning", "primary_strategy", "key_levels", "risk_flag", "counter_argument"],
                "additionalProperties": False
            }
        },
        "avoid_list": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["symbol", "reason"],
                "additionalProperties": False
            }
        },
        "max_positions_today": {"type": "integer"},
        "reasoning": {"type": "string"}
    },
    "required": ["shortlist", "max_positions_today", "reasoning"],
    "additionalProperties": False
}

SHORTLIST_TOOL = ("submit_shortlist", "Submit candidate shortlist", SHORTLIST_SCHEMA)

# ── Call 4: Per-Stock Deep Analysis ──────────────────────────────────────────

DEEP_ANALYSIS_SYSTEM = (
    "You are an expert intraday trading strategist with 15 years of NSE experience. "
    "Design precise trade setups based on the multi-timeframe data provided.\n\n"
    "Rules:\n"
    "1. Only propose setups with 3+ independent confirming signals across different "
    "timeframes or indicator types (confluence). Volume + RSI + VWAP = 3 signals. "
    "RSI + Stochastic = 1 signal (both momentum oscillators).\n"
    "2. Minimum reward:risk of 1.5:1 to target_1. If you cannot find that, return "
    "no_trade_reason instead of forcing a setup.\n"
    "3. Entry, stop loss, and targets MUST align with actual support/resistance, "
    "pivot, or VWAP levels from the data. Do NOT round to convenient numbers.\n"
    "4. Do NOT guess or invent price levels. Use ONLY levels visible in the data.\n\n"
    "Think step by step.\n\n"
    "Confidence calibration:\n"
    "- 0.8+ means you would bet your own capital\n"
    "- 0.6-0.8 means worth taking with reduced size\n"
    "- Below 0.6 means skip -- return no_trade_reason\n\n"
    "For each setup, state the invalidation condition -- the specific price action "
    "that kills the trade thesis.\n\n"
    "State the strongest COUNTER-ARGUMENT against each setup.\n\n"
    "If a <performance_context> block is provided, factor it into your "
    "confidence scoring. Strategies that underperform in the current regime "
    "deserve lower confidence. If your confidence calibration shows systematic "
    "overconfidence in a bucket, adjust downward."
)

DEEP_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
        "setups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string"},
                    "direction": {
                        "type": "string", "enum": ["long", "short"]
                    },
                    "entry_trigger": {"type": "string"},
                    "entry_price": {"type": "number"},
                    "stop_loss": {"type": "number"},
                    "target_1": {"type": "number"},
                    "target_2": {"type": "number"},
                    "position_size_hint": {
                        "type": "string", "enum": ["0.5x", "1x", "1.5x"]
                    },
                    "entry_window": {"type": "string"},
                    "exit_deadline": {"type": "string"},
                    "confidence": {
                        "type": "number"
                    },
                    "edge_description": {"type": "string"},
                    "invalidation": {"type": "string"},
                    "bear_case": {"type": "string"},
                    "confluence_count": {"type": "integer"},
                    "timeframe_alignment": {
                        "type": "array", "items": {"type": "string"}
                    }
                },
                "required": [
                    "strategy", "direction", "entry_trigger", "entry_price", "stop_loss",
                    "target_1", "target_2", "position_size_hint", "entry_window",
                    "exit_deadline", "confidence", "edge_description",
                    "invalidation", "bear_case", "confluence_count", "timeframe_alignment"
                ],
                "additionalProperties": False
            }
        },
        "no_trade_reason": {"type": ["string", "null"]}
    },
    "required": ["symbol", "setups", "no_trade_reason"],
    "additionalProperties": False
}

DEEP_ANALYSIS_TOOL = (
    "submit_deep_analysis", "Submit per-stock deep analysis", DEEP_ANALYSIS_SCHEMA,
)

# ── Call 5: Adversarial Validation ───────────────────────────────────────────

ADVERSARIAL_SYSTEM = (
    "You are a RISK MANAGER reviewing proposed trades. Your goal is quality "
    "control, not rejection maximization. Approve setups that have a valid "
    "edge; reject only with specific evidence of a flaw.\n\n"
    "Review the portfolio:\n"
    "1. Check correlation — flag if multiple stocks from the same sector\n"
    "2. Verify stop losses make sense (not inside normal ATR noise)\n"
    "3. Verify entry prices are realistic given current market prices\n"
    "4. Check that confluence signals are truly independent\n\n"
    "Think step by step.\n\n"
    "Approve with 'strong' if the setup has 3+ independent signals and "
    "clear risk/reward. Approve with 'conditional' if minor adjustments "
    "would improve it. Reject only if you can name a specific flaw that "
    "makes the trade likely to lose — not just uncertainty or caution.\n\n"
    "A setup that goes against the broad market regime is NOT automatically "
    "wrong — individual stocks can buck the trend. Judge the stock's own "
    "data, not the regime alone."
)

ADVERSARIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approved": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "setup_index": {"type": "integer"},
                    "approval": {
                        "type": "string", "enum": ["strong", "conditional"]
                    },
                    "adjustment": {"type": ["string", "null"]}
                },
                "required": ["symbol", "setup_index", "approval", "adjustment"],
                "additionalProperties": False
            }
        },
        "rejected": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "setup_index": {"type": "integer"},
                    "reason": {"type": "string"}
                },
                "required": ["symbol", "setup_index", "reason"],
                "additionalProperties": False
            }
        },
        "portfolio_risk_assessment": {
            "type": "object",
            "properties": {
                "total_setups": {"type": "integer"},
                "approved_count": {"type": "integer"},
                "max_correlated_exposure": {"type": "string"},
                "regime_alignment": {"type": "string"},
                "worst_case_loss": {"type": "string"},
                "recommendation": {"type": "string"}
            },
            "required": ["total_setups", "approved_count", "max_correlated_exposure", "regime_alignment", "worst_case_loss", "recommendation"],
            "additionalProperties": False
        }
    },
    "required": ["approved", "rejected", "portfolio_risk_assessment"],
    "additionalProperties": False
}

ADVERSARIAL_TOOL = (
    "submit_validation", "Submit adversarial portfolio validation", ADVERSARIAL_SCHEMA,
)

# ── User prompt builders ─────────────────────────────────────────────────────


def build_regime_user_prompt(
    nifty: float,
    banknifty: float,
    vix: float,
    nifty_5d_change: float,
    fii_5d_net: float,
    dii_5d_net: float,
    advance_decline: float,
    sector_data: dict[str, float],
) -> str:
    """Build user prompt for market regime analysis."""
    sectors = "\n".join(f"  {k}: {v:+.1f}%" for k, v in sector_data.items())
    return (
        f"Market Data (as of today):\n"
        f"  Nifty 50: {nifty:.0f} (5-day change: {nifty_5d_change:+.1f}%)\n"
        f"  Bank Nifty: {banknifty:.0f}\n"
        f"  India VIX: {vix:.1f}\n"
        f"  FII net (5-day): ₹{fii_5d_net:.0f} Cr\n"
        f"  DII net (5-day): ₹{dii_5d_net:.0f} Cr\n"
        f"  Advance/Decline ratio: {advance_decline:.2f}\n\n"
        f"Sector Performance (today):\n{sectors}\n\n"
        f"Determine the market regime and trading bias for today's session."
    )


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
    for s in scored_stocks[:50]:
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
        sig = s.get("signals")
        if sig:
            parts.append(
                f"    change_1d={sig.get('change_1d_pct', 0):+.1f}%, "
                f"change_5d={sig.get('change_5d_pct', 0):+.1f}%, "
                f"rsi14={sig.get('rsi_14', 50):.0f}, "
                f"vs_sma20={sig.get('vs_sma20_pct', 0):+.1f}%, "
                f"from_20d_high={sig.get('from_20d_high_pct', 0):+.1f}%, "
                f"gap={sig.get('gap_pct', 0):+.1f}%, "
                f"vol_ratio={sig.get('vol_ratio', 0):.1f}"
            )
        parts.append("  </stock>")
        stock_lines.append("\n".join(parts))

    candidates_block = "<candidates>\n" + "\n".join(stock_lines) + "\n</candidates>"

    task_block = (
        "<task>\n"
        "  Select 10-15 high-conviction intraday candidates with direction and reasoning.\n"
        "  Higher factor scores mean stronger signal magnitude in EITHER direction — a stock\n"
        "  with high scores may be a strong long OR a strong short candidate. Evaluate the\n"
        "  indicators to determine which direction makes sense, not just the score value.\n"
        "  The signed lines (change_*, rsi14, vs_sma20, from_20d_high, gap) give direction and how\n"
        "  far a stock has already moved; the factor scores give strength only. A stock already extended\n"
        "  far down (RSI under 30, far below its 20-day high) is not a long just because its scores are\n"
        "  high: pick it only if you can say why it keeps falling or reverses today.\n"
        "  Note: factor scores of exactly 50.0 may indicate unavailable data — treat as neutral, not as signal.\n"
        "</task>"
    )

    return f"{regime_block}{sector_block}\n\n{candidates_block}\n\n{task_block}"


def build_deep_analysis_user_prompt(
    symbol: str,
    direction: str,
    regime: dict,
    indicators: dict,
    backtest_results: list[dict],
    price_action_summary: str,
    performance_context: str = "",
) -> str:
    """Build user prompt for per-stock deep analysis."""
    bt_text = "\n".join(
        f"  {b['strategy']}: {b['total_trades']} trades, "
        f"win_rate={b['win_rate']:.0%}, PF={b['profit_factor']:.1f}, "
        f"expectancy_r={b['expectancy_r']:.2f}"
        for b in backtest_results
    )
    if not bt_text:
        bt_text = "  No prior backtest data — propose setups based on indicator confluence."
    ind_text = "\n".join(
        f"  {k}: {v}" for k, v in indicators.items() if not k.startswith("_")
    )
    return (
        f"Stock: {symbol} | Shortlist direction: {direction} (advisory — override if indicators disagree)\n"
        f"Market regime: {regime.get('regime', 'unknown')}\n\n"
        f"Technical Indicators (multi-timeframe):\n{ind_text}\n\n"
        f"Backtest Results:\n{bt_text}\n\n"
        f"Recent Price Action:\n{price_action_summary}\n\n"
        f"Design 1-3 precise trade setups with exact entry, stop loss, and target levels. "
        f"Only propose if you find 3+ confluence signals and 1.5:1 minimum R:R. "
        f"The shortlist direction is advisory. If indicators strongly favor the opposite "
        f"direction (e.g., overbought RSI + MACD bearish cross + extreme VWAP extension "
        f"= short, even if shortlist said long), propose the direction the data supports."
        + (f"\n\n<performance_context>\n{performance_context}\n</performance_context>"
           if performance_context else "")
    )
