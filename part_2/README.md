# ReAct Agent — Del 2

Software engineering agent using OpenRouter tool_use API. Extends Part 1 with structured output, file editing, multi-tool rounds, and active security guards.

## Setup

```bash
# 1. Copy env file and add your API key
cp .env.example .env

# 2. Run in Docker (recommended — safe sandbox)
docker compose run --rm agent

# 3. Or run locally
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Docker

```bash
docker compose run --rm agent
```

## Tools

| Tool | Description |
|---|---|
| `bash` | Run a single shell command in the workspace |
| `read_file` | Read a file relative to the workspace |
| `edit_file` | Replace an exact section of a file |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required |
| `MODEL` | `anthropic/claude-sonnet-4-6` | Model to use |
| `WORKSPACE_DIR` | `./workspace` | Sandbox directory |
| `MAX_OUTPUT` | `5000` | Max chars per tool output |
| `MAX_ROUNDS` | `20` | Max tool-calling rounds per message |
| `DEBUG` | `false` | Log raw API responses |

## Tests

```bash
source .venv/bin/activate

# Unit tests (no API calls)
pytest tests/test_main.py -v

# Integration tests (real API, ~30s)
pytest tests/ -m integration -v
```
