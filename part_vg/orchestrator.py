"""
Orchestrator — parallel fan-out + integration pass (D1, D2, D8, D5, H1).

Flow:
  1. Router produces a Plan (mode 1/2/3).
  2. For mode 3: N SubAgents start simultaneously via ThreadPoolExecutor.
     start_ts values overlap → genuine parallelism proof (H1).
  3. Cooperative abort: if BudgetExceeded fires in any worker, the stop
     event is set and remaining workers halt at their next loop top.
  4. Integration pass (cloud): reads all worker outputs, makes fixup edits
     (cross-file imports, registers router in main.py, etc.), runs tests.
  5. Returns final result string.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from backends import BackendSpec
from config import Config
from cost import BudgetExceeded, CostTracker
from router import Plan, Router
from state import StateRegistry, WorkerState
from subagent import SubAgent, WorkerPlan


def _attach_sibling_files(workers: list[WorkerPlan]) -> list[WorkerPlan]:
    """Tell each worker which files its siblings own (avoids read_file on directories)."""
    if len(workers) <= 1:
        return workers
    enriched: list[WorkerPlan] = []
    for wp in workers:
        siblings: list[str] = []
        for other in workers:
            if other.worker_id == wp.worker_id:
                continue
            for path in other.owned_files:
                if path and path not in siblings:
                    siblings.append(path)
        enriched.append(replace(wp, sibling_files=siblings))
    return enriched


_INTEGRATION_SYSTEM = """\
You are a senior engineer doing an integration pass after parallel workers
have each written one file. Your job:

