#!/usr/bin/env bash
# Staged manual analysis: `fetch` step. Usage: fetch.sh [YYYY-MM-DD]  (date defaults to the next session)
cd "$(dirname "$0")/../.." || exit 1
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then set -- --date "$@"; fi
exec "${PYTHON:-.venv/bin/python}" -m tradingbot pipeline fetch "$@"
