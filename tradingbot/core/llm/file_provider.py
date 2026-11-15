"""LLM provider that takes its answers from files a Claude Code session writes.

Never waits. A missing answer writes the request file once and raises
AnswersNeeded, so the calling process can exit and be rerun after the answers
exist. Queue layout under queue_dir:

    requests/<id>.json    what to answer (prompts, tool name, input schema)
    answers/<id>.json     the bare tool-input object, written by the responder
    rejected/<id>.json    answers that failed validation, with <id>.reason.txt
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import jsonschema

from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import now_ist

logger = logging.getLogger(__name__)

# An unparseable answer younger than this may still be mid-write.
FRESH_FILE_SECONDS = 3.0


_current_step: ContextVar[str | None] = ContextVar("llm_step", default=None)


@contextmanager
def llm_step(name: str) -> Iterator[None]:
    """Name the pipeline step making the next LLM calls.

    Live inputs (index level, VIX, flows) drift between reruns, which would change
    a prompt-hash id and orphan an answer already written. Inside a step the
    request id depends on the tool and step only, so a rerun finds its answer.
    """
    token = _current_step.set(name)
    try:
        yield
    finally:
        _current_step.reset(token)


class AnswersNeeded(Exception):
    """One or more LLM requests have no valid answer yet."""

    def __init__(self, requests: list[Path]) -> None:
        self.requests = requests
        super().__init__(f"{len(requests)} LLM request(s) need answers")


def request_id(tool_name: str, system_prompt: str, user_prompt: str) -> str:
    digest = hashlib.sha256("\x00".join((tool_name, system_prompt, user_prompt)).encode())
    return digest.hexdigest()[:16]


class FileAnswerProvider(LLMProvider):
    def __init__(self, queue_dir: Path) -> None:
        self.queue_dir = Path(queue_dir)

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
    ) -> dict[str, Any]:
        step = _current_step.get()
        if step is not None:
            rid = request_id(tool_name, f"step:{step}", "")
        else:
            rid = request_id(tool_name, system_prompt, user_prompt)
        answer_path = self.queue_dir / "answers" / f"{rid}.json"

        if answer_path.exists():
            answer = self._read_valid_answer(answer_path, rid, input_schema)
            if answer is not None:
                return answer

        request_path = self._write_request_once(
            rid, system_prompt, user_prompt, tool_name, tool_description, input_schema, step,
        )
        raise AnswersNeeded([request_path])

    async def health_check(self) -> bool:
        try:
            self.queue_dir.mkdir(parents=True, exist_ok=True)
            probe = self.queue_dir / ".write-probe"
            probe.write_text("ok")
            probe.unlink()
        except OSError:
            return False
        return True

    def _read_valid_answer(
        self, path: Path, rid: str, input_schema: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return the answer, or None when it is unusable (pending or rejected)."""
        try:
            answer = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if time.time() - path.stat().st_mtime < FRESH_FILE_SECONDS:
                return None  # probably still being written
            self._reject(path, rid, f"not valid JSON: {exc}")
            return None

        try:
            jsonschema.validate(answer, input_schema)
        except jsonschema.ValidationError as exc:
            self._reject(path, rid, exc.message)
            return None
        return answer

    def _reject(self, path: Path, rid: str, reason: str) -> None:
        rejected = self.queue_dir / "rejected"
        rejected.mkdir(parents=True, exist_ok=True)
        os.replace(path, rejected / f"{rid}.json")
        (rejected / f"{rid}.reason.txt").write_text(reason + "\n")
        logger.warning("rejected LLM answer %s: %s", rid, reason)

    def _write_request_once(
        self,
        rid: str,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        step: str | None,
    ) -> Path:
        requests = self.queue_dir / "requests"
        requests.mkdir(parents=True, exist_ok=True)
        path = requests / f"{rid}.json"
        if path.exists():
            return path

        payload = {
            "id": rid,
            "tool_name": tool_name,
            "tool_description": tool_description,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "input_schema": input_schema,
            "created_at": now_ist().isoformat(),
            "step": step,
        }
        temporary = requests / f".{rid}.tmp"
        temporary.write_text(json.dumps(payload, indent=2))
        os.replace(temporary, path)
        logger.info("LLM answer needed: %s %s", tool_name, rid)
        return path
