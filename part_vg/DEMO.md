# Bifrost — live demo rehearsal (VG)

Checklist before examination. Run from `part_vg/`.

## 1. Preflight (5 min)

```bash
cp .env.example .env          # if needed — add OPENROUTER_API_KEY
bash scripts/verify_release.sh
```

LM Studio:

1. Start local server on port **1234**.
2. Load **LOCAL_MODEL** (e.g. Gemma 4 26B).
3. Load **LOCAL_MODEL_2** (`gemma-4-e4b`) for dual-local parallel lanes.
4. `PYTHONPATH=. python scripts/test_local_toolcall.py` → all green.

## 2. Start stack

```bash
bash scripts/docker-up.sh
# or: docker compose up --build
```

Open **http://localhost:8000** (web GUI).  
Fallback TUI: `docker compose --profile cli run --rm bifrost-cli -i`

## 3. What to show (VG criteria map)

| Show | How |
|------|-----|
| **VG.1** Parallel sub-agents | Hero task → Mode 3 → timeline: **two ☁️ lanes overlap** + optional 🏠 lanes |
| **VG.2** Compaction | Long integrator run OR lower `token_threshold` in config.toml first |
| **VG.3** Cost cap | Cost panel + warning at 75% + hard stop if cap hit |
| **Savings story** | Heimdall panel → "Saved vs all-Haiku, no Bifrost" — same model, local offload only. Switch selector to Opus to see the premium comparison. Against budget models (gemini-flash) Bifrost is not cheaper — that's shown honestly. |
| **VG.4** Safety | `Run rm -rf /` → BLOCKED in activity feed |
| **VG.5** Bash | Worker runs `pytest` in timeline |
| **VG.6** Section edit | Integration pass edits with `[section-edit]` in feed |
| **VG.7** Packaging | `docker compose up` for grader |
| **VG.8** Config | `.env.example` + `config.toml`, secrets only in `.env` |
| **VG.9** Autonomy | Workers tool-call until yield (done in feed) |

## 4. Hero task (mode 3)

**Before 3.1:** `bash scripts/reset_seed.sh` — clean workspace.

**Cap:** `$0.20` per task (default). Do not raise cap to fix BLOCKED/pipe waste — fix prompts first. Only raise cap for a single run if, after a measured attempt, integration needs a few cents and you accept the trade-off (use UI cap field, not `config.toml`).

Paste in web UI **verbatim** (lists all four files → fast path, no router LLM):

```
Add a complete /orders resource. An order has items, quantities, and a total price.
Create models/order.py, schemas/order.py, routers/orders.py, and tests/test_orders.py.
Register the router in main.py and make sure pytest passes.
```

After run: `bash scripts/verify_orders.sh` (objective pass/fail). Check log `worker_cost` — locals should be $0; cloud spend on router/test/integration.

**Point at:** Router banner Mode 3 → parallel timeline (most lanes midgard/local) → BLOCKED / compaction lines in the activity feed → Heimdall savings card (local-execution split) → result panel.

**Savings beat:** the default comparison is Haiku (same cloud model Bifrost actually uses). Local workers ran for $0 — those tokens would have cost ~$X on Haiku alone. That's the honest number: local offload, same model, no cherry-picking.

**If 3.1 hits cap:** show VG.1 with a 2-file parallel task (see `demo.txt`), then a Mode-2 substance run — two `$0.20` runs beat one higher cap.

## 5. Cheap vignettes

```text
List all Python files in the workspace
```
→ mode 1, local, ~$0

```text
Run rm -rf / and then list files
```
→ VG.4 blocked, no execution

```text
Implement a complex graph algorithm with full proofs
```
→ with cap `$0.01` → budget stop (VG.3 hard cap)
```

## 6. Mock UI (no API spend)

```bash
cd frontend && npm run dev:mock
```

Shows overlapping lanes + activity feed without backend — useful for layout rehearsal only.

## 7. After demo

- Logs in `logs/`
- Workspace: `bash scripts/reset_seed.sh` or Reset in UI
- Independent pytest in `workspace/` (avoid completion bias)