1. Read every file listed in the task using read_file.
2. Fix any cross-file reference errors (wrong import names, missing
   registrations, type mismatches between schemas and routers).
   If a worker listed schemas/*.py but that file is missing, create it first.
3. Register any new routers/modules in the app's main entry point
   (e.g. app.include_router(...) in main.py).
4. Run the test suite with bash: python3 -m pytest tests/ -x -q
   Pipes (|), && and || are allowed. Semicolons (;) and background (&) are blocked.
   python3 -c "import x; print(x)" is fine (semicolons inside quotes are not blocked).
5. If tests fail, apply the minimal fix to make them pass and re-run.
6. Reply with a short summary: what you fixed and whether tests passed.

Be surgical — only change what is broken. Do not rewrite working code.
"""


class Orchestrator:
    def __init__(
        self,
        config: Config,
        local_backends: list[BackendSpec],
        cloud_backend: BackendSpec,
        cost_tracker: CostTracker,
        registry: StateRegistry,
        worker_system_prompt: str,
        *,
        allow_local: bool = True,
        allow_cloud: bool = True,
    ) -> None:
        self.config = config
        self.locals = local_backends      # 1 or 2 local slots (dual-local)
        self.cloud = cloud_backend
        self.cost_tracker = cost_tracker
        self.registry = registry
        self.worker_system_prompt = worker_system_prompt
        self.allow_local = allow_local
        self.allow_cloud = allow_cloud
        self.router = Router(
            config=config,
            cloud_base_url=cloud_backend.base_url,
            cloud_api_key=cloud_backend.api_key,
        )
        self.plan: Plan | None = None
        self.routing_summary: str = ""

    def _pick_local_slot(self, tier: str = "standard") -> BackendSpec:
        """Two-tier local selection:
        - "light" (boilerplate) → locals[-1] (smaller/faster model)
        - "standard" (logic) → locals[0] (capable model)
        Falls back gracefully if only one local is loaded.
        """
        true_local = [s for s in self.locals if s.is_local]
        pool = true_local if true_local else self.locals
        if len(pool) == 1:
            return pool[0]
        if tier == "light":
            return pool[-1]
        return pool[0]

    def _backend_for(self, wp: WorkerPlan) -> BackendSpec:
        """Map a worker's logical backend to a physical slot.

        Realm toggles (UI) remap workers only — router decomposition still uses cloud.
        """
        if wp.backend_name == "local":
            if not self.allow_local:
                return self.cloud
            return self._pick_local_slot(wp.local_tier)
        if not self.allow_cloud:
            return self._pick_local_slot(wp.local_tier)
        return self.cloud

    def run(self, task: str) -> str:
        """Top-level entry. Returns a plain-text result."""
        self.registry.set_phase("routing")
        self.plan = self.router.plan(task)
        self.plan.workers = _attach_sibling_files(self.plan.workers)
        self.routing_summary = (
            f"Mode {self.plan.mode}: {self.plan.reasoning} "
            f"({len(self.plan.workers)} worker(s))"
        )
        self.registry.set_routing(self.plan.mode, self.routing_summary)
        self.registry.append_run_log(f"🔀 Router: {self.routing_summary}")
        print(f"[orchestrator] {self.routing_summary}", file=sys.stderr)

        if self.plan.mode == 1:
            result = self._run_single(self.plan.workers[0])
            self.registry.set_phase("done")
            return result
        if self.plan.mode == 2:
            result = self._run_single(self.plan.workers[0])
            self.registry.set_phase("done")
            return result
        result = self._run_fanout(self.plan)
        self.registry.set_phase("done")
        return result

    # ------------------------------------------------------------------
    # Mode 1 / 2 — single worker
    # ------------------------------------------------------------------
    def _run_single(self, wp: WorkerPlan) -> str:
        self.registry.set_phase("fanout")
        backend = self._backend_for(wp)
        agent = self._make_agent(wp, backend)
        try:
            return agent.run()
        except BudgetExceeded as e:
            return f"ABORTED: {e}"

    # ------------------------------------------------------------------
    # Mode 3 — parallel fan-out (VG.1)
    # ------------------------------------------------------------------
    def _run_fanout(self, plan: Plan) -> str:
        workers = plan.workers
        n = len(workers)
        results: dict[str, str] = {}
        agents: dict[str, SubAgent] = {}

        for wp in workers:
            backend = self._backend_for(wp)
            agents[wp.worker_id] = self._make_agent(wp, backend)

        print(
            f"[orchestrator] fan-out: {n} workers starting simultaneously",
            file=sys.stderr,
        )

        self.registry.set_phase("fanout")
        with ThreadPoolExecutor(max_workers=n) as executor:
            future_to_id = {
                executor.submit(agents[wp.worker_id].run): wp.worker_id
                for wp in workers
            }
            for future in as_completed(future_to_id):
                wid = future_to_id[future]
                try:
                    results[wid] = future.result()
                except BudgetExceeded as e:
                    results[wid] = f"ABORTED: {e}"
                except Exception as e:
                    results[wid] = f"ERROR: {e}"

        if self.cost_tracker.should_stop():
            return "Run aborted: budget cap reached during parallel execution."

        # Integration pass — uses results and modifies files (D8, VG.1 substance)
        self.registry.set_phase("integration")
        return self._integration_pass(plan, results)

    # ------------------------------------------------------------------
    # Integration pass (D8)
    # ------------------------------------------------------------------
    def _integration_pass(self, plan: Plan, worker_results: dict[str, str]) -> str:
        all_files = [f for wp in plan.workers for f in wp.owned_files]
        summary_lines = [
            f"Worker {wid}: {res[:120]}" for wid, res in worker_results.items()
        ]
        task = (
            f"Integration pass after {len(plan.workers)} parallel workers.\n\n"
            f"Files produced: {', '.join(all_files) or '(none listed)'}\n\n"
            f"Worker summaries:\n" + "\n".join(summary_lines)
        )

        integration_wp = WorkerPlan(
            worker_id="asgard.integration",
            role="integrator",
            task=task,
            owned_files=[],       # integrator may edit any file
            backend_name="cloud",
        )

        # SubAgent.__init__ registers its own WorkerState entry with the
        # registry, so no manual register needed here.
        agent = SubAgent(
            plan=integration_wp,
            active_backend=self.cloud,
            cloud_backend=self.cloud,
            cost_tracker=self.cost_tracker,
            registry=self.registry,
            config=self.config,
            system_prompt=_INTEGRATION_SYSTEM,
        )
        try:
            return agent.run()
        except BudgetExceeded as e:
            return f"Integration aborted (budget): {e}"

    # ------------------------------------------------------------------
    def _make_agent(self, wp: WorkerPlan, backend: BackendSpec) -> SubAgent:
        return SubAgent(
            plan=wp,
            active_backend=backend,
            cloud_backend=self.cloud,
            cost_tracker=self.cost_tracker,
            registry=self.registry,
            config=self.config,
            system_prompt=self.worker_system_prompt,
        )
