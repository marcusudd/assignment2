# Part 3 — Autonomous Iteration Log

Session: 2026-05-21 (15-min autonomous run)
Test task: "Build a Python CLI tool that converts a JSON file to CSV using only the standard library. Single file, runnable as `python json2csv.py input.json output.csv`."

---

## Iteration 1 — Baseline

**Setup:** Fresh docker compose with hub + macmini1/2/3 (delays 2/30/60s, max_rounds=6, token_cap=150k)

**Timeline:**
- 14:02:16 — grader-bot welcome messages auto-posted (seq 1-2)
- 14:02:18 — macmini1 starts LLM (sees grader-bot only)
- 14:02:46 — macmini1 LLM finishes → PASS, then nudge → "Hi — what should we build?" (seq=4)
- 14:02:48 — Operator task posted to hub (seq=3, but arrived just AFTER macmini1's LLM finished)
- 14:02:48 — macmini2 recheck sees operator task, starts LLM
- 14:03:09 — macmini2 PASS, nudge 14:03:43 PASS (silent — 34s of work)
- 14:03:20 — macmini3 sees both task + macmini1's message, LLM → PASS, nudge → PASS

**Workspace files created:** input.json, json2csv.py
**Messages sent to hub:** macmini1 × 1 ("Hi"), macmini2 × 0, macmini3 × 0

**Critical findings:**
1. **Silent tool work** — macmini2 and macmini3 used 30+ seconds of LLM time (clearly tool_calls happening) but the workspace shows their work. They returned PASS, no chat reports.
2. **Auto-fallback failed to trigger** — even though tools were used.
3. **Code quality bad** — json2csv.py has duplicate function bodies (edit_file overwrites).
4. **Timing issue** — macmini1 (delay=2s) committed to a response before operator task arrived.

**Root cause of fallback failure:**
The fallback report logic only fires when `finish_reason == "stop"`. If the LLM exhausts `MAX_ROUNDS=6` while still calling tools (`finish_reason == "tool_calls"`), the for-loop ends and we return PASS unconditionally — the fallback is unreachable in this path.

**Fix applied:** Added an out-of-loop fallback in `agent.py decide()`:
```python
# MAX_ROUNDS exhausted without "stop" — if tools were used, generate fallback
if tools_used and this_turn_tools:
    actions = this_turn_tools[-4:]
    fallback = f"[auto-summary] Actions this turn: {'; '.join(actions)} (max rounds reached)."
    return fallback
```

145 tests passing after fix.

---

## Iteration 2 — After fallback fix

**Setup:** Same as iter 1 but with out-of-loop fallback in agent.py.

**Timeline:**
- 14:19:29 — grader-bot welcomes
- 14:19:34 — macmini1 sends "Hi — what should we build?" (still social on grader-bot's "build a CLI" suggestion)
- 14:19:44 — operator task arrives in macmini1's next poll
- 14:20:02 — macmini1 sends `[auto-summary] Actions this turn: edited json2csv.py; edited json2csv.py; edited json2csv.py; edited json2csv.py` — **auto-fallback fired!**
- 14:20:22 — macmini2 produced identical fallback → final-check ABORT (anti-dup worked)
- 14:21:07 — macmini3 same — ABORT

**Workspace files created:** NONE (only .gitkeep)
**Messages sent to hub:** macmini1 × 2, macmini2 × 0 (aborted), macmini3 × 0 (aborted)

**Critical findings:**
1. ✅ **Auto-fallback works** — chat is no longer silent after silent tool use
2. ✅ **Anti-dup works** — identical auto-summary from macmini2/3 was correctly aborted
3. ❌ **New bug exposed: `edit_file` on non-existent file**
   - LLM tried `edit_file` 4 times on `json2csv.py` which didn't exist
   - Each call returned "ERROR: file not found"
   - LLM didn't switch to bash heredoc to CREATE the file
   - Result: zero actual files created despite 4 tool rounds

**Root cause:** System prompt said "Write the file (use edit_file or bash)" — too vague. LLM defaulted to edit_file since it sounds simpler, but it ONLY edits existing files.

**Fix applied:** Updated `config/system_prompt.txt` with explicit "edit_file vs creating new files" section:
- Use `bash: cat > file <<'EOF' ... EOF` to CREATE
- Use `edit_file` only for EXISTING files
- If edit_file returns "ERROR: file not found", switch to bash heredoc
- Always run `python file.py` after writing to verify

145 tests still passing after this change.

---

## Iteration 3 — After "create vs edit" prompt fix

**Setup:** Same as iter 2 but with explicit `bash heredoc` instruction in system prompt for new file creation.

**Result — MAJOR PROGRESS:**

**Workspace files created:**
- ✅ `json2csv.py` (runnable, 30 lines)
- ✅ `test_input.json` (sample data for testing)
- ✅ `test_output.csv` (actual output from running the script)

**Hub stats:** 8 total messages — macmini1: 3, macmini2: 2, grader-bot: 2, operator: 1

**Sample messages sent:**
- macmini2: "The json2csv.py script exists and runs successfully, converting JSON to CSV without errors. The output file test_output..." — substantive verification
- macmini2 auto-summary: `read ./json2csv.py; edited ./json2csv.py; ran python json2csv.py test_input.json...` — proves actual tool usage including running the script
- macmini1: "The json2csv.py script has been successfully created and runs without errors..."

**Verification — does the script work?**
Yes, runs without crashing. Output:
```
name,age,city
name,age,city
name,age,city
John,30,New York
Jane,25,Chicago
```

**Remaining quality issue:** The header line is duplicated 3 times in the output — same `edit_file` accumulation bug. The LLM inserted `writer.writerow(data[0].keys())` three times. This is a model-quality issue, not a code bug.

---

## Summary — what changed in 3 iterations

| Iteration | Key fix | Outcome |
|---|---|---|
| 1 | (baseline) | Files created via tools but agents said PASS — chat silent |
| 2 | Out-of-loop auto-fallback in `decide()` | Agents now report when they exhaust MAX_ROUNDS doing tools, but edit_file failed because file didn't exist |
| 3 | System prompt: explicit `bash heredoc` for new files + always `python file.py` to verify | Files created, runs OK, agents verify and report substantively |

## Files modified (all green tests: 145/145)
- [agent.py](agent.py) — added MAX_ROUNDS-exhaustion fallback block
- [config/system_prompt.txt](config/system_prompt.txt) — added "edit_file vs creating new files" + "Verifying your work" sections
- [logs/iter1-*.log, logs/iter2-*.log, logs/iter3-*.log](logs/) — preserved logs per iteration

## Remaining known limitations (model-level, not code)
1. **edit_file accumulation** — gpt-4o-mini sometimes inserts the same line multiple times during edits. Causes duplicate headers, repeated function bodies. Hard to fully fix without changing models.
2. **macmini1 jumps the gun on early messages** — with 2s delay, it commits to a response before later operator messages arrive. Workaround: stagger is intentional, slower agents catch up.
3. **macmini3 frequently silent** — with 60s delay + LLM time, it sometimes only gets one useful response in.

## Rules respected
- ✅ No AI coding frameworks
- ✅ Hub protocol unchanged (HTTPS REST, server-enforced caps)
- ✅ Security guard untouched
- ✅ Token-tier system intact (75% soft / 90% hard)
- ✅ PASS mechanism preserved
- ✅ System prompt still forbids secrets leakage
- ✅ 145 tests green throughout

---

## Bonus: Model comparison (Haiku + Sonnet via OpenRouter)

User asked if switching from gpt-4o-mini to Haiku/Sonnet would help. Empirical test:

| Model | Iterations | Files created | Quality | Notes |
|---|---|---|---|---|
| openai/gpt-4o-mini | 3 | 3 (json2csv.py, test_input, test_output) | Runs, buggy headers | Baseline |
| anthropic/claude-haiku-4.5 | 5 | 0 | N/A | Tool calls had empty 'command' arg via OpenRouter |
| anthropic/claude-sonnet-4.5 | 1 | 3 (empty/partial) | Files exist but empty | Used heredoc/touch but didn't finish within MAX_ROUNDS=6 |

**Code-level findings (improvements applied during this exploration — useful for ALL models):**
1. **finish_reason normalization** — Anthropic returns "end_turn"/"tool_use", code now falls back to "stop" interpretation based on msg shape
2. **Empty-reply fallback** — if LLM returns empty msg.content after tool use, auto-summary fires (previously short-circuited to PASS)
3. **Defensive dispatch_tool** — wraps tool calls in try/except, returns descriptive error to LLM so it can retry with correct args

**Honest conclusion:** Despite Claude models being theoretically better at tool use, **gpt-4o-mini outperformed both Haiku and Sonnet** in this setup. Reasons:
- OpenRouter's Anthropic translation has gaps (especially for Haiku tool args)
- Claude's "thinking" style needs MAX_ROUNDS > 6 to complete
- Our tool spec is OpenAI-shaped, may need adjustment for Anthropic native style

**Initial conclusion was WRONG.** The fix was MAX_ROUNDS=10 (not 6). Claude models need more tool rounds to complete their thinking. After raising MAX_ROUNDS to 10:

**Haiku 4.5 (MAX_ROUNDS=10) — WINNER:**
- 4 files created (json2csv.py, output.csv, test.json, test_output.csv)
- 11 hub messages across all 3 agents
- macmini2 verified macmini1's work: "**Verified:** The CLI tool is complete and working."
- Code quality: idiomatic Python (csv.DictWriter), proper error handling, NO duplicate lines
- Script runs cleanly: `python3 json2csv.py /tmp/t.json /tmp/o.csv` → "Successfully converted"

**Final recommendation: anthropic/claude-haiku-4.5 with MAX_ROUNDS=10 AND max_tokens=2048.**

The TRUE root cause was found after one more deep dive:

`max_tokens=512` was truncating Claude models mid-tool-call. Claude writes verbose reasoning ("Step 1 — VERIFY...", "Step 2 — GAP ANALYSIS...") BEFORE emitting tool calls. When the token budget hit during a tool_use block, the JSON arguments were truncated → bash was called with empty `command`.

GPT-4o-mini is more concise, fits everything in 512 tokens, never hit this. Claude needs ~2048 tokens of headroom.

**Verified final test (max_tokens=2048):**
- 20 hub messages across all 3 agents (vs 5 with 512)
- 5 real files created (json2csv.py + 4 test artifacts)
- macmini2 hit 8/10 messages — near hub-cap
- Production-quality code: heterogeneous schemas, multiple exception types, idiomatic csv.DictWriter
- macmini2: "Perfect! **json2csv.py is complete and working.**" (substantive verification)

**Changes vs original setup:**
- MODEL: openai/gpt-4o-mini → anthropic/claude-haiku-4.5
- MAX_ROUNDS: 6 → 10 (Claude needs more reasoning rounds)
- max_tokens: 512 → 2048 (Claude writes longer reasoning before tool calls)
- Cost: ~$0.04 → ~$0.50 per session (12.5× more, but $0.50 is trivial for an exam)

Logs preserved in:
- `logs/iter1-3-*.log` — gpt-4o-mini progression
- `logs/haiku-iter1-5-*.log` — Haiku attempts (none produced files)
- `logs/sonnet-iter1-*.log` — Sonnet attempt (empty files)

