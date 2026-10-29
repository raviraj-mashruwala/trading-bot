"""uvicorn server that can still be killed when the event loop is wedged."""

from __future__ import annotations

import os
from types import FrameType

import uvicorn


class ForceExitServer(uvicorn.Server):
    """A second signal exits immediately.

    The first signal only sets a flag that the event loop has to notice. When the
    loop is blocked it never does, so SIGTERM was ignored and only kill -9 worked.
    """

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if self.should_exit:
            os._exit(1)
        super().handle_exit(sig, frame)
