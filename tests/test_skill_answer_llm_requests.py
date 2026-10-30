from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "answer-llm-requests" / "SKILL.md"


@pytest.fixture(scope="module")
def text():
    assert SKILL.exists(), "skill file missing"
    return SKILL.read_text()


def test_front_matter_names_the_skill_and_its_trigger(text):
    front = text.split("---")[1]

    assert "name: answer-llm-requests" in front
    assert "pending LLM requests" in front
    assert "run the analysis" in front


@pytest.mark.parametrize("marker", [
    "scripts/analysis/analyze.sh",       # rule 2: drives the script itself
    "exit 0", "exit 1", "exit 10", "exit 11",
    "scripts/analysis/fetch.sh",
    "run_in_background",                 # fetch never blocks the conversation
    "never poll",
    "llm pending",                       # rule 3: lists what to answer
    "system_prompt", "user_prompt", "input_schema",
    "answers/<id>.json",                 # where the answer goes
    "rejected/<id>.reason.txt",          # rule 4: fix rejected answers
    "parallel subagents",                # rule 5
    "Never leave a script running",      # rule 6
    "scripts/analysis/review.sh",        # nightly review uses the same loop
    "nightly_review",
])
def test_skill_states_each_rule(text, marker):
    assert marker in text
