#!/usr/bin/env bash
# Reset the local mock-hub test environment in one shot.
# Usage:  ./scripts/reset-local.sh
set -e

# Always run from part_3/
cd "$(dirname "$0")/.."

# Stop any running stack (ignore error if none running)
docker compose down 2>/dev/null || true

# Wipe workspace but keep .gitkeep
find workspace -mindepth 1 ! -name '.gitkeep' -delete

# Clear macmini logs (preserve archived iter-*/haiku-*/sonnet-* logs)
rm -f logs/macmini*.log

echo "Reset complete:"
echo "  - docker stack: stopped"
echo "  - workspace:    empty (.gitkeep kept)"
echo "  - logs:         macmini*.log cleared (archives preserved)"
echo ""
echo "Next: docker compose up --build"
