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
docker compose up --build
```

Open **http://localhost:8000** (web GUI).  
Fallback TUI: `docker compose --profile cli run --rm bifrost-cli -i`

## 3. What to show (VG criteria map)

| Show | How |
|------|-----|
| **VG.1** Parallel sub-agents | Hero task → Mode 3 → timeline: **two ☁️ lanes overlap** + optional 🏠 lanes |
| **VG.2** Compaction | Long integrator run OR lower `token_threshold` in config.toml first |
| **VG.3** Cost cap | Cost panel + warning at 75% + hard stop if cap hit |
| **VG.4** Safety | `Run rm -rf /` → BLOCKED in activity feed + criteria |
| **VG.5** Bash | Worker runs `pytest` in timeline |
| **VG.6** Section edit | Integration pass edits with `[section-edit]` in feed |
| **VG.7** Packaging | `docker compose up` for grader |
| **VG.8** Config | `.env.example` + `config.toml`, secrets only in `.env` |
| **VG.9** Autonomy | Workers tool-call until yield (done in feed) |

## 4. Hero task (mode 3)

Paste in web UI (cap e.g. `$0.20`):

```
Add a complete /orders resource. An order has items, quantities, and a total.
Create models/order.py, schemas/order.py, routers/orders.py, and tests/test_orders.py.
Register the router in main.py and ensure pytest passes.
```

**Point at:** Router banner Mode 3 → parallel timeline → criteria strip lights up → result panel.

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

Shows overlapping lanes + criteria without backend — useful for layout rehearsal only.

## 7. After demo

- Logs in `logs/`
- Workspace: `bash scripts/reset_seed.sh` or Reset in UI
- Independent pytest in `workspace/` (avoid completion bias)
