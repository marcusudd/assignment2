#!/usr/bin/env bash
# Container entrypoint: start every boot with an empty workspace, then run the
# real command (uvicorn for the web service).
set -euo pipefail

bash /app/scripts/clear_workspace.sh || true

exec "$@"
