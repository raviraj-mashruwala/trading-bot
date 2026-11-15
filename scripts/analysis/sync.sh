#!/usr/bin/env bash
# Staged manual analysis: `sync` step. Pass --full to force a full initial fill.
cd "$(dirname "$0")/../.." || exit 1
exec "${PYTHON:-.venv/bin/python}" -m tradingbot pipeline sync "$@"
