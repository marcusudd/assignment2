# Assignment 2 — Automated SW-Developer Organisation

**Deadline:** 2026-05-28 22:00
**Examination:** Live agent meeting 2026-05-29 (mandatory — GraderBot evaluates)
**Submissions:** 3 separate submissions, one per part

---

## General Rules

- Agents must be 100% Python-based with own code and API calls (Anthropic, OpenAI, OpenRouter, local models, etc.)
- **Forbidden:** OpenCode, KiloCode, Claude-Code, Cursor, Anti-gravity, Codex, or any AI coding assistant as part of the agent
- Frameworks (LangGraph, LangChain, LlamaIndex, etc.) only where **explicitly permitted per part**
- Big picture: the class is building a fully automated SW-developer organisation — one agent per student, with a central hub for communication

---

## Del 1 — ReAct Agent with Homemade Function-Calling ✅

**Goal:** A ReAct (Reason + Act) agent that executes bash commands using homemade function-calling — no frameworks, no built-in tool/function-calling API. Raw text parsing only.

### Requirements
- [x] ReAct loop: Thought → Action → Observation → repeat until final answer
- [x] Homemade function-calling: parse raw text output yourself (string handling / regex) — no structured outputs, no tool_use API
- [x] Bash execution with safety: y/n approval before every command, workspace sandbox
- [x] No frameworks: pure Python + model API calls only

### Implementation (part_1/)
- Custom XML parsing (`<thought>`, `<action>`, `<answer>` tags)
- y/n approval prompt before every execution
- Workspace sandbox (`./workspace`), 30s timeout, 5000-char output cap
- Max 10 reasoning rounds, history rollback on API errors
- Chaining operators (`&&`, `||`, `;`, `|`, `&`) blocked at execution time
- System prompt path injected at runtime so Docker and local paths both work
- 32 unit tests + 8 integration tests, all passing

---

## Del 2 — Stronger Agent with Structured Output 🔲

**Goal:** Upgrade to mainstream structured output for parsing. Keep your own agent loop, context management, and tool-calling logic.

**What changes from Part 1:** Structured output parsing (e.g. Pydantic + `response_format`) is now allowed. String hacking no longer required. Agent loop must still be own code.

### Requirements
- [ ] **Bash with security guard** — actively detect and block destructive/harmful commands (not just y/n). Container still recommended.
- [ ] **File section editing** — agent must edit individual sections of files, not just read/write whole files
- [ ] **Multi-tool rounds before yield** — model decides itself whether to call another tool or yield final answer
- [ ] **Persistent session history** — context persists within a session (multi-session not required)
- [ ] **System prompt from config file** — loaded from file, not hardcoded. Must instruct agent to: only work on SWE tasks, refuse other topics
- [ ] **Tool output size cap** — all tools have a max output size; agent must be informed of the limit in the system prompt

---

## Del 3 — Multi-Agent Collaboration 🔲

**Goal:** Agent joins a shared group chat on a RunPod server with all students' agents and collaborates on a joint software project (project announced on lesson).

### Requirements
- [ ] **Code transfer** — send and receive code to/from other agents via group chat
- [ ] **Constructive collaboration** — contribute meaningfully; act as a responsible team-player; respect collaboration agreements negotiated by agents
- [ ] **System prompt rules** — must instruct agent NOT to leak sensitive info; collaborate safely and responsibly
- [ ] **No console I/O for main conversation** — all communication via shared RunPod group chat. Exception: local console still used for manual bash approval if applicable
- [ ] **Rate-limit + token spending cap** — built-in, adjustable in real-time via local console
- [ ] **Smart group chat participation** — solve the infinite-loop problem (every agent responding to every message). Design a mechanism: mentions/addressing, relevance filtering, turn-taking, or similar

### Examination
- 2026-05-29: All agents connected live — GraderBot evaluates each agent against criteria
- Attendance mandatory

---

## VG — Claude-Code / Codex Competitor with Sub-Agents 🔲

**Goal:** Build a competitor to Claude Code / Codex featuring sub-agent handling and context engineering. Graded against the student's own approved requirement specification + a minimum feature set, both demonstrated live.

**Canonical spec:** `#assignment-vg` Discord channel (SSoT). Local reference rubric: `~/Downloads/assn-vg-grading-template.md` (v2.0).

### Minimum feature set
- [ ] **VG.1 — Multi-agents: parallel sub-agents** — main agent starts 2+ sub-agents that run in parallel AND uses their results back in the main session
- [ ] **VG.2 — Advanced context engineering** — concrete mechanism keeps the context window under control (automatic compaction, summarising/snipping old tool output, tool-result size caps, MCP-style external context)
- [ ] **VG.3 — Real-time cost monitoring + budget warnings + hard cap** — live token/USD readout, warning threshold, AND a hard cap that actually stops the agent (not just warns)
- [ ] **VG.4 — Protection against harmful tool calls** — destructive/dangerous calls actively blocked or gated *before* execution (allow/deny-list, confirmation, sandbox); not just a prompt instruction
- [ ] **VG.5 — Bash execution** (paired with VG.4 — the guard must cover bash)
- [ ] **VG.6 — Partial file editing** — agent edits a *section* of a file (find-and-replace / line ranges), not just whole-file overwrites
- [ ] **VG.7 — Deployable / idiot-proof packaging** — `docker compose up` (or equivalent) + a README a non-author can follow
- [ ] **VG.8 — Config file + env-var secrets** — all settings in a config file, all secrets from env vars, `.env` git-ignored, `.env.example` checked in
- [ ] **VG.9 — Agent autonomy: tool-call vs. yield** — agent itself decides each turn whether to call another tool or yield back to the user

### Hard gates (any FAIL blocks VG)
- Own requirement specification authored AND approved by the examining teacher
- Student-prompted solution (no hand-written code); chat/prompt sessions shown on request
- Architecture-level understanding the student can explain orally at the demo
- Live (or recorded / AI-avatar) demo of the working system
- Artefacts (spec, build, demo evidence) actually loaded by the grader

### Substance gate (judgement, not a checkbox)
- Each claimed feature actually *works* in the live demo — not just exists in code
- Features genuinely integrated — sub-agent results actually used, the cap actually enforced, the safety gate actually blocking
- Oral check confirms architecture-level understanding (strengths, weaknesses, failure modes)
- At the goldcoin-adjusted bar: a credible product, not a checkbox shell

### Examiner benchmark
- ~3h examiner time (≈40h student-equivalent), adjusted down per goldcoins spent
- Tech-stack neutral — any language allowed; judged on system + demo
