#!/usr/bin/env bash
# Staged manual analysis: `fetch` step. Usage: fetch.sh [YYYY-MM-DD]  (date defaults to the next session)
cd "$(dirname "$0")/../.." || exit 1
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then set -- --date "$@"; fi
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python.exe
exec "${PYTHON:-$PY}" -m tradingbot pipeline fetch "$@"
