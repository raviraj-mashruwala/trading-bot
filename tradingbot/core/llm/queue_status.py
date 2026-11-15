"""Read-only view of the LLM request queue written by FileAnswerProvider."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema


@dataclass
class PendingRequest:
    id: str
    tool_name: str
    created_at: str
    path: Path


def _load_requests(queue_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    requests = Path(queue_dir) / "requests"
    if not requests.is_dir():
        return []
    loaded = []
    for path in requests.glob("*.json"):
        try:
            loaded.append((path, json.loads(path.read_text())))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(loaded, key=lambda item: item[1].get("created_at", ""))


def _valid_answer(queue_dir: Path, path: Path, request: dict[str, Any]) -> Any | None:
    """The parsed answer when one exists and satisfies the request's schema."""
    answer_path = Path(queue_dir) / "answers" / path.name
    try:
        answer = json.loads(answer_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    schema = request.get("input_schema")
    if schema is not None:
        try:
            jsonschema.validate(answer, schema)
        except jsonschema.ValidationError:
            return None
    return answer


def pending_requests(queue_dir: Path) -> list[PendingRequest]:
    """Requests with no usable answer, oldest first."""
    return [
        PendingRequest(
            id=request["id"], tool_name=request["tool_name"],
            created_at=request.get("created_at", ""), path=path,
        )
        for path, request in _load_requests(queue_dir)
        if _valid_answer(queue_dir, path, request) is None
    ]


def answered_payload(queue_dir: Path, tool_name: str) -> dict[str, Any] | None:
    """The newest usable answer for a tool, or None."""
    for path, request in reversed(_load_requests(queue_dir)):
        if request.get("tool_name") != tool_name:
            continue
        answer = _valid_answer(queue_dir, path, request)
        if answer is not None:
            return answer
    return None
