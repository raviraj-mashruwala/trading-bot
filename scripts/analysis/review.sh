#!/usr/bin/env bash
# Staged manual analysis: `review` step. Usage: review.sh [YYYY-MM-DD]  (defaults to the latest finished session)
# Exit codes: 0 review saved, 10 LLM answer needed, 1 error.
cd "$(dirname "$0")/../.." || exit 1
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then set -- --date "$@"; fi
exec "${PYTHON:-.venv/bin/python}" -m tradingbot pipeline review "$@"
