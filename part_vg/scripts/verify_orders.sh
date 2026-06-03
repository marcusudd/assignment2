#!/usr/bin/env bash
# Verify /orders hero deliverables in workspace. Run from part_vg/: bash scripts/verify_orders.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WS="$ROOT/workspace"
cd "$WS"

missing=0
for f in models/order.py schemas/order.py routers/orders.py tests/test_orders.py; do
  if [[ ! -f "$f" ]]; then
    echo "MISSING: $f"
    missing=1
  fi
done

if [[ $missing -ne 0 ]]; then
  exit 1
fi

if ! grep -q include_router main.py 2>/dev/null; then
  echo "MISSING: main.py must register orders router (include_router)"
  exit 1
fi

echo "Files OK — running pytest..."
PY=python3
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
fi
"$PY" -m pytest tests/test_orders.py -x -q
