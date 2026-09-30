"""Tests for capital-based automatic risk configuration."""

import pytest

from tradingbot.core.config import ConfigError, RiskConfig, auto_risk_config


class TestAutoRiskConfigTiers:
    """Each capital tier produces the documented risk parameters."""

    def test_micro_account_under_50k(self):
        rc = auto_risk_config(20_000.0)
        assert rc == RiskConfig(
            max_risk_per_trade_pct=0.015,
            max_daily_loss_pct=0.03,
            max_capital_deployed_pct=0.70,
            max_concurrent_positions=1,
        )

    def test_small_account_50k_to_200k(self):
        rc = auto_risk_config(100_000.0)
        assert rc == RiskConfig(
            max_risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.025,
            max_capital_deployed_pct=0.60,
            max_concurrent_positions=2,
        )

    def test_medium_account_200k_to_1m(self):
        rc = auto_risk_config(500_000.0)
        assert rc == RiskConfig(
            max_risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.02,
            max_capital_deployed_pct=0.50,
            max_concurrent_positions=2,
        )

    def test_large_account_above_1m(self):
        rc = auto_risk_config(2_000_000.0)
        assert rc == RiskConfig(
            max_risk_per_trade_pct=0.0075,
            max_daily_loss_pct=0.02,
            max_capital_deployed_pct=0.40,
            max_concurrent_positions=3,
        )


class TestAutoRiskConfigBoundaries:
    """Exact boundary values pick the higher tier (more conservative)."""

    def test_exactly_50k_is_small_tier(self):
        rc = auto_risk_config(50_000.0)
        assert rc.max_risk_per_trade_pct == 0.01
        assert rc.max_concurrent_positions == 2

    def test_exactly_200k_is_medium_tier(self):
        rc = auto_risk_config(200_000.0)
        assert rc.max_capital_deployed_pct == 0.50

    def test_exactly_1m_is_large_tier(self):
        rc = auto_risk_config(1_000_000.0)
        assert rc.max_risk_per_trade_pct == 0.0075


class TestAutoRiskConfigInvalid:
    """Zero and negative capital are rejected."""

    def test_zero_capital_raises(self):
        with pytest.raises(ConfigError, match="capital must be positive"):
            auto_risk_config(0)

    def test_negative_capital_raises(self):
        with pytest.raises(ConfigError, match="capital must be positive"):
            auto_risk_config(-10_000.0)
