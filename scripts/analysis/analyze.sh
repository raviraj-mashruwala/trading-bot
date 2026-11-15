#!/usr/bin/env bash
# Staged manual analysis: `analyze` step. Usage: analyze.sh [YYYY-MM-DD]  (date defaults to the next session)
# Exit codes: 0 plan written, 10 LLM answers needed, 11 run fetch.sh first, 1 error.
cd "$(dirname "$0")/../.." || exit 1
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then set -- --date "$@"; fi
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python.exe
exec "${PYTHON:-$PY}" -m tradingbot pipeline analyze "$@"
