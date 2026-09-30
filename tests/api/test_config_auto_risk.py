"""Test that the config API surfaces auto-derived risk info."""

from tradingbot.core.config import RiskConfig, auto_risk_config
from tradingbot.api.config_routes import _risk_response


def test_auto_derived_flags_when_all_match_auto():
    capital = 20_000.0
    auto = auto_risk_config(capital)
    result = _risk_response(auto, capital)

    assert result["max_risk_per_trade_pct"] == 0.015
    assert result["auto_derived"]["max_risk_per_trade_pct"] is True
    assert result["auto_derived"]["max_daily_loss_pct"] is True
    assert result["auto_derived"]["max_capital_deployed_pct"] is True
    assert result["auto_derived"]["max_concurrent_positions"] is True


def test_auto_derived_flags_when_one_overridden():
    capital = 20_000.0
    risk = RiskConfig(
        max_risk_per_trade_pct=0.015,
        max_daily_loss_pct=0.03,
        max_capital_deployed_pct=0.70,
        max_concurrent_positions=5,
    )
    result = _risk_response(risk, capital)

    assert result["auto_derived"]["max_risk_per_trade_pct"] is True
    assert result["auto_derived"]["max_concurrent_positions"] is False


def test_auto_derived_flags_when_all_overridden():
    capital = 20_000.0
    risk = RiskConfig(
        max_risk_per_trade_pct=0.005,
        max_daily_loss_pct=0.01,
        max_capital_deployed_pct=0.30,
        max_concurrent_positions=4,
    )
    result = _risk_response(risk, capital)

    assert all(v is False for v in result["auto_derived"].values())
