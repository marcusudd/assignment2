# BUILD_LOG — Bifrost (VG)

Maps each module to the Claude Code session that produced it (HG-2 provenance).

| Module | Session date | Notes |
|---|---|---|
| `model_prices.json` | 2026-06-01 | Curated LiteLLM pricing table |
| `config.toml` | 2026-06-01 | All non-secret configuration |
| `.env.example` | 2026-06-01 | Secret template |
| `requirements.txt` | 2026-06-01 | openai, httpx, rich, python-dotenv, pytest |
| `config.py` | 2026-06-01 | tomllib + dotenv config loader |
| `security.py` | 2026-06-01 | Adapted from part_3/agent.py — workspace_dir param |
| `tools.py` | 2026-06-01 | Adapted from part_3/agent.py — dispatch_tool with workspace_dir |
| `cost.py` | 2026-06-01 | CostTracker with threading.Lock + counterfactual |
| `llm.py` | 2026-06-01 | Generalized call_llm + health_check |
| `backends.py` | 2026-06-01 | Local + cloud backend resolution + H2 fallback |
| `state.py` | 2026-06-01 | WorkerState + thread-safe StateRegistry |
| `subagent.py` | 2026-06-01 | Clean worker loop, cooperative abort, escalation |
| `router.py` | 2026-06-01 | Heuristic + cloud LLM decomposition, disjoint file validation |
| `orchestrator.py` | 2026-06-01 | ThreadPoolExecutor fan-out + integration pass |
| `compactor.py` | 2026-06-01 | Main-session context compaction |
| `ui.py` | 2026-06-01 | Rich Live dashboard, thread-safe render loop |
| `main.py` | 2026-06-01 | CLI entry point |
| `config/system_prompt.txt` | 2026-06-01 | Worker system prompt |
| `Dockerfile` | 2026-06-01 | Container packaging |
| `docker-compose.yml` | 2026-06-01 | LM Studio bridge + env wiring |
| `tests/test_security.py` | 2026-06-01 | 12 security guard tests |
| `tests/test_cost.py` | 2026-06-01 | 7 cost tracker tests incl. thread-safety |
| `tests/test_router.py` | 2026-06-01 | 6 router heuristic + parse tests |
| `tests/test_compactor.py` | 2026-06-01 | 4 compaction tests |

All code AI-generated in Claude Code session started 2026-06-01.
Chat sessions archived in `sessions/` (shown on request per VG-HG-2).
