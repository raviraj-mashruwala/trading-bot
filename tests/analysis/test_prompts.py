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
    assert "penalized" in ADVERSARIAL_SYSTEM.lower()
    assert "NOT to trade" in ADVERSARIAL_SYSTEM


def test_shortlist_prompt_counter_argument():
    assert "counter" in SHORTLIST_SYSTEM.lower() or "COUNTER" in SHORTLIST_SYSTEM


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


def test_build_shortlist_user_prompt():
    regime = {"regime": "trending_up", "regime_confidence": 0.82,
              "bias": "bullish", "sectors_in_play": ["banking"],
              "sectors_to_avoid": ["pharma"], "risk_appetite": "moderate"}
    stocks = [{"symbol": "RELIANCE", "composite_score": 85,
               "sector": "energy", "last_price": 2500,
               "factor_scores": {"volume_surge": 1.5, "relative_strength": 0.8}}]
    prompt = build_shortlist_user_prompt(regime, {}, stocks)
    assert "RELIANCE" in prompt
    assert "trending_up" in prompt
    assert "bullish" in prompt


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
        "What am I missing",
        "truly independent",
        "invalidate this trade",
        "Downgrade",
    ]:
        assert phrase in ADVERSARIAL_SYSTEM, f"Missing final_check phrase: {phrase!r}"
