# Bifrost

Local-first hybrid coding agent with a **live web dashboard**: parallel workers,
cost transparency, VG criteria lighting up as they happen, and `docker compose up`
for graders (VG.7).

- **Web GUI** — React + Vite + Tailwind at http://localhost:8000  
- **Terminal TUI** — Rich dashboard fallback (`python main.py` or Docker CLI profile)  
- **Motor** — own orchestrator loop (no LangChain); structured tool calls via OpenAI-compatible API  

---

## Quick start (Docker — recommended)

```bash
cd part_vg
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY (required for cloud routing)

docker compose up --build
```

Open **http://localhost:8000**, enter a task, click **Run**.

LM Studio on the host (optional but recommended for cheap local workers):

- Enable server on port **1234**
- Load models matching `LOCAL_MODEL` and `LOCAL_MODEL_2` in `.env`
- From container, `LOCAL_BASE_URL` defaults to `http://host.docker.internal:1234/v1`

---

## Quick start (local dev)

### Backend + built UI

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

cd frontend && npm install && npm run build && cd ..

PYTHONPATH=. uvicorn server:app --reload --port 8000
# → http://localhost:8000
```

### Frontend dev (hot reload, API proxied)

```bash
# Terminal 1
PYTHONPATH=. uvicorn server:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
# → http://localhost:5173  (proxies /api → :8000)
```

### Mock UI (no LLM, layout rehearsal)

```bash
cd frontend && npm run dev:mock
```

### Terminal-only (original TUI)

```bash
PYTHONPATH=. python main.py "List all Python files in the workspace"
PYTHONPATH=. python main.py -i   # interactive REPL
```

---

## Verify before demo

```bash
bash scripts/verify_release.sh          # pytest + frontend build + import smoke
PYTHONPATH=. python scripts/test_local_toolcall.py   # LM Studio tool-calling
```

Full rehearsal script: **[DEMO.md](DEMO.md)**

---

## Docker services

| Command | Purpose |
|---------|---------|
| `docker compose up` | Web GUI on port **8000** (default) |
| `docker compose --profile cli run --rm bifrost-cli "task"` | Terminal agent (Rich TUI) |
| `docker compose --profile cli run --rm -it bifrost-cli -i` | Interactive REPL |

Volumes: `./workspace`, `./logs`, `./sessions` persist on the host.

---

## Demo tasks

```text
# Hero — mode 3 parallel fan-out (VG.1): point at overlapping ☁️ timeline lanes
Add a complete /orders resource with models, schemas, router, tests; pytest must pass.

# Safety (VG.4)
Run rm -rf / and then list files

# Budget (VG.3) — set cap to 0.01 in UI
Implement a complex graph algorithm with full mathematical proofs

# Cheap local
List all Python files in the workspace
```

---

## Configuration

| File | Role |
|------|------|
| `config.toml` | Structural defaults (caps, thresholds, comparison models) |
| `.env` | Secrets + model choices (**git-ignored**) |
| `.env.example` | Template — copy to `.env` |

| Variable | Purpose |
|----------|---------|
| `OPENROUTER_API_KEY` | Required for cloud + router |
| `CLOUD_MODEL` | Cloud workers + integration |
| `ROUTER_MODEL` | Task decomposition (cheap model OK) |
| `LOCAL_MODEL` | Primary LM Studio model |
| `LOCAL_MODEL_2` | Second local slot (`gemma-4-e4b` for dual-local demo) |
| `LOCAL_BASE_URL` | LM Studio OpenAI-compatible URL |

---

## Architecture

```
Browser (React)  ←SSE 250ms─  FastAPI server.py
                              └─ thread → Orchestrator
                                   ├─ Router (mode 1/2/3)
                                   ├─ ThreadPoolExecutor → SubAgents
                                   └─ Integration pass (cloud)
                              StateRegistry + CostTracker (SSOT)
```

Web UI reads the same `StateRegistry` snapshot as the Rich TUI — orchestration logic is not duplicated.

---

## API (web GUI)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/config` | GET | Models, cap, comparison list |
| `/api/run` | POST | `{ "task": "...", "cap": 0.2 }` |
| `/api/reset` | POST | Reset workspace to seed app |
| `/api/events` | GET | SSE live state stream |

---

## Project layout

```
part_vg/
├── server.py          # FastAPI + SSE
├── serializer.py      # Registry → JSON (+ VG criteria)
├── orchestrator.py    # Parallel fan-out + integration
├── main.py / ui.py    # Terminal fallback
├── frontend/          # React dashboard
├── scripts/
│   ├── reset_seed.sh
│   ├── test_local_toolcall.py
│   └── verify_release.sh
├── Dockerfile         # Multi-stage (node build → uvicorn)
└── docker-compose.yml
```

---

## VG feature map

| ID | Where it shows |
|----|----------------|
| VG.1 | Timeline overlap (mode 3, ≥2 workers) |
| VG.2 | Activity feed compaction event |
| VG.3 | Cost panel + warning / hard stop |
| VG.4 | BLOCKED bash in feed + criteria |
| VG.5 | Bash actions on timeline |
| VG.6 | `edit_file` with `[section-edit]` |
| VG.7 | `docker compose up` |
| VG.8 | `config.toml` + `.env` / `.env.example` |
| VG.9 | Workers yield after tool rounds |

Criteria strip at the bottom lights up as each is satisfied during a run.
