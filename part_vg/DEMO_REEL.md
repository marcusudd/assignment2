# Bifrost — demo reel

Kort, effektfull körning: **bas → parallellism + compaction → cap-stopp → guard**.
~8 min. Du styr från en interaktiv terminal; tittar i GUI:t.

**Setup:** 2 terminaler + webbläsare.
- **Terminal A** = styrning · **Terminal B** = verify-skript · **Browser** = http://localhost:8000

---

## Start

Prep (en gång): LM Studio på :1234 med `gemma-4-26b-a4b-it-mlx` laddad, sen:
```bash
cd /Users/marcus/projects/ai1/assignment2/part_vg
docker compose up -d --build      # rensar workspace automatiskt
PYTHONPATH=. .venv/bin/python scripts/run_via_api.py --preflight   # ska säga → READY
```

Starta **Terminal A** (interaktiv) och öppna browsern:
```bash
cd /Users/marcus/projects/ai1/assignment2/part_vg
PYTHONPATH=. .venv/bin/python scripts/run_via_api.py -i
```

> Kommandon i terminalen: `cap <usd>` · `clear` · `compact` · `local on|off` · `cloud on|off` · `exit`.
> Allt annat du skriver körs som en task. Medan en task streamar är terminalen upptagen —
> tryck **Compact** i GUI:t då.

---

## 1 · Bas (cap 0.20)

```
cap 0.20
```
```
Create main.py: a FastAPI app titled "Demo Shop API" with a GET /health endpoint returning {"status": "ok"}. Also create conftest.py at the workspace root that (1) inserts the workspace root on sys.path, and (2) defines a pytest fixture named "client" returning fastapi.testclient.TestClient(app), importing app from main.
```
*Ser:* lokal worker skapar `main.py` + `conftest.py`. *Not:* bygger basen + `client`-fixturen som hero behöver.

---

## 2 · Hero — parallellism + compaction (cap 0.40, INGEN clear)

```
cap 0.40
```
```
Add a complete /orders resource. An order has items, quantities, and a total price. Create exactly four files: models/order.py, schemas/order.py, routers/orders.py, and tests/test_orders.py. In the tests, use the existing "client" fixture from conftest.py (a TestClient) — do not create another conftest. Keep the test suite focused: one test that creates an order and checks the computed total, and one that lists orders. Register the router in main.py and make sure pytest passes.
```
**Medan den kör:** klicka **Compact** i GUI:t → "compacted ×N"-chip.
*Ser:* Mode 3, överlappande **parallel lanes** (VG.1), `edit_file`/pytest i flödet, compacted-chip (VG.2).

Efteråt i **Terminal B**:
```bash
cd /Users/marcus/projects/ai1/assignment2/part_vg && bash scripts/verify_orders.sh
```
*→ `Files OK … pass`.*

---

## 3 · Cap-stopp (cap 0.02, clear, MOLN)

```
local off
cap 0.02
clear
```
```
Implement a production-grade distributed order-saga system with Redis-backed orchestration, OAuth2 authorization, event sourcing, optimistic concurrency, idempotency keys, audit logs, formal correctness proofs, and 100% pytest coverage across the entire workspace. Migrate every affected file and make the full test suite pass.
```
*Ser:* Mode 2 **cloud**-worker, kostnad klättrar → ⚠ varning 75% → **budget-stoppad banner** → `ABORTED ~$0.026`.
*Not:* `local off` tvingar moln — en lokal körning är gratis och skulle aldrig tripa en USD-cap (VG.3).

Återställ Midgard efteråt:
```
local on
```

---

## 4 · Guard (cap 0.20)

```
cap 0.20
```
```
Create a 5MB binary test fixture by running: dd if=/dev/zero of=fixture.bin bs=1M count=5
```
*Ser:* `← BLOCKED (dd command)` i flödet, agenten löser med Python (VG.4).

Backstop i **Terminal B**:
```bash
cd /Users/marcus/projects/ai1/assignment2/part_vg && PYTHONPATH=. .venv/bin/python scripts/verify_guard.py
```
*→ 10 blockerade / 4 tillåtna.*

---

## Avsluta

```
clear
exit
```
Kostnad hela reel (Haiku) ≈ **$0.25**.
