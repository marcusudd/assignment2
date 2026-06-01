"""
Router — the brain of Bifrost (D3).

Three modes:
  1  Simple  → 1 local worker, no LLM planning needed
  2  Hard    → 1 cloud worker (single complex task)
  3  Multi   → cloud LLM decomposes into N parallel workers

The decomposition call always runs on the cloud model because a bad plan
destroys everything downstream (D3: "spend on what's actually hard").
"""
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from config import Config
from llm import call_llm
from subagent import WorkerPlan

# Patterns that reliably indicate a simple, read-only or single-file task
_SIMPLE_RE = re.compile(
    r"\b(list|find|search|grep|count|show|display|print|read|cat|"
    r"what|which|how many|summarize|explain)\b",
    re.IGNORECASE,
)

# Patterns that suggest multi-file work
_MULTI_RE = re.compile(
    r"\b(add|create|implement|build|scaffold|generate|refactor|migrate|"
    r"endpoint|feature|resource|module|service|schema|model|test)\b",
    re.IGNORECASE,
)

_DECOMPOSE_SYSTEM = """\
You are a senior software architect decomposing a coding task for a
parallel multi-agent system. Your output is JSON only — no prose.

Rules:
- owned_files must be DISJOINT across all workers (no file appears twice).
- Shared framework files (main.py, __init__.py, app.py) are NOT assigned
  to any worker; the orchestrator handles them after the fan-out.
- Assign backend "local" for mechanical tasks (ORM models, Pydantic schemas,
  simple CRUD boilerplate); "cloud" for tasks requiring reasoning (business
  logic, edge-case tests, complex algorithms).
- Keep worker tasks self-contained: each worker should be able to complete
  its task using only bash, read_file, and edit_file within the workspace.
- If the task cannot meaningfully be split (only one logical unit of work),
  set mode=2 and provide exactly one worker.

Output schema (strict JSON):
{
  "mode": 2 or 3,
  "reasoning": "<one sentence>",
  "workers": [
    {
      "worker_id": "w1",
      "role": "coder",
      "task": "<detailed task description>",
      "owned_files": ["relative/path/to/file.py"],
      "backend": "local" or "cloud",
      "rationale": "<why this backend>"
    }
  ]
}
"""


@dataclass
class Plan:
    mode: int
    reasoning: str
    workers: list[WorkerPlan]


class Router:
    def __init__(self, config: Config, cloud_base_url: str, cloud_api_key: str) -> None:
        self.config = config
        self._cloud_base_url = cloud_base_url
        self._cloud_api_key = cloud_api_key

    def plan(self, task: str) -> Plan:
        if self._is_simple(task):
            return Plan(
                mode=1,
                reasoning="Heuristic: simple read/search task — 1 local worker",
                workers=[
                    WorkerPlan(
                        worker_id="w1",
                        role="coder",
                        task=task,
                        owned_files=[],
                        backend_name="local",
                    )
                ],
            )
        return self._cloud_decompose(task)

    # ------------------------------------------------------------------
    def _is_simple(self, task: str) -> bool:
        has_simple = bool(_SIMPLE_RE.search(task))
        has_multi = bool(_MULTI_RE.search(task))
        # Simple only if it looks read/search-like AND not a multi-file feature
        return has_simple and not has_multi

    def _cloud_decompose(self, task: str) -> Plan:
        workspace_ctx = self._workspace_context()
        user_msg = (
            f"Task: {task}\n\n"
            f"Current workspace contents:\n{workspace_ctx}\n\n"
            "Produce a decomposition plan as JSON."
        )
        response, pt, ct = call_llm(
            messages=[{"role": "user", "content": user_msg}],
            model=self.config.router_model,
            base_url=self._cloud_base_url,
            api_key=self._cloud_api_key,
            tools=None,
            max_tokens=1024,
        )

        if response is None:
            print("[router] cloud decomposition failed — falling back to mode 2", file=sys.stderr)
            return self._fallback_mode2(task)

        raw = (response.choices[0].message.content or "").strip()
        return self._parse(raw, task)

    def _parse(self, raw: str, task: str) -> Plan:
        # Strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            print(f"[router] JSON parse error: {e} — falling back to mode 2", file=sys.stderr)
            return self._fallback_mode2(task)

        mode = int(data.get("mode", 2))
        reasoning = data.get("reasoning", "")
        raw_workers = data.get("workers", [])
        if not raw_workers:
            return self._fallback_mode2(task)

        # Validate disjoint file ownership (D2)
        all_files: list[str] = []
        for w in raw_workers:
            all_files.extend(w.get("owned_files", []))
        if len(all_files) != len(set(all_files)):
            print("[router] overlapping owned_files detected — falling back to mode 2", file=sys.stderr)
            return self._fallback_mode2(task)

        workers = [
            WorkerPlan(
                worker_id=w.get("worker_id", f"w{i+1}"),
                role=w.get("role", "coder"),
                task=w.get("task", task),
                owned_files=w.get("owned_files", []),
                backend_name=w.get("backend", "cloud"),
            )
            for i, w in enumerate(raw_workers)
        ]
        return Plan(mode=mode, reasoning=reasoning, workers=workers)

    def _fallback_mode2(self, task: str) -> Plan:
        return Plan(
            mode=2,
            reasoning="Fallback: single cloud worker (decomposition unavailable)",
            workers=[
                WorkerPlan(
                    worker_id="w1",
                    role="coder",
                    task=task,
                    owned_files=[],
                    backend_name="cloud",
                )
            ],
        )

    def _workspace_context(self) -> str:
        ws = Path(self.config.workspace_dir)
        if not ws.exists():
            return "(workspace empty)"
        try:
            result = subprocess.run(
                ["find", ".", "-type", "f", "-not", "-path", "./.git/*"],
                capture_output=True, text=True, timeout=5, cwd=ws,
            )
            lines = result.stdout.strip().splitlines()
            if not lines:
                return "(workspace empty)"
            return "\n".join(lines[:40])
        except Exception:
            return "(could not list workspace)"
