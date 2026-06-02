"""
SubAgent — a clean, hub-free agent loop (VG.9 + VG.5 + VG.6).

One SubAgent = one worker thread with its own conversation history,
cost attribution, and tool dispatcher. Hub cruft from part_3/agent.py
is intentionally absent; this is a coding agent, not a chat participant.

Cooperative abort (D5): the worker checks cost_tracker.should_stop()
at the top of every round. A pending LLM call cannot be cancelled
(Python cannot kill threads), but no new rounds start after the cap fires.

Minimal escalation (D4): if the local backend returns None (connection
failure or malformed response) on the first call, the worker switches
transparently to the cloud backend for that round and all subsequent ones.
"""
import json
import sys
import time
from dataclasses import dataclass, field

from backends import BackendSpec
from config import Config
from cost import BudgetExceeded, CostTracker
from compactor import compact_if_needed
from llm import call_llm
from state import StateRegistry, WorkerState
from tools import TOOL_SCHEMAS, dispatch_tool

# Retries on transient None responses (network blips, provider 5xx) before
# a worker gives up. Separate from local→cloud escalation.
_MAX_TRANSIENT_RETRIES = 3


@dataclass
class WorkerPlan:
    worker_id: str
    role: str           # "coder" | "explorer" | "integrator" | "reviewer"
    task: str
    owned_files: list[str]
    backend_name: str   # "local" | "cloud"


