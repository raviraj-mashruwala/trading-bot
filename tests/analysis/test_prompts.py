"""Tests for LLM prompt templates and JSON schemas."""

from tradingbot.analysis.prompts import (
    REGIME_SYSTEM, REGIME_SCHEMA, REGIME_TOOL,
    SECTOR_SYSTEM, SECTOR_SCHEMA, SECTOR_TOOL,
    SHORTLIST_SYSTEM, SHORTLIST_SCHEMA, SHORTLIST_TOOL,
    DEEP_ANALYSIS_SYSTEM, DEEP_ANALYSIS_SCHEMA, DEEP_ANALYSIS_TOOL,
    ADVERSARIAL_SYSTEM, ADVERSARIAL_SCHEMA, ADVERSARIAL_TOOL,
    build_regime_user_prompt, build_shortlist_user_prompt,
    build_deep_analysis_user_prompt,
)

ALL_SYSTEMS = [REGIME_SYSTEM, SECTOR_SYSTEM, SHORTLIST_SYSTEM,
               DEEP_ANALYSIS_SYSTEM, ADVERSARIAL_SYSTEM]
ALL_SCHEMAS = [REGIME_SCHEMA, SECTOR_SCHEMA, SHORTLIST_SCHEMA,
               DEEP_ANALYSIS_SCHEMA, ADVERSARIAL_SCHEMA]
ALL_TOOLS = [REGIME_TOOL, SECTOR_TOOL, SHORTLIST_TOOL,
             DEEP_ANALYSIS_TOOL, ADVERSARIAL_TOOL]


def test_all_system_prompts_are_strings():
    for prompt in ALL_SYSTEMS:
        assert isinstance(prompt, str)
        assert len(prompt) > 100


def test_all_schemas_are_valid_json_schema():
    for schema in ALL_SCHEMAS:
        assert isinstance(schema, dict)
        assert "type" in schema
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema


def test_all_tools_have_name_and_schema():
    for name, desc, schema in ALL_TOOLS:
        assert isinstance(name, str)
        assert isinstance(desc, str)
        assert isinstance(schema, dict)


# ── Prompt content checks ──


def test_regime_prompt_role_anchoring():
    assert "senior proprietary trader" in REGIME_SYSTEM.lower()
    assert "NSE" in REGIME_SYSTEM


def test_regime_prompt_chain_of_thought():
    assert "step by step" in REGIME_SYSTEM.lower()


def test_regime_prompt_anti_hallucination():
    assert "ONLY" in REGIME_SYSTEM
    assert "Do NOT invent" in REGIME_SYSTEM or "do not invent" in REGIME_SYSTEM.lower()


def test_regime_prompt_confidence_calibration():
    assert "0.8" in REGIME_SYSTEM
    assert "0.6" in REGIME_SYSTEM


def test_deep_analysis_prompt_requires_confluence():
    assert "confluence" in DEEP_ANALYSIS_SYSTEM.lower()
    assert "3+" in DEEP_ANALYSIS_SYSTEM or "3 " in DEEP_ANALYSIS_SYSTEM
    assert "1.5" in DEEP_ANALYSIS_SYSTEM  # R:R floor


def test_deep_analysis_prompt_requires_independent_signals():
    assert "independent" in DEEP_ANALYSIS_SYSTEM.lower()


def test_adversarial_prompt_is_adversarial():
    assert "RISK MANAGER" in ADVERSARIAL_SYSTEM
    assert "reject" in ADVERSARIAL_SYSTEM.lower()
    assert "quality" in ADVERSARIAL_SYSTEM.lower() or "flaw" in ADVERSARIAL_SYSTEM.lower()


def test_shortlist_prompt_counter_argument():
    assert "counter" in SHORTLIST_SYSTEM.lower() or "COUNTER" in SHORTLIST_SYSTEM


def test_shortlist_system_has_rubric():
    lower = SHORTLIST_SYSTEM.lower()
    assert "regime alignment" in lower
    assert "volume" in lower
    assert "risk" in lower


def test_shortlist_system_has_self_check():
    lower = SHORTLIST_SYSTEM.lower()
    assert "self-check" in lower or "before finalizing" in lower or "verify" in lower


def test_shortlist_system_has_example():
    assert "<example>" in SHORTLIST_SYSTEM or "Example" in SHORTLIST_SYSTEM


