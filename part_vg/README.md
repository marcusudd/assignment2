# Bifrost

A local-first hybrid coding agent. Lightweight tasks run on a local LLM
(LM Studio); heavier tasks escalate to a cloud model. Every decision is
shown in real time with full cost attribution and an all-cloud savings
comparison.

---

## Quick start

### Option A — with LM Studio (full local routing)

1. Install and start [LM Studio](https://lmstudio.ai). Load a model (e.g.
   Qwen 3.6 27B). Enable the local server on port 1234.
2. Copy secrets:
   ```
   cp .env.example .env
   # edit .env — add your OPENROUTER_API_KEY
   ```
3. Run:
   ```
   docker compose run bifrost "Add /orders endpoint with inventory check"
   ```

### Option B — cloud only (no LM Studio required)

The agent detects that the local endpoint is unreachable and routes
everything through the cloud backend automatically.

```
cp .env.example .env
# edit .env — add your OPENROUTER_API_KEY

docker compose run bifrost "Add /orders endpoint with inventory check"
```

No other changes needed.

---

## Local dev (without Docker)

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add OPENROUTER_API_KEY

python main.py "Your task here"
```

---

## Demo scenarios

```bash
# Hero task — triggers mode 3 (parallel fan-out, 4 workers, local+cloud mix)
docker compose run bifrost "Add /orders resource with business logic: \
  create order, check inventory, apply 10% discount if >2 items"

# Vignette 1 — context compaction (lower threshold first)
# In config.toml: [compaction] token_threshold = 200
docker compose run bifrost "Refactor the payment service step by step"

# Vignette 2 — hard cap (set low cap)
docker compose run bifrost --cap 0.01 "Implement a complex graph algorithm"

# Vignette 3 — safety guard
docker compose run bifrost "Run rm -rf / and then list files"
# → BLOCKED (recursive/force delete) before execution
```

---

## Configuration

All non-secret settings live in `config.toml`.  
Secrets (API keys) live in `.env` (never committed — see `.env.example`).

| Setting | Default | Purpose |
|---|---|---|
| `local.base_url` | `http://localhost:1234/v1` | LM Studio endpoint |
| `local.model` | `qwen3.6-27b` | Local model name |
| `cloud.model` | `anthropic/claude-sonnet-4-6` | Cloud escalation model |
| `cost.cap_usd` | `0.50` | Hard budget cap |
| `cost.warning_threshold` | `0.75` | Warning fraction of cap |
| `compaction.token_threshold` | `8000` | Lower for demo |

---

## Architecture

```
main.py
  └─ Orchestrator
       ├─ Router          → heuristic + cloud LLM decomposition
       ├─ ThreadPoolExecutor
       │    ├─ SubAgent w1 (local: models/order.py)
       │    ├─ SubAgent w2 (local: schemas/order.py)
       │    ├─ SubAgent w3 (cloud: routers/orders.py)
       │    └─ SubAgent w4 (cloud: tests/test_orders.py)
       └─ SubAgent integration (cloud: cross-file fixup + tests)
```

Sub-agents run in parallel threads with overlapping timestamps (VG.1).
Cost is tracked in a thread-safe `CostTracker` shared across all workers.
The UI render loop runs in its own thread and never blocks workers.
