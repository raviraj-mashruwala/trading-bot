"""Config CRUD routes."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.config import ConfigError, load_config
from tradingbot.core.models import Mode

router = APIRouter(prefix="/api")

PROVIDERS = [
    {"name": "anthropic", "models": ["claude-sonnet-5", "claude-haiku-4-5"]},
]


def _mask_secret(value: str) -> str:
    if not value or len(value) <= 6:
        return "***"
    return "***" + value[-3:]


def _config_to_dict(state: AppState) -> dict[str, Any]:
    config = state.config
    return {
        "general": {"mode": config.general.mode.value, "capital": config.general.capital, "log_level": config.general.log_level},
        "scanner": {
            "min_volume": config.scanner.min_volume, "min_price": config.scanner.min_price,
            "max_price": config.scanner.max_price, "min_market_cap_cr": config.scanner.min_market_cap_cr,
            "min_atr_pct": config.scanner.min_atr_pct, "max_stocks_to_llm": config.scanner.max_stocks_to_llm,
            "llm_pick_count": config.scanner.llm_pick_count,
        },
        "strategy": {
            "backtest_days": config.strategy.backtest_days, "candle_interval": config.strategy.candle_interval,
            "min_confidence": config.strategy.min_confidence, "min_reward_risk": config.strategy.min_reward_risk,
            "max_trades_per_day": config.strategy.max_trades_per_day,
        },
        "risk": {
            "max_risk_per_trade_pct": config.risk.max_risk_per_trade_pct,
            "max_daily_loss_pct": config.risk.max_daily_loss_pct,
            "max_capital_deployed_pct": config.risk.max_capital_deployed_pct,
            "max_concurrent_positions": config.risk.max_concurrent_positions,
        },
        "execution": {
            "entry_slippage_pct": config.execution.entry_slippage_pct,
            "square_off_time": config.execution.square_off_time.strftime("%H:%M"),
            "connection_timeout_sec": config.execution.connection_timeout_sec,
            "heartbeat_interval_sec": config.execution.heartbeat_interval_sec,
            "plan_max_age_hours": config.execution.plan_max_age_hours,
            "max_entry_price_drift_pct": config.execution.max_entry_price_drift_pct,
        },
        "llm": {
            "provider": config.llm.provider, "model": config.llm.model,
            "timeout_sec": config.llm.timeout_sec, "max_retries": config.llm.max_retries,
            "base_url": config.llm.base_url,
        },
        "paper": {"slippage_pct": config.paper.slippage_pct, "initial_capital": config.paper.initial_capital},
        "secrets": {
            "anthropic_api_key": _mask_secret(config.secrets.anthropic_api_key),
            "kite_api_key": _mask_secret(config.secrets.kite_api_key),
            "kite_api_secret": _mask_secret(config.secrets.kite_api_secret),
        },
    }


@router.get("/config")
async def get_config(request: Request):
    state: AppState = request.app.state.app_state
    return _config_to_dict(state)


@router.put("/config")
async def put_config(request: Request):
    state: AppState = request.app.state.app_state
    body = await request.json()

    config_path = Path(state.config_path)
    with config_path.open("rb") as f:
        existing = tomllib.load(f)

    if "general" in body and "mode" in body["general"]:
        try:
            Mode(body["general"]["mode"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid mode: {body['general']['mode']!r}")

    for section, values in body.items():
        if section == "secrets":
            continue
        if section not in existing:
            raise HTTPException(status_code=400, detail=f"unknown section: {section}")
        if isinstance(values, dict):
            existing[section].update(values)

    lines = []
    for section, values in existing.items():
        lines.append(f"[{section}]")
        for key, val in values.items():
            if isinstance(val, str):
                lines.append(f'{key} = "{val}"')
            elif isinstance(val, bool):
                lines.append(f"{key} = {'true' if val else 'false'}")
            elif isinstance(val, (int, float)):
                lines.append(f"{key} = {val}")
            else:
                lines.append(f'{key} = "{val}"')
        lines.append("")
    config_path.write_text("\n".join(lines))

    try:
        state.config = load_config(config_path)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"status": "updated"}


@router.get("/config/providers")
async def get_providers(request: Request):
    state: AppState = request.app.state.app_state
    result = []
    for p in PROVIDERS:
        if p["name"] == "anthropic":
            key = state.config.secrets.anthropic_api_key
        else:
            key = ""
        result.append({"name": p["name"], "has_key": bool(key), "models": p["models"]})
    return result


@router.post("/config/test-llm")
async def test_llm(request: Request):
    state: AppState = request.app.state.app_state
    try:
        from tradingbot.core.llm.anthropic_provider import build_provider
        provider = build_provider(state.config.llm, state.config.secrets)
        ok = await provider.health_check()
        return {"ok": ok}
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("LLM test failed")
        return {"ok": False, "error": "LLM connection test failed. Check API key and server logs."}
