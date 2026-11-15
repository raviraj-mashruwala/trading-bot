import json
from pathlib import Path

from tradingbot.core.llm.queue_status import answered_payload, pending_requests


def add_request(queue: Path, rid: str, tool="submit_regime_analysis", created="2026-10-30T10:00:00+05:30"):
    (queue / "requests").mkdir(parents=True, exist_ok=True)
    (queue / "requests" / f"{rid}.json").write_text(
        json.dumps({"id": rid, "tool_name": tool, "created_at": created})
    )


def add_answer(queue: Path, rid: str, payload=None):
    (queue / "answers").mkdir(parents=True, exist_ok=True)
    (queue / "answers" / f"{rid}.json").write_text(json.dumps(payload or {"ok": True}))


def test_pending_lists_unanswered_requests_oldest_first(tmp_path):
    add_request(tmp_path, "bbb", created="2026-10-30T10:05:00+05:30")
    add_request(tmp_path, "aaa", created="2026-10-30T10:01:00+05:30")

    pending = pending_requests(tmp_path)

    assert [p.id for p in pending] == ["aaa", "bbb"]
    assert pending[0].tool_name == "submit_regime_analysis"
    assert pending[0].path == tmp_path / "requests" / "aaa.json"


def test_pending_ignores_answered_requests(tmp_path):
    add_request(tmp_path, "aaa")
    add_request(tmp_path, "bbb")
    add_answer(tmp_path, "aaa")

    assert [p.id for p in pending_requests(tmp_path)] == ["bbb"]


def test_pending_on_missing_dir_is_empty(tmp_path):
    assert pending_requests(tmp_path / "nope") == []


def test_pending_ignores_temp_files_from_atomic_writes(tmp_path):
    add_request(tmp_path, "aaa")
    (tmp_path / "requests" / ".bbb.tmp").write_text("{}")

    assert [p.id for p in pending_requests(tmp_path)] == ["aaa"]


def test_answered_payload_returns_the_answer_for_a_tool(tmp_path):
    add_request(tmp_path, "aaa", tool="submit_shortlist")
    add_answer(tmp_path, "aaa", {"shortlist": []})

    assert answered_payload(tmp_path, "submit_shortlist") == {"shortlist": []}


def test_answered_payload_is_none_when_unanswered_or_absent(tmp_path):
    add_request(tmp_path, "aaa", tool="submit_shortlist")

    assert answered_payload(tmp_path, "submit_shortlist") is None
    assert answered_payload(tmp_path / "nope", "submit_shortlist") is None


def test_pending_includes_requests_whose_answer_is_invalid(tmp_path):
    schema = {"type": "object", "required": ["picks"]}
    (tmp_path / "requests").mkdir(parents=True)
    (tmp_path / "requests" / "aaa.json").write_text(json.dumps({
        "id": "aaa", "tool_name": "t", "created_at": "2026-10-30T10:00:00+05:30",
        "input_schema": schema,
    }))
    add_answer(tmp_path, "aaa", {"wrong": 1})

    assert [p.id for p in pending_requests(tmp_path)] == ["aaa"]


def test_pending_includes_requests_whose_answer_is_not_json(tmp_path):
    add_request(tmp_path, "aaa")
    (tmp_path / "answers").mkdir()
    (tmp_path / "answers" / "aaa.json").write_text("{broken")

    assert [p.id for p in pending_requests(tmp_path)] == ["aaa"]
