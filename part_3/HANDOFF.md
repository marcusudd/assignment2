# Part 3 — Agent handoff (2026-05-22)

Handoff for the next agent continuing Assignment 2 Del 3 work.

---

## Assignment constraints (do not break)

From [../CLAUDE.md](../CLAUDE.md) and [../th25-hub-connection.md](../th25-hub-connection.md):

- **100% own Python** — no LangGraph/LangChain/Cursor-as-agent
- **Hub:** HTTPS REST, 10 msgs/agent, 4096 chars/msg, 1 req/sec
- **System prompt from file** — no secrets, safe collaboration, PASS for infinite-loop control
- **Rate-limit + token cap** — console-adjustable (`pause`, `cap`, `limit`)
- **Smart participation** — mentions, anti-dup, stagger delays, operator priority
- **Exam:** 2026-05-29, one agent in live hub with ~20 student agents

**Do not change without good reason:** `hub.py` protocol, security `BLOCKED` list in `agent.py`, docker service layout.

---

## What this agent session completed

### Committed (on `main`)

| Commit | Summary |
|--------|---------|
| `ea51b06` | Baseline hardening: anti-dup, auto-fallback, Haiku, crash loop, fast-forward |
| `22a4e52` | Canned "On it!" anti-repeat (60s window) |
| `9948197` | Prompt: no Step N leak, TASK COMPLETED rule |
| `8ebbddf` | Hub retry on 5xx/timeout (+ tests) |
| `c4c1915` | Defaults aligned (Haiku, macmini1, MAX_ROUNDS=10) |
| `3aa74ff` | Iteration log doc update |

### Uncommitted (implement plan "Del 3 hub-fixar" — ready to commit)

| File | Changes |
|------|---------|
| `main.py` | `operator_directive_pending`, `task_completed_heuristic`, operator fast-path (skip delay), operator prompt injection on first `decide()`, gated canned ack, history trim at soft limit |
| `config/system_prompt.txt` | Delete-first for operator, @mention after complete → PASS, 400-char messages |
| `tests/test_main.py` | +5 tests → **156 passed** |
| `COMMANDS.txt` | Workspace cleanup note + Flask/delete test curl |

**Run tests:** `cd part_3 && .venv/bin/pytest tests/ -q` → **160 passed** (after 2026-05-22 review fixes)

**Security/quality audit:** [REVIEW.md](REVIEW.md)

**Suggested commit message:**

```
Add operator fast-path and task-completed gates for hub agents

- Skip RESPONSE_DELAY when operator/grader posts an imperative directive
- Inject operator command block on first LLM call, not only on nudge retry
- Suppress canned "On it!" when task_completed_heuristic is true
- Prompt: delete workspace files before rebuild; shorter hub messages
- Trim history to 12 entries at 75% token soft limit
```

---

## Current production config

| Setting | Value | Where |
|---------|-------|-------|
| MODEL | `anthropic/claude-haiku-4.5` | `docker-compose.yml`, `.env.example` |
| MAX_ROUNDS | `10` | env / compose |
| max_tokens (per LLM call) | `2048` | `agent.py` line ~246 (hardcoded) |
| TOKEN_CAP | `150000` | compose |
| MSG_CAP | `10` | compose |
| RESPONSE_DELAY | 2s / 30s / 60s | macmini1/2/3 |
| DRY_RUN | `false` | required for hub chat |

**Why Haiku + 2048 + 10 rounds:** gpt-4o-mini worked but duplicated edits; Haiku needs more tokens before tool calls and more rounds. Empirically best local run used this stack.

**Nödfallback:** `MODEL=openai/gpt-4o-mini`, `MAX_ROUNDS=6` in `.env` if Haiku misbehaves on exam day.

---

## How to run locally

```bash
cd assignment2/part_3

# ALWAYS between tests:
docker compose down
find workspace -mindepth 1 ! -name '.gitkeep' -delete
rm -f logs/macmini*.log

docker compose up --build   # or -d for detached
# Hub UI: http://localhost:8080
# Logs: tail -f logs/macmini1.log
```

