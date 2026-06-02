#!/usr/bin/env bash
# Pre-demo / pre-submit checks for Bifrost (VG.7 packaging + tests).
# Run from part_vg/:  bash scripts/verify_release.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Bifrost verify_release ==="
echo

echo "1. Python unit tests..."
PYTHONPATH=. .venv/bin/pytest tests/ -q
echo

echo "2. Frontend production build..."
(cd frontend && npm run build)
test -f frontend/dist/index.html
echo

echo "3. Server import smoke..."
PYTHONPATH=. .venv/bin/python -c "from server import app; assert app.title == 'Bifrost'"
echo

if [[ -f .env ]] && grep -qE '^OPENROUTER_API_KEY=.+$' .env 2>/dev/null; then
  echo "4. Local tool-calling (optional — needs LM Studio)..."
  if PYTHONPATH=. .venv/bin/python scripts/test_local_toolcall.py; then
    echo "   local OK"
  else
    echo "   local SKIP/FAIL (LM Studio offline is OK for CI-like runs)"
  fi
else
  echo "4. Local tool-calling — skipped (no .env with OPENROUTER_API_KEY)"
fi
echo

echo "=== All automated checks passed ==="
echo "Next: docker compose up  →  http://localhost:8000"
echo "Mock UI (no backend): cd frontend && npm run dev:mock"
