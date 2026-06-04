# Bifrost — live demo rehearsal (VG)

Checklist before examination. Run from `part_vg/`.

## 1. Preflight (5 min)

```bash
cp .env.example .env          # if needed — add OPENROUTER_API_KEY
bash scripts/verify_release.sh
PYTHONPATH=. python scripts/run_via_api.py --preflight   # after server is up
```

LM Studio:

1. Start local server on port **1234**.
2. **Unload** other models; load only **`LOCAL_MODEL`** (default: `gemma-4-26b-a4b-it-mlx`).
3. Leave **`LOCAL_MODEL_2` unset** in `.env` for demo (single-local). VG.1 is parallel **workers**, not two model IDs at once.
4. `PYTHONPATH=. python scripts/test_local_toolcall.py` → green for `LOCAL_MODEL`.
5. If 26b hits resource guard: unload extras in LM Studio or set `LOCAL_MODEL=gemma-4-e4b-it-mlx` and retry.

## 2. Start stack

```bash
bash scripts/docker-up.sh
# or: docker compose up --build
```

Open **http://localhost:8000** (web GUI).

**Same run in terminal + GUI** (recommended for live demo):

```bash
PYTHONPATH=. python scripts/run_via_api.py -i
# or one-shot: python scripts/run_via_api.py --cap 0.35 "…"
```

Offline Rich TUI (not in GUI SSE): `docker compose --profile cli run --rm bifrost-cli -i`

## 3. What to show (VG criteria map)

| Show | How |
|------|-----|
| **VG.1** Parallel sub-agents | Hero task → **Mode 3** badge + **Parallel lanes** (center) — overlapping bars + worker grid |
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

**Cap:** `$0.35` for the hero task (integration often needs more than `$0.20`). Default `$0.20` is fine for vignettes. Do not raise cap to fix BLOCKED/pipe waste — fix prompts first.

Paste in web UI **verbatim** (lists all four files → fast path, no router LLM):

```
Add a complete /orders resource. An order has items, quantities, and a total price.
Create models/order.py, schemas/order.py, routers/orders.py, and tests/test_orders.py.
Register the router in main.py and make sure pytest passes.
```

After run: `bash scripts/verify_orders.sh` (objective pass/fail). Check log `worker_cost` — locals should be $0; cloud spend on router/test/integration.

**Point at:** Mode 3 badge + Parallel lanes → Evidence panel (routing/workers/tools) → activity feed → Heimdall savings → **Built in workspace** + run summary after done.

**Objective check:** `bash scripts/verify_orders.sh` (pytest on workspace).

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

## 8. Eval ladder prompts (automated GUI run)

```bash
PYTHONPATH=. python scripts/run_eval_gui.py
```

Prompts live in `logs/eval_ladder_GUI/test_1.txt` … `test_5.txt` (same text as `presentation_vg.md`).

## Bonus: calculator GUI (Mac only)

Tkinter is not available in Homebrew Python 3.14 `.venv`. Use system Python:

```bash
/usr/bin/python3 workspace/calculator_gui.py
```

Requires `calculator.py` in workspace (build via agent first; do not reset before GUI run).
