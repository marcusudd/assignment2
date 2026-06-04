#!/usr/bin/env bash
# Attach to a running agent's interactive rich console
# (ask / steer / say / status / pause / cap / limit / y / n / help / quit).
#
# Usage:
#   ./scripts/console.sh         # live  (docker-compose.yml,       service: agent)
#   ./scripts/console.sh local   # local (docker-compose.local.yml, service: agent1)
#
# Once attached, type `help` to (re)show the command panel.
# Detach with Ctrl-P Ctrl-Q. Ctrl-C would kill the container.

set -e
cd "$(dirname "$0")/.."

MODE="${1:-live}"
case "$MODE" in
  live)
    COMPOSE_FILE="docker-compose.yml"
    SERVICE="agent"
    ;;
  local)
    COMPOSE_FILE="docker-compose.local.yml"
    SERVICE="agent1"
    ;;
  *)
    echo "Usage: $0 [live|local]"
    exit 2
    ;;
esac

CID=$(docker compose -f "$COMPOSE_FILE" ps -q "$SERVICE" 2>/dev/null || true)
if [ -z "$CID" ]; then
  echo "Error: service '$SERVICE' is not running."
  echo "Start it first with:"
  echo "  docker compose -f $COMPOSE_FILE up --build"
  exit 1
fi

echo "Attaching to $SERVICE ($CID)."
echo "Detach with  Ctrl-P  Ctrl-Q   (Ctrl-C kills the agent!)"
echo
exec docker attach --detach-keys ctrl-p,ctrl-q "$CID"