class SubAgent:
    def __init__(
        self,
        plan: WorkerPlan,
        active_backend: BackendSpec,
        cloud_backend: BackendSpec,
        cost_tracker: CostTracker,
        registry: StateRegistry,
        config: Config,
        system_prompt: str,
    ) -> None:
        self.plan = plan
        self._cloud = cloud_backend
        # The orchestrator has already resolved which backend this worker uses
        # (local-0, local-1, or cloud). cloud_backend is the escalation target.
        self._active = active_backend
        self.cost_tracker = cost_tracker
        self.registry = registry
        self.config = config
        self.system_prompt = system_prompt
        self.history: list[dict] = []
        self._escalated = False
        self._failed_calls = 0

        ws = WorkerState(
            worker_id=plan.worker_id,
            role=plan.role,
            task_summary=plan.task[:60],
            backend=self._active.name,
            model=self._active.model,
        )
        registry.register(ws)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Execute the worker task. Returns a plain-text summary."""
        wid = self.plan.worker_id
        self.registry.update(wid, status="running", start_ts=time.monotonic())
        self._log(f"Starting: {self.plan.task[:80]}")

        self.history.append({"role": "user", "content": self._build_user_prompt()})

        result = self._loop()

        end_ts = time.monotonic()
        status = "done" if not self.cost_tracker.should_stop() else "aborted"
        self.registry.update(wid, status=status, end_ts=end_ts, current_action="")
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> str:
        wid = self.plan.worker_id
        # The integrator has the hardest job (read all files, fix cross-refs,
        # run + debug tests) so it gets more rounds than a single-file worker.
        rounds = self.config.max_rounds
        if self.plan.role == "integrator":
            rounds = int(rounds * 2)
        for round_num in range(rounds):

            # Cooperative stop check (D5)
            if self.cost_tracker.should_stop():
                self._log("Budget cap reached — aborting")
                self.registry.update(wid, status="aborted", current_action="aborted")
                raise BudgetExceeded("Stop signal set by another worker or cap")

            # Context engineering (VG.2, D6): compact history once it grows past
            # the threshold. No-op for short-lived workers; the long-lived
            # integrator session is where this actually fires.
            if compact_if_needed(
                self.history, self.config, self._cloud.base_url, self._cloud.api_key
            ):
                self._log("🗜 compacted history (context engineering)")

            self.registry.update(wid, current_action=f"LLM call #{round_num + 1}")
            response, prompt_tok, completion_tok = call_llm(
                messages=[{"role": "system", "content": self.system_prompt}] + self.history,
                model=self._active.model,
                base_url=self._active.base_url,
                api_key=self._active.api_key,
                tools=TOOL_SCHEMAS,
                max_tokens=4096,
            )

            if response is None:
                self._failed_calls += 1
                # Local failure → escalate to cloud once (D4).
                if not self._escalated and self._active.is_local:
                    self._escalate()
                    continue
                # Transient failure on cloud → retry the same backend a few
                # times with brief backoff before giving up.
                if self._failed_calls <= _MAX_TRANSIENT_RETRIES:
                    self._log(f"LLM call failed — retry {self._failed_calls}/{_MAX_TRANSIENT_RETRIES}")
                    time.sleep(2 * self._failed_calls)
                    continue
                self._log("LLM call failed — giving up after retries")
                self.registry.update(wid, status="error", current_action="LLM error")
                return "ERROR: LLM call failed after retries"

            # Successful response — reset the consecutive-failure counter.
            self._failed_calls = 0

            # Track cost (raises BudgetExceeded if cap hit)
            try:
                cost = self.cost_tracker.add(
                    wid, self._active.model, prompt_tok, completion_tok
                )
                snap = self.cost_tracker.snapshot()
                self.registry.update(
                    wid,
                    prompt_tokens=snap["worker_tokens"].get(wid, 0),
                    completion_tokens=0,
                    cost_usd=snap["worker_cost"].get(wid, 0.0),
                    backend=self._active.name,
                    model=self._active.model,
                )
            except BudgetExceeded:
                self._log("Budget cap hit while recording usage")
                raise

            msg = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            # Normalize finish_reason (inherited from part_3/agent.py:437-440)
            if msg.tool_calls:
                finish_reason = "tool_calls"
            elif finish_reason not in ("stop", "tool_calls"):
                finish_reason = "stop"

            assistant_entry: dict = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            self.history.append(assistant_entry)

            if finish_reason == "stop":
                reply = self._strip_thinking(msg.content or "")
                reply = reply.strip() or "(no text reply)"
                self._log(f"Done: {reply[:100]}")
                return reply

            if finish_reason == "tool_calls":
                for tc in msg.tool_calls:
                    result = self._dispatch(tc)
                    self.history.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result}
                    )

        self._log("Max rounds reached")
        return "Reached max rounds without final answer"

    def _dispatch(self, tc) -> str:
        name = tc.function.name
        try:
            inputs = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            self._log(f"⚠ malformed JSON from model for tool {name!r}")
            return "ERROR: invalid tool argument JSON from model"

        self.registry.update(
            self.plan.worker_id, current_action=f"{name}({self._fmt_inputs(name, inputs)})"
        )
        self._log(f"▶ {name}: {self._fmt_inputs(name, inputs)}")

        result = dispatch_tool(
            name,
            inputs,
            workspace_dir=self.config.workspace_dir,
            max_output=self.config.max_output,
            auto_approve=True,   # D14: AUTO_APPROVE in container
        )
        self._log(f"← {result[:120]}")
        return result

    def _escalate(self) -> None:
        """Switch from local to cloud on first failure (D4 minimal escalation)."""
        self._escalated = True
        self._active = self._cloud
        self._log(f"⚡ Escalated to cloud ({self._cloud.model}) after local failure")
        self.registry.update(
            self.plan.worker_id,
            backend=f"cloud (escalated from local)",
            model=self._cloud.model,
        )

    def _build_user_prompt(self) -> str:
        if self.plan.role == "integrator":
            return self.plan.task
        files_note = ""
        if self.plan.owned_files:
            files_note = (
                f"\n\nCreate ONLY these files: {', '.join(self.plan.owned_files)}\n"
                "Write complete, working code immediately using edit_file "
                "(old_str='' creates a new file). Do NOT explore the workspace "
                "or list files first — you already know your task. You may "
                "read_file ONLY if you need to see an existing model/schema to "
                "import from. Finish in as few steps as possible."
            )
        return self.plan.task + files_note

    def _log(self, line: str) -> None:
        self.registry.append_log(self.plan.worker_id, line)

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Remove model-internal reasoning tags that leak into output.
        Handles Gemma's <|channel>thought ... <channel|> and similar patterns."""
        import re
        # Gemma 4: <|channel>thought ... <channel|>
        text = re.sub(r"<\|channel\>thought.*?<channel\|>", "", text, flags=re.DOTALL)
        # Generic <think> ... </think> (Qwen, DeepSeek, etc.)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text.strip()

    @staticmethod
    def _fmt_inputs(name: str, inputs: dict) -> str:
        if name == "bash":
            return inputs.get("command", "")[:60]
        if name in ("read_file", "edit_file"):
            return inputs.get("path", "")
        return str(inputs)[:60]
