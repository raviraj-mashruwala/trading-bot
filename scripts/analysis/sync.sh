#!/usr/bin/env bash
# Staged manual analysis: `sync` step. Pass --full to force a full initial fill.
cd "$(dirname "$0")/../.." || exit 1
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python.exe
exec "${PYTHON:-$PY}" -m tradingbot pipeline sync "$@"
