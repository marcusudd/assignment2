# Multi-Agent Demo

Kör flera agenter lokalt och se dem prata med varandra i en webbläsare.

## Starta

```bash
cd part_3

# Terminal 1 — starta hubben med web dashboard
python frontend_demo/mock_hub.py

# Öppna webbläsaren
open http://localhost:8080

# Terminal 2 — starta tre agenter
python frontend_demo/run_agents.py
```

## Vad händer

| Komponent | Vad den gör |
|---|---|
| `mock_hub.py` | Lokal hub-server + chat UI på port 8080 |
| `run_agents.py` | Startar marcus-developer, alice-tester, bob-architect |
| Webbläsaren | Visar live-chatten, uppdateras var 2:a sekund |

Du kan också skriva egna meddelanden via text-fältet i webbläsaren.

## Konfigurera

Ändra i `run_agents.py` under `AGENTS = [...]`:
- `name` — agentens namn i chatten
- `persona` — personlighet och roll
- `msg_cap` — max meddelanden per agent
- `token_cap` — max tokens per agent

## Notera

- `AUTO_APPROVE=true` är satt automatiskt — bash-kommandon godkänns utan y/n
- Alla agenter delar samma `workspace/`-mapp
- Modell: `openai/gpt-4o-mini` (billig och snabb)
