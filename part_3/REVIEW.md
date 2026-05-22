# Part 3 — Security & quality review (2026-05-22)

Full-project audit against Assignment 2 Del 3 requirements. Fixes applied in the same iteration are marked **FIXED**.

---

## Executive summary

| Area | Grade | Notes |
|------|-------|-------|
| Del 3 requirements coverage | **Good** | Hub chat, caps, console, smart participation, prompt rules |
| Security (bash guard) | **Good** | Part 2 guard intact; small gaps in read_file (now tightened) |
| Reliability | **Good** | Crash loop, hub retry, auto-fallback, operator fast-path |
| Exam readiness | **Good** | Use 1 agent + LIVE `.env`; Haiku + MAX_TOKENS=2048 |
| Test coverage | **Good** | 160 unit tests |

---

## Critical / high — fixed this review

### 1. `grader-bot` not recognized as operator **FIXED**

Hub and mock hub use agent name `grader-bot`. Code only matched `graderbot` → operator directives from GraderBot were ignored for `latest_operator_command` / fast-path.

**Fix:** `is_operator_agent()` with normalized aliases (`grader-bot` → `graderbot`).

### 2. @mention substring false positive **FIXED**

`@{AGENT_NAME} in content` matched `@macmini1` inside `@macmini10`.

**Fix:** Word-boundary regex `@{name}\b`.

### 3. `has_imperative` substring false positives **FIXED**

`"creative"` matched `"create"`.

**Fix:** Whole-word regex `\b(build|create|...)\b`.

### 4. Malformed tool JSON could crash loop **FIXED**

`json.loads(tc.function.arguments)` uncaught → iteration crash.

**Fix:** `JSONDecodeError` → tool error message, continue loop.

### 5. `read_file` could read `.env` in workspace **FIXED**

Bash blocks `cat .env`; `read_file` did not.

**Fix:** Block `.env` filenames in `tool_read_file`.

---

## Medium — open / mitigated

| Issue | Risk | Mitigation |
|-------|------|------------|
| macmini3 (60s delay) misses instant operator fast-path | Operator seen only after full delay + recheck | Fast-path on first poll; recheck injects operator prompt; exam uses 1 agent |
| `decide()` only sees last 20 msgs in batch | Long threads lose early operator context | History carries prior turns; hub batches usually include recent operator |
| `AUTO_APPROVE=true` in Docker | No human bash approval in containers | OK for local demo; exam single agent can use console y/n |
| Shared workspace bind mount | Race on simultaneous `cat > file` | Rare; anti-dup reduces duplicate work |
| `task_completed_heuristic` keyword-based | May miss atypical success wording | Good enough; saves msg spam |
| Token budget burns fast with 3 Haiku clones | Sign-off at 90% in ~5–10 min intense chat | Exam: one agent; console `cap` adjustable |
| `shell=True` in bash + nudge `find` | Standard risk | Workspace cwd; security_check on bash only |
| Hub password in compose / `.env.example` | Public course password | Expected for assignment hub |

---

## Low / nice-to-have (not changed)

- **`_FILE_RE` extension** — misses `README.md`, `pyproject.toml` (anti-dup still has text similarity).
- **`fetch_stats` no retry** — unused in main loop.
- **Sign-off on 429** — may fail silently (logged).
- **Prompt injection via hub** — mitigated by SECURITY section (PASS on jailbreak); not code-enforced.
- **`rm file`** allowed (not `rm -rf`) — required for operator delete tasks.
- **Flask not in stdlib** — agents may assume `pip install`; containers lack pip unless installed via bash.
- **History duplicates** — each `decide()` appends full context slice to history (by design for persistence).

---

## Security checklist (Del 3)

| Control | Status |
|---------|--------|
| No secrets in chat prompt | ✅ Prompt forbids |
| Bash chaining blocked | ✅ |
| rm -rf blocked | ✅ |
| .env read via bash blocked | ✅ |
| .env read via read_file blocked | ✅ **new** |
| Secret env expansion blocked | ✅ |
| Path traversal in tools | ✅ `resolve_path` |
| Workspace-only cwd for bash | ✅ |
| DRY_RUN for safe testing | ✅ |
| Token/msg caps | ✅ |
| No framework in agent loop | ✅ |

---

## Assignment Del 3 mapping

| Requirement | Implementation |
|-------------|----------------|
| Code transfer via chat | Tools + workspace + reports |
| Constructive collaboration | @mentions, anti-dup, operator priority |
| System prompt safety | `config/system_prompt.txt` |
| No console for main chat | `hub.send_message` / `fetch_messages` |
| Rate limit + token cap | `hub._throttle`, `TokenCounter`, console `cap`/`limit` |
| Smart participation | PASS, delays, mentions, anti-dup, operator fast-path |

---

## Tests

```bash
cd part_3 && .venv/bin/pytest tests/ -q
# 160 passed (after this review)
```

New tests: `grader-bot` operator, imperative word boundaries, `read_file` .env block.

---

## Config reference

| Variable | Recommended |
|----------|-------------|
| MODEL | `anthropic/claude-haiku-4.5` |
| MAX_ROUNDS | `10` |
| MAX_TOKENS | `2048` |
| TOKEN_CAP | `150000` (local 3-agent) / lower for exam tuning |
| DRY_RUN | `false` for real chat |

---

## Files changed in this review iteration

- `main.py` — operator alias fix, mention regex, imperative regex, late operator log
- `agent.py` — MAX_TOKENS env, JSON safety, read_file .env block
- `tests/test_main.py` — +4 tests
- `.env.example` — MAX_TOKENS documented
- `REVIEW.md` — this file

Uncommitted hub-fixar from prior session may still be in working tree — commit together when ready.
