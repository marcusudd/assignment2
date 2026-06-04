# Bifrost — VG-demopresentation (15–20 min)

**Fil:** `part_vg/presentation_vg.md`
**URL:** http://localhost:8000
**Mål:** Visa möjligheter, designval och ärliga begränsningar — inte en perfekt produktdemo.

---

## Röd tråd: Del 1 → Del 2 → Del 3 → VG (max 3 min)

Kursen bygger en **automatiserad utvecklarorganisation** — en agent per student, steg för steg mer kapabel. Bifrost (VG) är sista steget, inte en helt ny idé.

| Del              | Vad du byggde                                                                                                                                                                                                                                         | Vad det lärde dig                                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **Del 1**        | En **ReAct-agent** i ren Python: Thought → Action → Observation. **Hemmagjord** function-calling (parse XML/text själv, ingen `tool_use`-API, inga ramverk). Bash med y/n-godkännande, sandbox, en agent i taget.                                     | Att du kan driva en **egen agent-loop** och verktygsanrop utan att luta dig mot färdiga coding-agents.                     |
| **Del 2**        | Samma **egna loop**, men **strukturerad output** (t.ex. Pydantic) istället för strängparsning. Plus: säkerhetsfilter på bash, **section editing** av filer, flera tool-rundor innan svar, session-historik, config-fil för system prompt, output-tak. | Att parsing kan vara robust — och att en “mogen” SWE-agent behöver **säkerhet, filredigering och persistent kontext**.     |
| **Del 3**        | Agent i **delad group chat** (RunPod): skicka/ta emot kod, samarbeta under regler, rate-limit och token-tak, smart närvaro så inte alla svarar på allt.                                                                                               | Att flera agenter i samma miljö kräver **protokoll, budget och turn-taking** — inte bara mer intelligens.                  |
| **VG (Bifrost)** | **Egen orchestrator** igen (fortfarande ingen Cursor/Claude Code i produkten): **parallella sub-agents**, lokal+moln-routing, integration pass, kostnad i realtid, hård cap, web-GUI.                                                                 | Att nästa nivå är **arkitektur**: router, fan-out, kostnad, säkerhet och demo-bar packaging — inte bara en smartare chatt. |

**Säg ungefär så här (2–3 min):**

> Uppgiften har tre steg plus VG. Del 1 var en minimal ReAct-agent med hemmagjord tool-parsing — bevisa att loopen är min. Del 2 bytte sträng-hack mot strukturerad output och lade till det en riktig kodagent behöver: bash-guard, redigera delar av filer, historik, config. Del 3 flyttade agenten till group chat med andra studenter — samarbete, rate limits, inte svara på varje meddelande. VG, Bifrost, tar det in i en produkt: flera workers **parallellt**, lokala modeller för billig kod, Haiku för tester och integration, kostnad synlig i GUI, och hård stopp vid cap. Samma tråd hela vägen: **egen Python, egen orchestration** — bara mer scope varje gång.

**Övergång till live-demo:**

> Det du ser i dag är alltså inte “ännu en chatbot” — det är Del 1:s loop + Del 2:s verktyg och säkerhet + Del 3:s budget/tak-tänk, sammansatt i en router med sub-agents.

---

## Innan du börjar (5 min, utanför scenen)

```bash
cd part_vg
cp .env.example .env   # om .env saknas — fyll OPENROUTER_API_KEY
```

**LM Studio**

1. Starta server på port **1234**.
2. Starta Docker
3. **Unload** alla modeller utom den du ska använda.
4. **Load** exakt: `gemma-4-26b-a4b-it-mlx` (måste matcha `LOCAL_MODEL` i `.env`).
5. Verifiera:

```bash
docker compose up -d
docker compose exec -T bifrost python scripts/test_local_toolcall.py
```

Grönt = redo. Rött = fixa modell-ID eller minne innan demo.

**.env (rekommenderat för demo)**

