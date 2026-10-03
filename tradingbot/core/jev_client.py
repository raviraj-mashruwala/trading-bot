"""Thin wrapper around TypeSafe's Jev SDK with graceful degradation."""

from __future__ import annotations

import logging
import os
import time as _time
from typing import Any

from tradingbot.core.config import JevConfig

log = logging.getLogger(__name__)

try:
    from typesafe_sdk import (
        AsyncTypeSafeClient,
        Choice,
        Noul,
        Score,
        TypeSafeClient,
    )
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    TypeSafeClient = None  # type: ignore[assignment,misc]
    AsyncTypeSafeClient = None  # type: ignore[assignment,misc]
    Choice = None  # type: ignore[assignment,misc]
    Noul = None  # type: ignore[assignment,misc]
    Score = None  # type: ignore[assignment,misc]


class JevClient:
    """Evaluate state + questions via TypeSafe Jev. Returns None on any failure."""

    def __init__(self, config: JevConfig) -> None:
        self._config = config
        self._api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        self._available = _SDK_AVAILABLE and bool(self._api_key) and config.enabled
        self._calls = 0
        self._total_latency_ms = 0.0

        if not _SDK_AVAILABLE:
            log.info("typesafe-sdk not installed — Jev disabled")
        elif not self._api_key:
            log.info("TYPESAFE_API_KEY not set — Jev disabled")
        elif not config.enabled:
            log.info("Jev disabled in config")

    @property
    def available(self) -> bool:
        return self._available

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any] | None:
        if not self._available:
            return None
        try:
            start = _time.monotonic()
            with TypeSafeClient(
                api_key=self._api_key,
                model=self._config.model,
            ) as client:
                response = client.system_one(state=state, questions=questions)
            elapsed_ms = (_time.monotonic() - start) * 1000
            self._calls += 1
            self._total_latency_ms += elapsed_ms
            log.debug("Jev call %d: %.0fms, %d answers",
                      self._calls, elapsed_ms, len(response.answers))
            return response.answers
        except Exception:
            log.warning("Jev evaluate failed", exc_info=True)
            return None

    async def aevaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any] | None:
        if not self._available:
            return None
        try:
            start = _time.monotonic()
            async with AsyncTypeSafeClient(
                api_key=self._api_key,
                model=self._config.model,
            ) as client:
                response = await client.system_one(state=state, questions=questions)
            elapsed_ms = (_time.monotonic() - start) * 1000
            self._calls += 1
            self._total_latency_ms += elapsed_ms
            log.debug("Jev async call %d: %.0fms", self._calls, elapsed_ms)
            return response.answers
        except Exception:
            log.warning("Jev aevaluate failed", exc_info=True)
            return None

    def stats(self) -> dict[str, Any]:
        return {
            "calls": self._calls,
            "total_latency_ms": self._total_latency_ms,
            "avg_latency_ms": (self._total_latency_ms / self._calls) if self._calls > 0 else 0.0,
        }
