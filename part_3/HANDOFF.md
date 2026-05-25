# Part 3 — Session handoff (2026-05-25)

Handoff covering **Claude Code session** (review, shootout, demos) + **Cursor session** (orchestration, smoke tests, go-on fix).  
Branch: `main`, **15 commits ahead of `origin/main`** (through `312e5be`).

---

## Assignment constraints (do not break)

From [../CLAUDE.md](../CLAUDE.md) and [../th25-hub-connection.md](../th25-hub-connection.md):

- **100% own Python** — no LangGraph/LangChain/Cursor-as-agent
- **Hub:** REST, 10 msgs/agent, 4096 chars/msg, 1 req/sec (live)
- **System prompt from file** — SWE-only, no secrets, PASS for loop control
- **Rate-limit + token cap** — console: `pause`, `cap`, `limit`
- **Smart participation** — mentions, anti-dup, stagger delays, operator priority
- **Exam 2026-05-29:** **one** agent on live hub (~20 peer agents)

**Do not change lightly:** `hub.py` protocol, `agent.py` `BLOCKED` list, docker service layout.

---

## Current production config (use this on exam)

| Setting | Value | Where |
|---------|-------|-------|
| **MODEL** | `google/gemini-2.5-flash` | `docker-compose.yml`, `.env.example`, `agent.py` default |
| MAX_ROUNDS | `10` | compose / env |
| MAX_TOKENS | `2048` | `agent.py` (env `MAX_TOKENS`) |
| TOKEN_CAP | `150000` | compose |
| MSG_CAP | `10` | compose |
| RESPONSE_DELAY | 2s / 30s / 60s | macmini1 / macmini2 / macmini3 |
| Mock hub | **No grader-bot seed** | `frontend_demo/mock_hub.py` (commented out) |

**Cost:** ~$0.15/session, ~$1.65 for 10 local tests + exam.

**Fallback if Gemini misbehaves:** `openai/gpt-4.1-mini` (~$0.11/session) or `openai/gpt-4o-mini` (~$0.04, proven on simple tasks, edit_file dup risk).

**Do not use for exam without retest:** `anthropic/claude-haiku-4.5` (misses filenames under noise; expensive).

---

## How to run locally

```bash
cd assignment2/part_3

# One-shot reset (preferred):
./scripts/reset-local.sh

docker compose up --build    # or -d
# Hub UI: http://localhost:8080
# Logs:   tail -f logs/macmini1.log
```

Post task (curl or UI), password `th25-agents-vg`.  
Full ops: [COMMANDS.txt](COMMANDS.txt)

### Live exam (2026-05-29)

1. `.env` — **LIVE** block: `AGENT_NAME=marcus-macmini1`, RunPod `HUB_URL`
2. `DRY_RUN=false`
3. **One** agent: `python main.py` (not 3× macmini on live hub)
4. Second terminal: console `status` / `cap` / `limit` / `pause`

### Large projects — recommended operator pattern

Do **not** expect 6+ files in one message in 3 minutes with 3 agents. Use **phased hub messages**:

1. “Delete workspace files. Create `requirements.txt`, `models.py`, `db.py`. Verify import.”
2. “Create `app.py` with routes … Test with TestClient.”
3. “Create `project_cli.py` + `README.md`.”

After each phase: `./scripts/reset-local.sh` only between **full** demo restarts, not mid-task.

---

## Architecture

```
main.py              — poll loop, routing, operator/gap/delegation/promise gates
agent.py             — decide(), tools, security guard, auto-fallback, TokenCounter
hub.py               — fetch/send + retry on 5xx/timeout
console.py           — pause/cap/limit/quit (stdin thread)
config/system_prompt.txt
workspace/           — shared bind mount (3 containers)
frontend_demo/mock_hub.py — local hub, empty start (no welcome seed)
scripts/reset-local.sh
tests/test_main.py   — 187 unit tests
```

---

## Session timeline (what happened)

### Phase A — Claude Code: review + hardening (`ea51b06` … `6be0644`)

- Checkpointed uncommitted work; fixed Step-N leak, “On it!” loop, hub retry, operator fast-path, `REVIEW.md`, `HANDOFF.md` (old).
- Pre-exam fixes: broader `is_operator_agent()`, auto-summary anti-loop, `reset-local.sh`.
- **Solid test:** `csv2json.py` / `urls.py` — all agents prose, operator fast-path OK.

### Phase B — Model shootout (`fc89b66`)

Compared on **wordfreq.py** task (explicit filename):

| Model | wordfreq.py | Notes |
|-------|-------------|-------|
| gpt-4.1-mini | ✅ | Extra distractor files |
| **gemini-2.5-flash** | ✅ | **Winner** — focused, all prose, no auto-summary spam |
| deepseek-chat | ✅ | Extra files |

**Chosen:** `google/gemini-2.5-flash` for test + exam consistency.

### Phase C — Demo + large-task failures

- Clean hub (no grader-bot welcomes).
- **Simple tasks** (urls, wordfreq): ✅ ~30–60s, all agents deliver.
- **Complex task** (Project Tracker, 6 files): ❌ ~1 file + “I will…” promises; agents idle after partial work.

### Phase D — Large-project orchestration (`d6d9800`, `ff9a5fe`)

- **NO PROMISES** prompt + `is_empty_promise()` / `has_disallowed_promise()`.
- **WORKSPACE GAP** injection (missing filenames from operator text).
- **Delegation override** — `@agent please take…` → tools required.
- Optional `PROJECT_STATUS.md` in prompt.
- Result: 3/6 files (requirements, db, README); mixed “Created X. Next I will…” still sent (loophole).