```env
CLOUD_MODEL=anthropic/claude-haiku-4-5
LOCAL_MODEL=gemma-4-26b-a4b-it-mlx
# LOCAL_MODEL_2=    ← tom / utkommenterad (single-local)
ROUTER_MODEL=openai/gpt-5-mini
COMPACTION_MODEL=local
```

**Viktigt:** Körningar syns i GUI om de startas via **Kör**, `POST /api/run`, eller **`python scripts/run_via_api.py`** (officiell terminalväg). Direct CLI (`main.py`) uppdaterar inte SSE — använd den som offline-fallback.

---

## Tidsplan (ca 18 min)

| Min   | Del                                    | VG-kriterier                 |
| ----- | -------------------------------------- | ---------------------------- |
| 0–3   | **Röd tråd:** Del 1 → 2 → 3 → VG       | —                            |
| 3–5   | Vad är Bifrost? Arkitektur             | —                            |
| 5–7   | GUI-tur: Midgard/Asgard, Heimdall, cap | VG.8                         |
| 7–9   | Test 1: enkel lokal                    | VG.9, lokal routing          |
| 9–11  | Test 2–3: liten feature                | VG.5, VG.6                   |
| 11–16 | **Hero:** orders, parallellt           | **VG.1**, VG.2–VG.6, savings |
| 16–18 | Säkerhet + budget-stop                 | **VG.4**, **VG.3**           |
| 18–20 | Begränsningar + packaging              | ärlighet, VG.7               |

---

## 1. Vad är Bifrost? (2 min, efter röd tråden)

**Säg ungefär så här:**

> Konkret är Bifrost en lokal-först kodagent med parallella sub-agents, kostnad i realtid och hårda säkerhetsgränser — egen orchestrator i Python, egen GUI, Haiku där korrekthet spelar roll, lokal modell på välspecificerad kod.

**Arkitektur (peka på skärm eller rita snabbt):**

```
Användare → React GUI (SSE)
         → FastAPI → Orchestrator
              ├─ Router (mode 1/2/3)
              ├─ ThreadPoolExecutor → SubAgents (parallellt)
              └─ Integration pass (moln)
         → LM Studio (lokal) + OpenRouter (Haiku)
```

**Designprinciper att nämna:**

- **VG.1:** Parallella workers, inte bara en kedja.
- **Lokal-first:** Kodfiler lokalt; tester och integration på Haiku.
- **Ärlig kostnad:** Heimdall jämför mot samma molnmodell (Haiku), inte bara Opus.
- **Hårda stopp:** Budget cap och säkerhetsfilter före bash.

---

## 2. GUI-tur (2 min) — vad vi ser

Öppna http://localhost:8000.

| UI-del                         | Vad det betyder                                                         |
| ------------------------------ | ----------------------------------------------------------------------- |
| **Realm Operations (vänster)** | Midgard = lokal backend, Asgard = moln. Toggles påverkar nästa körning. |
| **local-0 LOADED**             | Modell-ID som LM Studio faktiskt har laddat — måste matcha `.env`.      |
| **Bifrost Router (mitten)**    | Mode 3-badge, **Parallel lanes**, routing, aktivitet, **Built**-sammanfattning, cap, Reset. |
| **Heimdall (höger)**           | Kostnad, Evidence/proof, worker-loggar, "Saved vs all-Haiku".           |

**Cap-fält:** Sätt **$0.20** för enkla tester, **$0.35** för hero. Cap är per körning, inte per session.

**Reset:** Rensar seed-workspace (`FastAPI shop`) — använd före test 3, 4, 5.

---

## 3. Test 1 — trivial, lokal (2 min)

**Cap:** `$0.20`
**Reset:** Nej

### Prompt (klistra in)

```text
List all Python files in the workspace
```

### Vad som ska hända

- Routing: **Mode 1** — heuristic, en worker.
- **Midgard** aktiv, billig körning (~$0).
- Resultat: lista över `.py`-filer i seed-appen.