Full commands: [COMMANDS.txt](COMMANDS.txt)

### Live exam (2026-05-29)

1. In `.env`: use **LIVE** block — `AGENT_NAME=marcus-macmini1` (or your name), `HUB_URL=https://wb48jtfnjng6on-8080.proxy.runpod.net`
2. `DRY_RUN=false`
3. Run **one** agent: `python main.py` (not 3 macminis against live hub)
4. Console in second terminal for `cap` / `limit` / `pause`

---

## Architecture (quick map)

```
main.py          — poll loop, routing, anti-dup, operator fast-path, nudges
agent.py         — decide() multi-round tools, security guard, auto-fallback
hub.py           — REST client, rate limit, retry
console.py       — stdin thread: pause/cap/limit/quit
config/system_prompt.txt
workspace/       — shared bind mount (all containers)
frontend_demo/   — local mock hub (port 8080)
tests/test_main.py — 156 unit tests
```

### Key behaviors in `main.py`

- **PASS** — agent sends nothing
- **mentioned_other** — skip if message starts with `@other`
- **operator_directive** — skip RESPONSE_DELAY, immediate recheck, inject `*** OPERATOR'S DIRECT COMMAND ***`
- **looks_duplicate** — abort send (file+action or text similarity >0.75)
- **auto-fallback** in `agent.py` when tools used but LLM returns PASS/empty/max rounds
- **Token tiers:** 75% soft (no nudge/retry), 90% hard (sign-off + silent)

---

## Known issues / not fixed

1. **macmini3 (60s delay)** still waits one full delay cycle if operator posts during that window; recheck then includes operator — no more "no directive" PASS, but slower than macmini1 fast-path.
2. **Auto-summary spam** — Haiku often hits MAX_ROUNDS; fallback sends `[auto-summary]` instead of prose.
3. **Flask in workspace** — not in stdlib; containers may lack `flask` unless installed via bash (agents sometimes assume it exists).
4. **3-agent local test** burns token budget fast — not representative of single-agent exam.
5. **Workspace races** — 3 containers share bind mount; simultaneous `cat > file` can clash (rare).

---

## Last live test results (after hub-fixar)

Task: *Build Flask app, delete old files first* (seeded `leftover.json`)

- ✅ `leftover.json` removed
- ✅ `app.py` + `templates/index.html` created
- ✅ `operator directive — skipping response delay` in macmini1.log
- ✅ No "On it!" in logs
- ✅ macmini3 did not send "no directive" after operator (saw operator on recheck)

Docker may still be running from last test — run `docker compose down` if needed.

---

## Documentation files

| File | Purpose |
|------|---------|
| [PART_3_ITERATION_LOG.md](PART_3_ITERATION_LOG.md) | Empirical iteration history (gpt-4o-mini vs Haiku vs Sonnet) |
| [COMMANDS.txt](COMMANDS.txt) | Ops cheat sheet |
| [../th25-hub-connection.md](../th25-hub-connection.md) | Live hub API |

---

## Suggested next steps for incoming agent

1. **Commit** uncommitted changes (4 files) if user wants them saved.
2. Optional: make `max_tokens` env-configurable (`MAX_TOKENS` in `.env.example`).
3. Optional: after delay+recheck, if `operator_directive_pending` becomes true, log `operator directive (late)` — same as fast-path for macmini3.
4. Pre-exam: single-agent dry run against LIVE hub with low `limit 3` first to verify connectivity.
5. Do **not** refactor `hub.py` or weaken security guard unless assignment requirements change.

---

## Rules reminder for the new agent

- Match existing code style; type hints; async not required in part_3
- **Ask before adding dependencies**
- **Do not commit** unless user asks
- Use `git switch` / `git restore`, not `checkout`
- User communicates in Swedish; technical docs can be English or Swedish
