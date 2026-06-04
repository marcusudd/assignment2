#!/usr/bin/env bash
# Run pytest on the workspace from any cwd.
# Usage: bash scripts/run_workspace_tests.sh [pytest args]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/workspace"

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

exec "$PY" -m pytest "${@:--q}"
