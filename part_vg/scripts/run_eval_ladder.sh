#!/usr/bin/env bash
# Run the 5-step Haiku eval ladder; logs under logs/eval_ladder_<timestamp>/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TS="$(date +%Y%m%d_%H%M%S)"
EVAL_DIR="$ROOT/logs/eval_ladder_$TS"
mkdir -p "$EVAL_DIR"

# Prefer Docker (same env as GUI); fallback to .venv
RUNNER=()
if docker compose ps --status running bifrost 2>/dev/null | grep -q bifrost; then
  RUNNER=(docker compose exec -T bifrost python main.py)
  RESET_CMD=(docker compose exec -T bifrost bash scripts/reset_seed.sh)
  PYTEST_CMD=(docker compose exec -T bifrost bash -c "cd workspace && python3 -m pytest tests/ -q")
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  export PYTHONPATH=.
  RUNNER=("$ROOT/.venv/bin/python" main.py)
  RESET_CMD=(bash scripts/reset_seed.sh)
  PYTEST_CMD=(bash -c "cd workspace && .venv/bin/python -m pytest tests/ -q")
else
  echo "Need Docker (docker compose up) or part_vg/.venv — system python3 lacks deps." >&2
  exit 1
fi

log_step() { echo "[$(date -Iseconds)] $*" | tee -a "$EVAL_DIR/runner.log"; }

run_test() {
  local id="$1"
  local cap="$2"
  local reset_ws="$3"
  local prompt="$4"
  local outfile="$EVAL_DIR/test_${id}.stdout"

  log_step "=== TEST $id cap=\$$cap reset=$reset_ws ==="
  if [[ "$reset_ws" == "yes" ]]; then
    "${RESET_CMD[@]}" >> "$EVAL_DIR/runner.log" 2>&1
  fi

  {
    echo "TEST_ID=$id"
    echo "CAP_USD=$cap"
    echo "PROMPT=$prompt"
    echo "START=$(date -Iseconds)"
    echo "RUNNER=${RUNNER[*]}"
  } > "$EVAL_DIR/test_${id}_meta.txt"

  set +e
  "${RUNNER[@]}" --no-verbose --cap "$cap" "$prompt" 2>&1 | tee "$outfile"
  local ec=$?
  set -e
  echo "EXIT_CODE=$ec" >> "$EVAL_DIR/test_${id}_meta.txt"
  echo "END=$(date -Iseconds)" >> "$EVAL_DIR/test_${id}_meta.txt"

  local session_log
  session_log=$(ls -t logs/*.log 2>/dev/null | grep -v server.log | grep -v eval_ladder | head -1 || true)
  if [[ -n "${session_log:-}" ]]; then
    cp "$session_log" "$EVAL_DIR/test_${id}_session.log"
    echo "SESSION_LOG=$(basename "$session_log")" >> "$EVAL_DIR/test_${id}_meta.txt"
  fi
  return $ec
}

log_step "Eval ladder start — EVAL_DIR=$EVAL_DIR"
log_step "CLOUD_MODEL=$(grep '^CLOUD_MODEL=' .env | cut -d= -f2-)"
log_step "LOCAL_MODEL=$(grep '^LOCAL_MODEL=' .env | cut -d= -f2-)"
if grep -qE '^LOCAL_MODEL_2=.+' .env 2>/dev/null; then
  log_step "WARN: LOCAL_MODEL_2 is set — dual-local may trigger LM Studio resource guard; demo uses single-local"
else
  log_step "LOCAL_MODEL_2 unset (single-local — recommended)"
fi
curl -s -o /dev/null -w "LM_STUDIO_HTTP=%{http_code}\n" http://localhost:1234/v1/models 2>/dev/null \
  | tee -a "$EVAL_DIR/runner.log" || echo "LM_STUDIO_HTTP=down" | tee -a "$EVAL_DIR/runner.log"

run_test 1 0.20 no "List all Python files in the workspace" || true
run_test 2 0.20 no "Read models/item.py and summarize the Item model fields in two bullet points." || true

run_test 3 0.20 yes "Add a GET /items endpoint in routers/items.py that returns two hardcoded items. Register the router in main.py so /health still works. Make sure pytest passes." || true

log_step "Test 3 workspace pytest"
"${PYTEST_CMD[@]}" 2>&1 | tee "$EVAL_DIR/test_3_pytest.txt" || true

run_test 4 0.35 yes "Add a complete /orders resource. An order has items, quantities, and a total price. Create models/order.py, schemas/order.py, routers/orders.py, and tests/test_orders.py. Register the router in main.py and make sure pytest passes." || true

bash scripts/verify_orders.sh 2>&1 | tee "$EVAL_DIR/test_4_verify_orders.txt" || true

run_test 5 0.02 yes "Implement a production-grade distributed order-saga system with Redis-backed orchestration, OAuth2 authorization, event sourcing, optimistic concurrency, idempotency keys, audit logs, formal correctness proofs, and 100% pytest coverage across the entire workspace. Migrate every affected file and make the full test suite pass." || true

log_step "Eval ladder finished — see $EVAL_DIR"
