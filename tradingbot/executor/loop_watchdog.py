"""Detects a wedged execution loop from outside it.

The ticker watchdog runs on the execution loop itself, so a blocked loop also
silences the watchdog. This one runs on its own thread: the loop calls beat()
every pass, and if the beats stop it logs every thread's stack (the evidence
for finding the blocker) and alerts once.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from typing import Callable

logger = logging.getLogger(__name__)


class LoopWatchdog:
    def __init__(
        self,
        stall_seconds: float = 60.0,
        alert: Callable[[str], None] | None = None,
        check_interval: float = 5.0,
    ) -> None:
        self._stall_seconds = stall_seconds
        self._alert = alert
        self._check_interval = check_interval
        self._last_beat: float | None = None
        self._alerted = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def beat(self, now: float | None = None) -> None:
        self._last_beat = time.monotonic() if now is None else now
        self._alerted = False

    def check(self, now: float | None = None) -> bool:
        """Return True when this call detected a new stall."""
        last = self._last_beat
        if last is None or self._alerted:
            return False
        now = time.monotonic() if now is None else now
        stalled_for = now - last
        if stalled_for <= self._stall_seconds:
            return False
        self._alerted = True
        logger.error(
            "Execution loop has not progressed for %.0fs. Thread stacks:\n%s",
            stalled_for, _thread_stacks(),
        )
        if self._alert is not None:
            try:
                self._alert(f"Execution loop stalled for {stalled_for:.0f}s. Stacks are in the server log.")
            except Exception:
                logger.warning("stall alert delivery failed", exc_info=True)
        return True

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="loop-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self._check_interval):
            self.check()


def _thread_stacks() -> str:
    names = {t.ident: t.name for t in threading.enumerate()}
    blocks = []
    for ident, frame in sys._current_frames().items():
        stack = "".join(traceback.format_stack(frame))
        blocks.append(f"--- {names.get(ident, ident)} ---\n{stack}")
    return "\n".join(blocks)
