#!/usr/bin/env bash
# Start Bifrost (API + built React UI) in Docker.
# Usage from part_vg/:
#   bash scripts/docker-up.sh          # live backend (needs .env + API keys for runs)
#   bash scripts/docker-up.sh --mock   # UI rehearsal, no LLM / no keys required
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MOCK=0
if [[ "${1:-}" == "--mock" ]]; then
  MOCK=1
fi

if [[ ! -f .env ]]; then
  echo "Creating .env from .env.example — edit OPENROUTER_API_KEY for live runs."
  cp .env.example .env
fi

if [[ "$MOCK" -eq 1 ]]; then
  echo "Starting Bifrost in MOCK mode (animated SSE, no orchestrator)…"
  export BIFROST_MOCK=true
else
  echo "Starting Bifrost (live orchestrator + web UI on :8000)…"
  unset BIFROST_MOCK
fi
exec docker compose up --build
