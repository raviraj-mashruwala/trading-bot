from datetime import time

import pytest

from tradingbot.core.config import StrategyConfig
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import (
    BacktestResult,
    Direction,
    EntryType,
    IndicatorSnapshot,
    MarketContext,
    MarketRegime,
    ShortlistedStock,
    StrategyName,
)
from tradingbot.strategy.strategy_selector import StrategySelector


class StubProvider(LLMProvider):
    def __init__(self, payload):
        self.payload = payload
        self.last_user_prompt = None
        self.call_count = 0

    async def analyze(self, system_prompt, user_prompt, tool_name, tool_description, input_schema):
        self.call_count += 1
        self.last_user_prompt = user_prompt
        return self.payload

    async def health_check(self):
        return True


def make_config() -> StrategyConfig:
    return StrategyConfig(
        backtest_days=30,
        candle_interval="15minute",
        min_confidence=0.5,
        min_reward_risk=1.5,
        max_trades_per_day=2,
    )


def make_context() -> MarketContext:
    return MarketContext(
        nifty_level=25400.0,
        nifty_trend="bullish",
        banknifty_trend="bullish",
        india_vix=12.5,
        fii_net_cr=2300.0,
        dii_net_cr=-800.0,
        global_cues="US flat",
        sector_leaders=["IT"],
        sector_laggards=["FMCG"],
        regime=MarketRegime.TRENDING_UP,
    )


def make_shortlist(*symbols):
    return [
        ShortlistedStock(
            symbol=symbol,
            reasoning="Candidate.",
            suggested_strategy=StrategyName.BREAKOUT,
            direction_bias="long",
            key_levels=[100.0],
        )
        for symbol in symbols
    ]


def make_snapshot(symbol) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol=symbol,
        last_close=100.0,
        rsi_14=58.0,
        macd=0.5,
        macd_signal=0.2,
        bb_upper=108.0,
        bb_middle=100.0,
        bb_lower=92.0,
        atr_14=2.0,
        sma_20=98.0,
        sma_50=95.0,
        sma_200=90.0,
        ema_12=99.0,
        ema_26=97.0,
        vwap=99.0,
        pivot=100.0,
        support_levels=[95.0],
        resistance_levels=[105.0],
    )


def make_backtests(symbol):
    return [
        BacktestResult(
            symbol=symbol,
            strategy=StrategyName.BREAKOUT,
            trades=20,
            wins=12,
            win_rate=0.6,
            avg_reward_risk=2.0,
        )
    ]


def setup_payload(symbol, **overrides):
    item = {
        "symbol": symbol,
        "strategy": "breakout",
        "direction": "long",
        "entry_price": 100.0,
        "entry_type": "limit",
        "stop_loss": 98.0,
        "target_1": 104.0,
        "target_2": 106.0,
        "entry_window_start": "09:30",
        "entry_window_end": "10:30",
        "confidence": 0.72,
        "reasoning": "Clean breakout setup.",
    }
    item.update(overrides)
    return item


async def test_design_setups_maps_the_payload_to_trade_setups():
    provider = StubProvider({"setups": [setup_payload("RELIANCE")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert len(setups) == 1
    setup = setups[0]
    assert setup.symbol == "RELIANCE"
    assert setup.strategy is StrategyName.BREAKOUT
    assert setup.direction is Direction.LONG
    assert setup.entry_type is EntryType.LIMIT
    assert setup.entry_window_start == time(9, 30)
    assert setup.confidence == pytest.approx(0.72)


async def test_all_shortlisted_stocks_go_out_in_a_single_llm_call():
    provider = StubProvider({"setups": []})
    selector = StrategySelector(provider, make_config())

    await selector.design_setups(
        make_shortlist("RELIANCE", "TCS", "INFY"),
        {symbol: make_snapshot(symbol) for symbol in ("RELIANCE", "TCS", "INFY")},
        {symbol: make_backtests(symbol) for symbol in ("RELIANCE", "TCS", "INFY")},
        make_context(),
    )

    assert provider.call_count == 1
    assert "RELIANCE" in provider.last_user_prompt
    assert "TCS" in provider.last_user_prompt
    assert "INFY" in provider.last_user_prompt


async def test_a_setup_for_a_symbol_outside_the_shortlist_is_dropped():
    provider = StubProvider(
        {"setups": [setup_payload("RELIANCE"), setup_payload("HALLUCINATED")]}
    )
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert [setup.symbol for setup in setups] == ["RELIANCE"]


async def test_a_setup_with_an_unknown_strategy_is_dropped():
    provider = StubProvider({"setups": [setup_payload("RELIANCE", strategy="astrology")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert setups == []


async def test_a_setup_with_a_malformed_time_window_is_dropped():
    provider = StubProvider({"setups": [setup_payload("RELIANCE", entry_window_start="morning")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert setups == []


async def test_a_setup_with_a_non_numeric_price_is_dropped():
    provider = StubProvider({"setups": [setup_payload("RELIANCE", entry_price="about a hundred")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert setups == []


async def test_the_prompt_carries_indicator_values_and_backtest_evidence():
    provider = StubProvider({"setups": []})
    selector = StrategySelector(provider, make_config())

    await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    prompt = provider.last_user_prompt
    assert "RSI" in prompt
    assert "58" in prompt
    assert "breakout" in prompt
    assert "60" in prompt  # the 60% backtest win rate


async def test_an_empty_shortlist_skips_the_llm_call():
    provider = StubProvider({"setups": [setup_payload("GHOST")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups([], {}, {}, make_context())

    assert setups == []
    assert provider.call_count == 0