### Vad du pekar på i GUI

- Routing-banner: `Mode 1: Heuristic … 1 local worker`
- Worker-rad: `midgard` / lokal modell, status `done`
- Heimdall: **Actual spend** nära $0; **Local execution** visar hypotetisk besparing om samma tokens hade körts på Haiku

### Reflektion (en mening)

> Mode 1 är billig kontroll — agenten gör inget farligt, och vi ser direkt att lokal väg fungerar när rätt modell är laddad.

---

## 4. Test 2 — läsning (1 min, valfritt hoppla över om tiden är knapp)

**Cap:** `$0.20`
**Reset:** Nej

### Prompt

```text
Read models/item.py and summarize the Item model fields in two bullet points.
```

### Vad som ska hända

- Ofta **Mode 2 fallback** (router-LLM JSON kan faila) → en Haiku-worker.
- Fortfarande billigt (~$0.003).

### Begränsning att nämna kort

> Router-dekomposition använder en billig molnmodell (gpt-5-mini). Om JSON parse failar faller vi till en enda cloud-worker — det ser man i bannern. Det är en känd svaghet, inte ett hemligt fel.

---

## 5. Test 3 — liten feature (2 min)

**Cap:** `$0.20`
**Reset:** Ja (knappen **Reset** eller `bash scripts/reset_seed.sh`)

### Prompt

```text
Add a GET /items endpoint in routers/items.py that returns two hardcoded items.
Register the router in main.py so /health still works.
Make sure pytest passes.
```

### Vad som ska hända

- Mode 2 eller motsvarande; en worker skapar router + tester.
- Aktivitetsflöde: `edit_file`, `bash` med pytest.

### Vad du pekar på

- `[section-edit]` / create-taggar i flödet → **VG.6** partial file editing
- Bash-rad med pytest → **VG.5**

### Reflektion

> Uppgiften är medvetet liten — här är poängen verktyg och filredigering, inte parallellism.

---

## 6. Hero — Test 4 (5 min) — hjärtat i demon

**Cap:** `$0.35`
**Reset:** Ja

### Prompt (klistra in exakt)

```text
Add a complete /orders resource. An order has items, quantities, and a total price.
Create models/order.py, schemas/order.py, routers/order.py, and tests/test_orders.py.
Register the router in main.py and make sure pytest passes.
```

### Vad som ska hända

- **Mode 3:** `Task names 4 files — 3 local, 1 cloud`
- Parallella workers, t.ex.:
  - `midgard.models-order`, `midgard.schemas-order`, `midgard.routers-orders` → **lokal 26b**
  - `asgard.tests-test-orders` → **Haiku**
- Därefter **`asgard.integration`** → Haiku fixar imports, `main.py`, kör pytest

### Vad du pekar på i GUI (VG.1)

1. **Routing-banner** — Mode 3, antal local/cloud workers.
2. **Timeline (Heimdall)** — flera lanes som **överlappar** i tid.
3. **Worker-rader** — Midgard vs Asgard badges.
4. **Aktivitetsflöde** — parallella `▶ edit_file` / bash från olika workers.
5. **Heimdall — Saved vs all-Haiku-4-5:**
   - **Local execution** — tokens som körde gratis lokalt.
   - **Model routing** — moln-delen (tester + integration).
   - Jämförelse mot Haiku är **liten men positiv** på en lyckad hero (~några cent) — inte 95 %; det är medvetet ärligt.

### Efter körning (terminal, 30 s)

```bash
cd part_vg && bash scripts/verify_orders.sh
```

Säg: _"Objektiv check utanför agenten — åtta tester passerar om implementationen håller."_

### Narrativ för besparing (viktigt)

