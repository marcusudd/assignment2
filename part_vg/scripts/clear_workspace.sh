#!/usr/bin/env bash
# Clear the workspace to empty (keeps .gitkeep). Run from part_vg/: bash scripts/clear_workspace.sh
set -euo pipefail

WS="$(cd "$(dirname "$0")/../workspace" && pwd)"
cd "$WS"

find . -type f -not -name ".gitkeep" -delete
find . -mindepth 1 -depth -type d -empty -delete 2>/dev/null || true

echo "Workspace cleared."
