"""Tests for mapping Claude's strategy names to generic strategies."""

from tradingbot.analysis.pipeline import _match_strategy
from tradingbot.core.models import StrategyName


def test_exact_match():
    assert _match_strategy("breakout") == StrategyName.BREAKOUT


def test_case_insensitive():
    assert _match_strategy("Mean_Reversion") == StrategyName.MEAN_REVERSION
    assert _match_strategy("BREAKOUT") == StrategyName.BREAKOUT


def test_fuzzy_match():
    assert _match_strategy("vwap_mean_reversion") == StrategyName.MEAN_REVERSION
    assert _match_strategy("rsi_divergence") == StrategyName.MEAN_REVERSION
    assert _match_strategy("trend_continuation") == StrategyName.MOMENTUM
    assert _match_strategy("support_bounce") == StrategyName.SUPPLY_DEMAND
    assert _match_strategy("resistance_rejection") == StrategyName.SUPPLY_DEMAND
    assert _match_strategy("pullback_entry") == StrategyName.MEAN_REVERSION


def test_unknown_returns_none():
    assert _match_strategy("quantum_flux_arbitrage") is None
    assert _match_strategy("") is None


def test_underscore_and_space_variants():
    assert _match_strategy("gap and go") == StrategyName.GAP_AND_GO
    assert _match_strategy("bollinger squeeze") == StrategyName.BOLLINGER_SQUEEZE