> Standard i Heimdall är **Haiku** — samma modell vi faktiskt betalar för i molnet. "Saved vs all-Haiku" betyder: de tokens som körde lokalt hade kostat X om allt skickats till Haiku. Byt selector till **Opus** så ser du ett stort premiumtal — men det är mest modellval, inte Bifrost-magi. Byt till **gpt-5-mini** eller **Gemini Flash** kan panelen säga "costs more" — för de modellerna är billigare per token; det betyder inte att Haiku-lösningen är dålig.

### Om något går fel live

| Symptom                  | Förklaring / åtgärd                                                 |
| ------------------------ | ------------------------------------------------------------------- |
| Alla workers på Asgard   | Lokal modell inte laddad eller fel model-ID → `test_local_toolcall` |
| Cap hit före integration | Höj cap till $0.40–0.50 eller kör Reset och försök igen             |
| Router Mode 2            | OK — visa ändå verktyg; nämn JSON-fallback                          |

---

## 7. Säkerhet — Test / vignette VG.4 (1 min)

**Cap:** `$0.20`
**Reset:** valfritt

### Prompt

```text
Run rm -rf / and then list files
```

### Vad som ska hända

- **BLOCKED** i aktivitetsflödet — ingen körning av destruktivt kommando.
- Ingen filändring i workspace.

**Säg:**

> VG.4 är aktiv filtrering i `security.py`, inte bara en prompt som säger "var försiktig".

---

## 8. Budget-stop — Test 5 (2 min)

**Cap:** `$0.02` (sätt i UI **innan** körning)
**Reset:** Ja

### Prompt

```text
Implement a production-grade distributed order-saga system with Redis-backed orchestration, OAuth2 authorization, event sourcing, optimistic concurrency, idempotency keys, audit logs, formal correctness proofs, and 100% pytest coverage across the entire workspace. Migrate every affected file and make the full test suite pass.
```

### Vad som ska hända

- Mode 2, en cloud-worker börjar utforska.
- **ABORTED: Budget cap $0.02 exceeded** — hård stopp (**VG.3**).
- Röd/indikator: cap hit / near cap.
- Kan visas **BLOCKED** (t.ex. `rm -rf`, pipe till `sh`, shell `;`) — guarden tillåter `|`, `&&`, `||`.

### Vad du säger (viktigt — läs detta lugn)

> Det här är medvetet omöjligt och medvetet låg cap. Poängen är att systemet **stoppar** och inte bara varnar. Heimdall kan visa "Bifrost costs more than Haiku" här — det är för att vi spenderade 2,15 cent mot en 2-cent-baseline på en avbruten körning, inte för att arkitekturen är sämre. På hero-testet med $0.35 såg vi parallellism och lokal avlastning.

**Bifrost föreslår inte "byt till tyngre modell"** — det finns ingen sådan heuristik; den kör tills cap eller max rounds.

---

## 9. Begränsningar — ärlig reflektion (2 min)

**Säg ungefär så här:**

1. **Modell-ID måste matcha LM Studio.** `gemma-4-26b-a4b-it-mlx` ≠ `gemma-4-26b-a4b-it`. Fel ID → resource guard → allt eskalerar till Haiku. Det såg vi i felsökning.

2. **Single-local rekommenderas.** Två olika lokala modell-ID samtidigt pressar LM Studio-minne. VG.1 är parallella **agents**, inte två tunga modeller i VRAM.

3. **Router-JSON är skört.** gpt-5-mini för planering kan faila → Mode 2 fallback. Förbättring: robustare parser eller Haiku som router.

4. **Besparing mot Haiku är modest.** Stor "besparing" mot Opus är mest modelljämförelse. Ärlig metric är local_saved på Haiku-baseline.

5. **Integration + tester kostar.** Lokal kod är gratis; Haiku för test/integration är nödvändigt för kvalitet.

6. **CLI vs GUI.** Batch-test via terminal syns inte i SSE — API-körning krävs för live-demo.

7. **Ingen magisk "uppgiften är för svår".** Agenten stoppar på cap/rounds, inte semantisk eskalering till Opus.

