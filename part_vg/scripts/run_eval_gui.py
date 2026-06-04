#!/usr/bin/env python3
"""
Trigger eval-ladder tasks via POST /api/run so the web GUI (SSE) shows live progress.

CLI runs (main.py) do NOT appear in the GUI — use run_via_api.py or this script instead.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:8000"
PROMPTS_DIR = ROOT / "logs" / "eval_ladder_GUI"
LOG_DIR = ROOT / "logs"


def _ts_dir() -> Path:
    d = LOG_DIR / f"eval_gui_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(path)


def _wait_run(client: httpx.Client, run_id: str, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    with client.stream("GET", "/api/events", timeout=None) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if time.monotonic() > deadline:
                raise TimeoutError(f"run {run_id} timed out after {timeout_s}s")
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            if payload.get("run_id") != run_id:
                continue
            last = payload
            if not payload.get("running") and payload.get("phase") == "done":
                return payload
    return last


def _run_one(
    client: httpx.Client,
    out: Path,
    test_id: str,
    cap: float,
    prompt: str,
    *,
    reset_first: bool,
    timeout_s: float,
) -> dict:
    log = out / f"test_{test_id}.json"
    if reset_first:
        r = client.post("/api/reset")
        r.raise_for_status()
        time.sleep(0.5)

    r = client.post(
        "/api/run",
        json={
            "task": prompt,
            "cap": cap,
            "allow_local": True,
            "allow_cloud": True,
        },
    )
    if r.status_code == 409:
        raise RuntimeError("409: a run is already in progress — wait or refresh GUI")
    r.raise_for_status()
    run_id = r.json()["run_id"]
    print(f"[test {test_id}] started run_id={run_id} cap=${cap} — watch http://localhost:8000")
    sys.stdout.flush()

    final = _wait_run(client, run_id, timeout_s)
    log.write_text(json.dumps(final, indent=2), encoding="utf-8")
    cost = final.get("cost") or {}
    print(
        f"[test {test_id}] done cost=${cost.get('total', 0):.4f} "
        f"routing={final.get('routing', {}).get('summary', '')[:80]}"
    )
    if final.get("error"):
        print(f"[test {test_id}] error: {final['error']}")
    if final.get("result"):
        print(f"[test {test_id}] result: {str(final['result'])[:200]}")
    sys.stdout.flush()
    return final


def main() -> None:
    out = _ts_dir()
    (out / "runner.log").write_text(f"GUI eval {out.name}\n", encoding="utf-8")
    print(f"Log dir: {out}")
    print("Open http://localhost:8000 now — runs only show in GUI when triggered via API.\n")

    tests = [
        ("1", 0.20, "test_1.txt", False, 120),
        ("2", 0.20, "test_2.txt", False, 180),
        ("3", 0.20, "test_3.txt", True, 300),
        ("4", 0.35, "test_4.txt", True, 900),
        ("5", 0.02, "test_5.txt", True, 300),
    ]

    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        h = client.get("/api/health")
        h.raise_for_status()
        cfg = client.get("/api/config").json()
        print(f"cloud={cfg['cloud']['model']} locals={[l['model'] for l in cfg['locals']]}\n")

        for test_id, cap, prompt_file, reset_first, timeout_s in tests:
            prompt = _read_prompt(prompt_file)
            try:
                _run_one(client, out, test_id, cap, prompt, reset_first=reset_first, timeout_s=timeout_s)
            except Exception as e:
                print(f"[test {test_id}] FAILED: {e}", file=sys.stderr)
            time.sleep(2)

    print(f"\nFinished. Summaries in {out}")


if __name__ == "__main__":
    main()
