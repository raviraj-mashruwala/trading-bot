import pytest

from tradingbot.core.config import ScannerConfig
from tradingbot.core.models import Stock
from tradingbot.scanner.filters import apply_filters


def make_config(**overrides) -> ScannerConfig:
    defaults = {
        "min_volume": 500000,
        "min_price": 50.0,
        "max_price": 5000.0,
        "min_market_cap_cr": 5000.0,
        "min_atr_pct": 0.5,
        "max_stocks_to_llm": 100,
        "llm_pick_count": 15,
    }
    defaults.update(overrides)
    return ScannerConfig(**defaults)


def make_stock(
    symbol="RELIANCE",
    last_price=2855.0,
    avg_volume=2_000_000.0,
    market_cap_cr=1_900_000.0,
    atr_pct=1.4,
) -> Stock:
    return Stock(
        symbol=symbol,
        exchange="NSE",
        last_price=last_price,
        avg_volume=avg_volume,
        market_cap_cr=market_cap_cr,
        atr_pct=atr_pct,
        sector="Energy",
    )


def test_a_fully_qualified_stock_passes():
    result = apply_filters([make_stock()], make_config())

    assert [stock.symbol for stock in result.passed] == ["RELIANCE"]
    assert result.rejected == {}


def test_illiquid_stock_is_rejected_for_volume():
    result = apply_filters([make_stock(avg_volume=1000.0)], make_config())

    assert result.passed == []
    assert result.rejected == {"volume": 1}


def test_penny_stock_is_rejected_for_price():
    result = apply_filters([make_stock(last_price=12.0)], make_config())

    assert result.passed == []
    assert result.rejected == {"price": 1}


def test_very_expensive_stock_is_rejected_for_price():
    result = apply_filters([make_stock(last_price=9000.0)], make_config())

    assert result.passed == []
    assert result.rejected == {"price": 1}


def test_micro_cap_is_rejected_for_market_cap():
    result = apply_filters([make_stock(market_cap_cr=300.0)], make_config())

    assert result.passed == []
    assert result.rejected == {"market_cap": 1}


def test_stock_that_barely_moves_is_rejected_for_atr():
    result = apply_filters([make_stock(atr_pct=0.05)], make_config())

    assert result.passed == []
    assert result.rejected == {"atr": 1}


def test_boundary_values_are_inclusive():
    config = make_config(min_volume=1000, min_price=50.0, max_price=5000.0, min_market_cap_cr=5000.0, min_atr_pct=0.5)
    at_lower = make_stock(symbol="LOW", last_price=50.0, avg_volume=1000.0, market_cap_cr=5000.0, atr_pct=0.5)
    at_upper = make_stock(symbol="HIGH", last_price=5000.0)

    result = apply_filters([at_lower, at_upper], config)

    assert sorted(stock.symbol for stock in result.passed) == ["HIGH", "LOW"]


def test_each_stock_is_counted_under_its_first_failing_reason():
    stock = make_stock(avg_volume=10.0, last_price=5.0, market_cap_cr=1.0, atr_pct=0.0)

    result = apply_filters([stock], make_config())

    assert result.rejected == {"volume": 1}


def test_results_are_capped_at_max_stocks_to_llm_keeping_the_most_liquid():
    stocks = [
        make_stock(symbol=f"SYM{index}", avg_volume=1_000_000.0 + index)
        for index in range(10)
    ]

    result = apply_filters(stocks, make_config(max_stocks_to_llm=3))

    assert [stock.symbol for stock in result.passed] == ["SYM9", "SYM8", "SYM7"]


def test_an_empty_universe_produces_an_empty_result():
    result = apply_filters([], make_config())

    assert result.passed == []
    assert result.rejected == {}
