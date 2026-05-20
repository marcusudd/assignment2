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
