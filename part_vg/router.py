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
from worker_ids import assign_worker_id

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

_TEST_RE = re.compile(r'(?:^tests?/|/tests?/|^test_|/test_|_test\.py$|conftest\.py$)', re.IGNORECASE)
_MULTI_FILE_SIGNALS = re.compile(
    r"\b(?:register|pytest|main\.py|app\.py|tests?/)\b",
    re.IGNORECASE,
)
_BOILERPLATE_DIRS = {"models", "schemas", "migrations", "db", "config"}
_BOILERPLATE_FILES = {"__init__.py", "constants.py", "enums.py", "types.py"}


def _classify_backend(f: str, *, allow_cloud: bool = True) -> str:
    """Tests run on cloud (correctness critical). Everything else is local."""
    if not allow_cloud:
        return "local"
    return "cloud" if _TEST_RE.search(f) else "local"


def _classify_tier(f: str) -> str:
    """Light = boilerplate (pure data-shape files). Standard = logic-bearing."""
    p = Path(f)
    if p.name in _BOILERPLATE_FILES:
        return "light"
    if any(part in _BOILERPLATE_DIRS for part in p.parts):
        return "light"
    return "standard"


_DECOMPOSE_SYSTEM = """\
Decompose a coding task into parallel workers. Output ONLY a JSON object.

Rules (strict):
- mode 3 = 2+ files writable independently in parallel. Use when task names multiple files.
- mode 2 = single logical unit (one file, one bug fix).
- owned_files: DISJOINT across all workers. Never assign main.py/__init__.py/app.py.
- backend: "cloud" ONLY for test files (tests/ dir, conftest.py, test_*.py). Everything
  else (routers, services, models, schemas, utils, config) uses "local".
- tier: "light" for pure boilerplate (models, schemas, migrations, __init__, constants).
  "standard" for everything else (routers, services, business logic, utils).
- task: max 15 words.
- reasoning: max 10 words.

JSON schema:
{
  "mode": <2 or 3>,
  "reasoning": "<10 words>",
  "workers": [
    {"role": "coder", "task": "<15 words>", "owned_files": ["path/file.py"], "backend": "local", "tier": "standard"}
  ]
}

Bifrost assigns worker_id as realm.file-slug (e.g. midgard.models-order); do not emit w1/w2.
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

    def plan(self, task: str, *, allow_cloud: bool = True, allow_local: bool = True) -> Plan:
        if self._is_simple(task):
            used: dict[str, int] = {}
            return Plan(
                mode=1,
                reasoning="Heuristic: simple read/search task — 1 local worker",
                workers=[
                    WorkerPlan(
                        worker_id=assign_worker_id("local", [], used),
                        role="coder",
                        task=task,
                        owned_files=[],
                        backend_name="local",
                        local_tier="standard",
                    )
                ],
            )

        # Fast path: if task explicitly names 2+ disjoint .py files, decompose
        # without an LLM call — deterministic and never truncates.
        fast = self._fast_decompose(task, allow_cloud=allow_cloud)
        if fast:
            return fast

        if not allow_cloud:
            return self._fallback_mode2_local(task)

        return self._cloud_decompose(task, allow_local=allow_local, allow_cloud=allow_cloud)

    # ------------------------------------------------------------------
    def _fast_decompose(self, task: str, *, allow_cloud: bool = True) -> Plan | None:
        """If task names 2+ .py files (or 1 + pytest/register), decompose without LLM."""
        skip = {"main.py", "app.py", "__init__.py", "conftest.py"}
        all_py = re.findall(r'(?:[\w/-]+/)?[\w-]+\.py', task)
        named = [f for f in dict.fromkeys(all_py) if Path(f).name not in skip]

        if len(named) < 3:
            single = self._fast_decompose_single_named(
                task, named, skip, allow_cloud=allow_cloud
            )
            if single:
                return single
            return None

        return self._plan_from_files(task, named, allow_cloud=allow_cloud)

    def _fast_decompose_single_named(
        self, task: str, named: list[str], skip: set[str], *, allow_cloud: bool = True
    ) -> Plan | None:
        """One implementation file + pytest/register/main → add inferred test worker."""
        if len(named) != 1 or not self._implies_multi_file_work(task):
            return None

        f = named[0]
        extra: list[str] = []
        for path in re.findall(r'(?:[\w/-]+/)?[\w-]+\.py', task):
            if _TEST_RE.search(path) and path not in named and Path(path).name not in skip:
                extra.append(path)
        if not extra and re.search(r"\bpytest\b", task, re.IGNORECASE):
            inferred = self._infer_test_file(f)
            if inferred not in named:
                extra.append(inferred)

        files = named + [p for p in extra if p not in named]
        if len(files) < 2:
            return None
        return self._plan_from_files(task, files, allow_cloud=allow_cloud)

    def _implies_multi_file_work(self, task: str) -> bool:
        if _MULTI_FILE_SIGNALS.search(task):
            return True
        return bool(_MULTI_RE.search(task)) and bool(
            re.search(r"\b(?:register|main\.py)\b", task, re.IGNORECASE)
        )

    @staticmethod
    def _infer_test_file(source_py: str) -> str:
        stem = Path(source_py).stem
        return f"tests/test_{stem}.py"

    def _plan_from_files(
        self, task: str, files: list[str], *, allow_cloud: bool = True
    ) -> Plan:
        used: dict[str, int] = {}
        workers = [
            WorkerPlan(
                worker_id=assign_worker_id(
                    _classify_backend(f, allow_cloud=allow_cloud), [f], used
                ),
                role="coder",
                task=(
                    f"{task}\n\n"
                    f"YOUR PART of this task: implement `{f}`. Other agents are "
                    f"building the sibling files in parallel — implement every "
                    f"requirement above that belongs in `{f}`, including any "
                    f"business logic, validation, and edge cases."
                ),
                owned_files=[f],
                backend_name=_classify_backend(f, allow_cloud=allow_cloud),
                local_tier=_classify_tier(f),
            )
            for f in files
        ]
        n_local = sum(1 for w in workers if w.backend_name == "local")
        n_cloud = len(workers) - n_local
        return Plan(
            mode=3,
            reasoning=(
                f"Task names {len(files)} files — "
                f"{n_local} local, {n_cloud} cloud"
            ),
            workers=workers,
        )

    def _is_simple(self, task: str) -> bool:
        has_simple = bool(_SIMPLE_RE.search(task))
        has_multi = bool(_MULTI_RE.search(task))
        # Simple only if it looks read/search-like AND not a multi-file feature
        return has_simple and not has_multi

    def _cloud_decompose(
        self, task: str, *, allow_local: bool = True, allow_cloud: bool = True
    ) -> Plan:
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
            json_mode=True,
        )

        if response is None:
            print("[router] cloud decomposition failed — falling back to mode 2", file=sys.stderr)
            return self._fallback_mode2(
                task, allow_local=allow_local, allow_cloud=allow_cloud
            )

        raw = (response.choices[0].message.content or "").strip()
        return self._parse(
            raw, task, allow_local=allow_local, allow_cloud=allow_cloud
        )

    def _parse_json(self, raw: str) -> dict | None:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        no_trailing_commas = re.sub(r",\s*]", "]", re.sub(r",\s*}", "}", cleaned))
        for candidate in (cleaned, no_trailing_commas):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None

    def _parse(
        self,
        raw: str,
        task: str,
        *,
        allow_local: bool = True,
        allow_cloud: bool = True,
    ) -> Plan:
        data = self._parse_json(raw)
        if data is None:
            print("[router] JSON parse error — falling back to mode 2", file=sys.stderr)
            return self._fallback_mode2(
                task, allow_local=allow_local, allow_cloud=allow_cloud
            )

        mode = int(data.get("mode", 2))
        reasoning = data.get("reasoning", "")
        raw_workers = data.get("workers", [])
        if not raw_workers:
            return self._fallback_mode2(
                task, allow_local=allow_local, allow_cloud=allow_cloud
            )

        # Validate disjoint file ownership (D2)
        all_files: list[str] = []
        for w in raw_workers:
            all_files.extend(w.get("owned_files", []))
        if len(all_files) != len(set(all_files)):
            print("[router] overlapping owned_files detected — falling back to mode 2", file=sys.stderr)
            return self._fallback_mode2(
                task, allow_local=allow_local, allow_cloud=allow_cloud
            )

        used: dict[str, int] = {}
        workers = [
            WorkerPlan(
                worker_id=assign_worker_id(
                    w.get("backend", "cloud"),
                    w.get("owned_files", []),
                    used,
                ),
                role=w.get("role", "coder"),
                task=w.get("task", task),
                owned_files=w.get("owned_files", []),
                backend_name=w.get("backend", "cloud"),
                local_tier=w.get("tier", _classify_tier(
                    w.get("owned_files", [""])[0]
                )),
            )
            for w in raw_workers
        ]
        return Plan(mode=mode, reasoning=reasoning, workers=workers)

    def _fallback_mode2(
        self, task: str, *, allow_local: bool = True, allow_cloud: bool = True
    ) -> Plan:
        """Mode 2 when decomposition fails — prefer Midgard when available."""
        if allow_local:
            return self._fallback_mode2_local(task)
        return self._fallback_mode2_cloud(task)

    def _fallback_mode2_cloud(self, task: str) -> Plan:
        used: dict[str, int] = {}
        return Plan(
            mode=2,
            reasoning="Fallback: single cloud worker (decomposition unavailable)",
            workers=[
                WorkerPlan(
                    worker_id=assign_worker_id("cloud", [], used),
                    role="coder",
                    task=task,
                    owned_files=[],
                    backend_name="cloud",
                    local_tier="standard",
                )
            ],
        )

    def _fallback_mode2_local(self, task: str) -> Plan:
        used: dict[str, int] = {}
        return Plan(
            mode=2,
            reasoning="Fallback: single local worker (cloud disabled)",
            workers=[
                WorkerPlan(
                    worker_id=assign_worker_id("local", [], used),
                    role="coder",
                    task=task,
                    owned_files=[],
                    backend_name="local",
                    local_tier="standard",
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
