import pytest

from tradingbot.core.config import ScannerConfig
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import MarketContext, MarketRegime, Stock, StrategyName
from tradingbot.scanner.market_analyzer import MarketAnalyzer


class StubProvider(LLMProvider):
    def __init__(self, payload):
        self.payload = payload
        self.last_user_prompt = None
        self.last_schema = None

    async def analyze(self, system_prompt, user_prompt, tool_name, tool_description, input_schema):
        self.last_user_prompt = user_prompt
        self.last_schema = input_schema
        return self.payload

    async def health_check(self):
        return True


def make_config(llm_pick_count=15) -> ScannerConfig:
    return ScannerConfig(
        min_volume=500000,
        min_price=50.0,
        max_price=5000.0,
        min_market_cap_cr=5000.0,
        min_atr_pct=0.5,
        max_stocks_to_llm=100,
        llm_pick_count=llm_pick_count,
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
        regime=MarketRegime.TRENDING,
    )


def make_stocks(*symbols) -> list[Stock]:
    return [
        Stock(
            symbol=symbol,
            exchange="NSE",
            last_price=100.0,
            avg_volume=1_000_000.0,
            market_cap_cr=50000.0,
            atr_pct=1.2,
            sector="IT",
        )
        for symbol in symbols
    ]


async def test_shortlist_maps_the_llm_payload_to_dataclasses():
    provider = StubProvider(
        {
            "picks": [
                {
                    "symbol": "RELIANCE",
                    "reasoning": "Consolidating near resistance.",
                    "suggested_strategy": "breakout",
                    "direction_bias": "long",
                    "key_levels": [2850.0, 2900.0],
                }
            ]
        }
    )
    analyzer = MarketAnalyzer(provider, make_config())

    picks = await analyzer.shortlist(make_stocks("RELIANCE", "TCS"), make_context())

    assert len(picks) == 1
    assert picks[0].symbol == "RELIANCE"
    assert picks[0].suggested_strategy is StrategyName.BREAKOUT
    assert picks[0].key_levels == [2850.0, 2900.0]


async def test_picks_not_present_in_the_candidate_pool_are_dropped():
    provider = StubProvider(
        {
            "picks": [
                {
                    "symbol": "RELIANCE",
                    "reasoning": "Real candidate.",
                    "suggested_strategy": "breakout",
                    "direction_bias": "long",
                    "key_levels": [2850.0],
                },
                {
                    "symbol": "NOTREAL",
                    "reasoning": "Hallucinated ticker.",
                    "suggested_strategy": "momentum",
                    "direction_bias": "long",
                    "key_levels": [100.0],
                },
            ]
        }
    )
    analyzer = MarketAnalyzer(provider, make_config())

    picks = await analyzer.shortlist(make_stocks("RELIANCE", "TCS"), make_context())

    assert [pick.symbol for pick in picks] == ["RELIANCE"]


async def test_picks_with_an_unknown_strategy_are_dropped():
    provider = StubProvider(
        {
            "picks": [
                {
                    "symbol": "TCS",
                    "reasoning": "Unknown strategy name.",
                    "suggested_strategy": "telepathy",
                    "direction_bias": "long",
                    "key_levels": [100.0],
                }
            ]
        }
    )
    analyzer = MarketAnalyzer(provider, make_config())

    assert await analyzer.shortlist(make_stocks("TCS"), make_context()) == []


async def test_the_prompt_lists_every_candidate_and_the_market_context():
    provider = StubProvider({"picks": []})
    analyzer = MarketAnalyzer(provider, make_config())

    await analyzer.shortlist(make_stocks("RELIANCE", "TCS"), make_context())

    assert "RELIANCE" in provider.last_user_prompt
    assert "TCS" in provider.last_user_prompt
    assert "25400" in provider.last_user_prompt
    assert "trending" in provider.last_user_prompt


async def test_the_result_is_capped_at_the_configured_pick_count():
    provider = StubProvider(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "reasoning": "Candidate.",
                    "suggested_strategy": "breakout",
                    "direction_bias": "long",
                    "key_levels": [100.0],
                }
                for symbol in ("A", "B", "C", "D")
            ]
        }
    )
    analyzer = MarketAnalyzer(provider, make_config(llm_pick_count=2))

    picks = await analyzer.shortlist(make_stocks("A", "B", "C", "D"), make_context())

    assert [pick.symbol for pick in picks] == ["A", "B"]


async def test_an_empty_candidate_pool_skips_the_llm_call():
    provider = StubProvider({"picks": [{"symbol": "GHOST", "reasoning": "x", "suggested_strategy": "orb", "direction_bias": "long", "key_levels": []}]})
    analyzer = MarketAnalyzer(provider, make_config())

    picks = await analyzer.shortlist([], make_context())

    assert picks == []
    assert provider.last_user_prompt is None
