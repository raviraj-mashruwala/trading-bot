from pathlib import Path

EXECUTOR_DIR = Path(__file__).resolve().parents[2] / "tradingbot" / "executor"


def test_executor_package_exists():
    assert EXECUTOR_DIR.is_dir()


def test_no_executor_module_imports_the_llm_package():
    # llm_escalator.py is the designated LLM integration point — exempt it
    allowed = {"llm_escalator.py"}
    offenders = []

    for path in EXECUTOR_DIR.rglob("*.py"):
        if path.name in allowed:
            continue
        source = path.read_text()
        if "tradingbot.core.llm" in source or "from anthropic" in source or "import anthropic" in source:
            offenders.append(path.name)

    assert offenders == [], (
        f"the executor must never depend on an LLM, but these files do: {offenders}"
    )