### Phase E — Cursor: go-on + complaint fix (`312e5be`)

**Bug:** `latest_operator_command()` returned `"go on"` → lost imperative spec → no GAP/delegation.

**Fix:**

- `latest_operator_command()` → latest operator message **with imperative** (`build`/`create`/…).
- `is_non_delivery_reply()` + `hub_reply_blocked()` — block complaint prose without delivery.
- `apply_send_quality_retries()` — promise + non-delivery retries before send.

**Smoke test (2026-05-25 11:44):** Project Tracker + `go on` → **5/6 files** in ~6 min:

- ✅ requirements, models, db, project_cli, README  
- ❌ `app.py` — macmini2 ran `rm -f app.py` in tool chain (regression)

---

## Key behaviors in `main.py` (current)

| Mechanism | Purpose |
|-----------|---------|
| `latest_operator_command()` | Active **imperative** spec (ignores “go on”) |
| `operator_directive_pending()` | Fast-path skip delay |
| `build_workspace_gap_section()` | Lists missing required files (2+ in spec) |
| `was_delegated_to_me()` + DELEGATION OVERRIDE | @mention + please/take → must use tools |
| `has_disallowed_promise()` / `is_non_delivery_reply()` | Block promises + complaints |
| `apply_send_quality_retries()` | Up to 2 retries before send |
| `hub_reply_blocked()` | ABORT send if still bad |
| `looks_duplicate()` | ABORT if dup file+action or text >0.75 similarity |
| `should_suppress_autosum()` | No repeat `[auto-summary]` within 60s |
| Canned “On it!” | Only @mention + PASS; 60s anti-repeat; tool nudge if delegated + operator open |
| `task_completed_heuristic()` | Suppress canned ack when peers reported success |
| Token tiers | 75% soft (trim history, no nudge), 90% hard sign-off |

---

## Empirical results summary

| Task type | Outcome | Notes |
|-----------|---------|-------|
| 1-file CLI (wordfreq, urls) | **Good** | 30–60s, prose reports |
| Medium (TODO API iter 1) | **Partial** | app.py + deps; promise leak before fix |
| Large 6-file (Tracker, pre-orchestration) | **Poor** | 1 file, promises |
| Large 6-file (after `d6d9800`) | **Partial** | 3 files; go-on lost context |
| Large 6-file (after `312e5be`) | **Good** | 5/6 files; app.py deleted by agent |

---

## Known issues (open)

1. **Agents `rm` required files** — e.g. `rm -f app.py` while building app. **Suggested fix:** extend `agent.py` security guard or prompt: forbid `rm` on filenames from active operator spec.
2. **Mixed delivery + promise** — largely fixed by `has_disallowed_promise`; still watch auto-summary text.
3. **Anti-dup ABORT hides progress** — agent creates file but message blocked; peers may redo work.
4. **3-agent token burn** — macmini3 hit 90% cap in Tracker test; use 1 agent for long local runs.
5. **Workspace races** — 3 containers, one bind mount (rare file clash).
6. **`go on` has no fast-path** — correct; relies on retained imperative spec in prompt injection (works after `312e5be`).

---

## Git commit map (Part 3, newest first)

| Commit | Summary |
|--------|---------|
| `312e5be` | Fix “go on” clearing operator context; block non-delivery replies |
| `d6d9800` | Large-project orchestration (GAP, delegation, promise gate) |
| `0b2b8f0` | Checkpoint before orchestration |
| `ff9a5fe` | NO PROMISES prompt + `is_empty_promise`; disable hub seed |
| `fc89b66` | Switch to gemini-2.5-flash (shootout winner) |
| `6be0644` | `reset-local.sh` |
| `4ea6efe` | Auto-summary anti-loop |
| `bdbd3a4` | Operator substring fallback + LLM exception handling |
| `0bcfd38` | Operator fast-path, task-completed, REVIEW/HANDOFF |
| … | See `git log --oneline part_3/` back to `d0f59c3` |

**Tests:** `cd part_3 && .venv/bin/pytest tests/ -q` → **187 passed**

**Working tree:** clean at handoff time.

---

## Suggested next steps

1. **Prompt/guard:** forbid `rm` on files listed in active operator directive.
2. **Optional:** skip dup-ABORT when reply mentions a file still missing from `build_workspace_gap_section`.
3. **Pre-exam:** single-agent LIVE dry run with `limit 3`; phased operator messages if task is large.
4. **Do not** switch model without a 1-task shootout on **your** exam-style prompt.
5. Push `main` when ready (`git push` — 15 commits ahead of origin).

---

## Rules for next agent

- Type hints; match existing style; no new deps without asking
- **Do not commit** unless user asks
- `git switch` / `git restore` (not checkout)
- User language: Swedish OK; docs English or Swedish
- This handoff supersedes the 2026-05-22 sections above (kept for history in git)

---

## Quick reference — log grep

```bash
grep -h "SENT\|ABORT\|blocked\|operator directive\|delegation\|promise\|non-delivery" logs/macmini*.log
find workspace -type f ! -name .gitkeep ! -path '*/__pycache__/*'
curl -s "http://localhost:8080/api/stats?password=th25-agents-vg" | python3 -m json.tool
```

---

## Documentation

| File | Purpose |
|------|---------|
| [PART_3_ITERATION_LOG.md](PART_3_ITERATION_LOG.md) | Model shootout + iteration history |
| [REVIEW.md](REVIEW.md) | Security/quality audit (2026-05-22) |
| [COMMANDS.txt](COMMANDS.txt) | Ops cheat sheet |
| [../th25-hub-connection.md](../th25-hub-connection.md) | Live hub API |
