# ReAct Agent — Assignment 2, Del 1

A Python-based ReAct agent with homemade XML function-calling.
No frameworks, no built-in tool use — just raw text parsing.

## How it works

1. You type a message
2. The LLM reasons (Thought) and decides to run a command (Action)
3. Your program parses the XML, asks you y/n, runs it
4. The result (Observation) goes back to the LLM
5. Repeat until the LLM has an Answer

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

## Tests

```bash
source .venv/bin/activate

# Unit tests (no API calls, ~0.02s)
pytest tests/test_main.py -v

# Integration tests (real Anthropic API, ~20s)
pytest tests/ -m integration -v
```

## Project structure

```
part_1/
├── main.py              # Agent loop + XML parsing
├── system_prompt.txt    # ReAct instructions for the LLM
├── Dockerfile           # Isolated container
├── docker-compose.yml   # Easy startup
├── requirements.txt     # Python deps
├── .env.example         # API key template
├── workspace/           # Safe sandbox for the agent to work in
├── tests/
│   ├── test_main.py        # Unit tests (parsers, history, startup)
│   └── test_integration.py # Integration tests (real API calls)
└── README.md
```

## Safety

- Every command requires y/n approval before execution
- Agent runs inside Docker container (can't touch your real files)
- Commands execute in /app/workspace only
- 30-second timeout on all commands
- Output truncated at 5000 chars
- Max 10 tool-call rounds per message