def test_shortlist_system_has_scoring_weights():
    assert "%" in SHORTLIST_SYSTEM or "weight" in SHORTLIST_SYSTEM.lower()


# ── Schema field checks ──


def test_regime_schema_has_enum():
    props = REGIME_SCHEMA["properties"]
    assert "regime" in props
    assert "enum" in props["regime"]
    assert "trending_up" in props["regime"]["enum"]
    assert "volatile" in props["regime"]["enum"]


def test_regime_schema_required_fields():
    required = REGIME_SCHEMA["required"]
    for field in ["regime", "regime_confidence", "bias", "key_levels",
                  "sectors_in_play", "risk_appetite", "reasoning"]:
        assert field in required


def test_shortlist_schema_structure():
    props = SHORTLIST_SCHEMA["properties"]
    assert "shortlist" in props
    assert props["shortlist"]["type"] == "array"
    item_props = props["shortlist"]["items"]["properties"]
    assert "symbol" in item_props
    assert "direction" in item_props
    assert "conviction" in item_props
    assert "counter_argument" in item_props


def test_deep_analysis_schema_setup_fields():
    setup_props = DEEP_ANALYSIS_SCHEMA["properties"]["setups"]["items"]["properties"]
    for field in ["strategy", "direction", "entry_price", "stop_loss",
                  "target_1", "confidence", "invalidation", "confluence_count"]:
        assert field in setup_props


def test_adversarial_schema_structure():
    props = ADVERSARIAL_SCHEMA["properties"]
    assert "approved" in props
    assert "rejected" in props
    assert "portfolio_risk_assessment" in props
    risk_required = props["portfolio_risk_assessment"]["properties"]
    assert "total_setups" in risk_required
    assert "approved_count" in risk_required
    assert "recommendation" in risk_required


# ── User prompt builder tests ──


def test_build_regime_user_prompt():
    prompt = build_regime_user_prompt(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=1.2, fii_5d_net=-500, dii_5d_net=800,
        advance_decline=1.4, sector_data={"banking": 1.5, "IT": -0.8},
    )
    assert "19500" in prompt
    assert "45000" in prompt
    assert "13.5" in prompt
    assert "-500" in prompt
    assert "banking" in prompt


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


def test_build_shortlist_user_prompt():
    regime = {"regime": "trending_up", "regime_confidence": 0.82,
              "bias": "bullish", "sectors_in_play": ["banking"],
              "sectors_to_avoid": ["pharma"], "risk_appetite": "moderate"}
    stocks = [_make_stock()]
    prompt = build_shortlist_user_prompt(regime, {}, stocks)
    assert "RELIANCE" in prompt
    assert "trending_up" in prompt
    assert "bullish" in prompt


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
    stocks = [_make_stock()]
    prompt = build_shortlist_user_prompt({"regime": "range_bound"}, {}, stocks)
    assert "RELIANCE" in prompt


def test_build_shortlist_user_prompt_caps_at_30():
    stocks = [_make_stock(symbol=f"STOCK{i}", composite=100 - i) for i in range(50)]
    prompt = build_shortlist_user_prompt({"regime": "range_bound"}, {}, stocks)
    assert "STOCK0" in prompt
    assert "STOCK29" in prompt
    assert "STOCK30" not in prompt


def test_build_shortlist_user_prompt_empty_stocks():
    prompt = build_shortlist_user_prompt({"regime": "range_bound"}, {}, [])
    assert "<candidates>" in prompt
    assert "</candidates>" in prompt


def test_build_deep_analysis_user_prompt():
    prompt = build_deep_analysis_user_prompt(
        symbol="RELIANCE", direction="long",
        regime={"regime": "trending_up"},
        indicators={"rsi_14": 45, "vwap": 2505},
        backtest_results=[{
            "strategy": "vwap_mean_reversion",
            "total_trades": 20, "win_rate": 0.65,
            "profit_factor": 2.1, "expectancy_r": 0.35,
        }],
        price_action_summary="3 day pullback to VWAP support",
    )
    assert "RELIANCE" in prompt
    assert "long" in prompt
    assert "rsi_14" in prompt
    assert "vwap_mean_reversion" in prompt
    assert "1.5:1" in prompt or "confluence" in prompt.lower()


def test_adversarial_system_contains_final_check_questions():
    for phrase in [
        "independent",
        "reject",
        "flaw",
    ]:
        assert phrase.lower() in ADVERSARIAL_SYSTEM.lower(), f"Missing phrase: {phrase!r}"