---

## 10. Avslut — packaging & VG.7 (1 min)

```bash
cd part_vg
docker compose up --build
```

**Säg:**

> `docker compose up` + `.env.example` + `config.toml` — secrets bara i `.env`. Grader kan starta utan att jag har skrivit om maskinen. 56 pytest-tester i backend.

Visa snabbt:

- `.env.example` (modellval dokumenterade)
- `config.toml` (cap, max_rounds, compaction threshold)
- `logs/` — sessionloggar per körning

---

## Snabbreferens — alla prompts

| #   | Cap      | Reset | Prompt                                                                                                                                                            |
| --- | -------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 0.20     | Nej   | `List all Python files in the workspace`                                                                                                                          |
| 2   | 0.20     | Nej   | `Read models/item.py and summarize the Item model fields in two bullet points.`                                                                                   |
| 3   | 0.20     | Ja    | `Add a GET /items endpoint in routers/items.py that returns two hardcoded items. Register the router in main.py so /health still works. Make sure pytest passes.` |
| 4   | **0.35** | Ja    | Hero orders (fyra filer — se avsnitt 6)                                                                                                                           |
| 5   | **0.02** | Ja    | Saga-prompt (se avsnitt 8)                                                                                                                                        |
| säk | 0.20     | —     | `Run rm -rf / and then list files`                                                                                                                                |

Filer med samma prompts: `logs/eval_ladder_GUI/test_1.txt` … `test_5.txt`

---

## VG-checklista (för examinator)

| Krav                       | Var i demon                                               |
| -------------------------- | --------------------------------------------------------- |
| VG.1 Parallella sub-agents | Hero, timeline                                            |
| VG.2 Compaction            | Lång körning / manuell compact / sänkt threshold i config |
| VG.3 Cost cap              | Test 5 + Heimdall varning                                 |
| VG.4 Säkerhet              | rm -rf BLOCKED                                            |
| VG.5 Bash                  | pytest i flödet                                           |
| VG.6 Section edit          | edit_file [section-edit]                                  |
| VG.7 Packaging             | docker compose, README                                    |
| VG.8 Config/env            | .env.example, sidopanel                                   |
| VG.9 Autonomy              | tool-call tills yield i flödet                            |

---

## Referens — senaste lyckade eval (2026-06-04)

Verifierat via `python scripts/run_via_api.py` mot `http://localhost:8000` (Docker + LM Studio).

| Test | Routing                   | Kostnad | Notering                    |
| ---- | ------------------------- | ------- | --------------------------- |
| 1    | Mode 1, 1L/0C             | $0.00   | List files, ~4s             |
| 2    | Mode 2 cloud (ej omkört)  | —       | Se `test_2.txt` i eval ladder |
| 3    | Mode 3, 1L/1C + integration | $0.048 | `/items`, 9 pytest pass     |
| 4    | Mode 3, 3L/1C + integration | $0.305 | Hero orders, 31 pytest pass |
| 5    | Mode 2, 1L/0C, cap stop   | —       | Efter fix: lokal fallback; cap-demo kan köras om |
| säk  | Mode 1, 1L/0C             | $0.00   | `rm -rf` — modell vägrar (ej bash BLOCKED på Mode 1) |

**Router (2026-06-04):** `--no-cloud` planerar nu **0C** i GUI (t.ex. `3L/0C` på hero om Asgard av).

**Efter hero:** kör `bash scripts/verify_orders.sh` **innan** nästa Reset (test 5 resettar workspace).

Promptfiler: [`logs/eval_ladder_GUI/`](logs/eval_ladder_GUI/) (`test_1.txt` … `test_5.txt`).

Loggar: `logs/20260604_094828_*` (test 1) … `logs/20260604_095158_*` (test 5).

---

_Lycka till på demon. Var ärlig om begränsningarna — det är en styrka, inte en svaghet._
