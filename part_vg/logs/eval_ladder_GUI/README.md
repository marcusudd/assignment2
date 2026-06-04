# Eval ladder — GUI runbook (Haiku)

**URL:** http://localhost:8000  
**Cloud:** `CLOUD_MODEL=anthropic/claude-haiku-4-5` (from `.env`)  
**Local (demo):** single-local `LOCAL_MODEL=gemma-4-26b-a4b-it-mlx`, `LOCAL_MODEL_2` unset — one model loaded in LM Studio  
**Session logs:** `part_vg/logs/*.log` (one file per run; also listed in API `/api/logs`)

## Viktigt: CLI syns inte i GUI

Körningar via `main.py` eller `docker compose exec … main.py` uppdaterar **inte** web-GUI. För live-visning:

```bash
# Terminal 1: stack
docker compose up -d

# Terminal 2: trigga alla 5 tester via API (öppna GUI först)
cd part_vg && .venv/bin/python scripts/run_eval_gui.py
```

Öppna **http://localhost:8000** (inte bara Vite :5173) innan scriptet startar.

Kör **ett test i taget** om du klistrar in prompts manuellt. Vänta tills körningen är klar (phase `done`) innan nästa.

| # | Cap (UI) | Reset workspace? | Prompt file |
|---|----------|------------------|-------------|
| 1 | $0.20 | Nej | `test_1.txt` |
| 2 | $0.20 | Nej | `test_2.txt` |
| 3 | $0.20 | **Ja** (Reset-knapp eller `bash scripts/reset_seed.sh`) | `test_3.txt` |
| 4 | **$0.35** | **Ja** | `test_4.txt` |
| 5 | **$0.02** | **Ja** | `test_5.txt` |

Efter test 4 (valfritt): `bash scripts/verify_orders.sh` från `part_vg/`.

## Vad som loggas automatiskt

Varje GUI-run skapar en timestamped log under `logs/` med:

- Task, routing summary, cost, worker backends/models, status, activity lines

## Failure-test (#5)

Förväntat: budget stop / aborted workers — **inte** att agenten säger "byt till Opus". Det är avsiktligt.
