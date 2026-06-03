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
import ast
import json
import re
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
_CLOUD_THRASH_ABORT = 5
_BASE_MAX_TOKENS = 4096
_HIGH_MAX_TOKENS = 8192
_MAX_MAX_TOKENS = 16384
_LENGTH_TOKEN_BUMP = 4096
_MAX_LENGTH_RETRIES = 2


def repair_tool_arguments(raw: str) -> dict | None:
    """Try to salvage malformed tool-call JSON from the model."""
    if not raw or not raw.strip():
        return {}
    s = raw.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)
    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    try:
        parsed = ast.literal_eval(s)
        if isinstance(parsed, dict):
            return parsed
    except (SyntaxError, ValueError):
        pass
    return None


@dataclass
class WorkerPlan:
    worker_id: str
    role: str           # "coder" | "explorer" | "integrator" | "reviewer"
    task: str
    owned_files: list[str]
    backend_name: str   # "local" | "cloud"
    local_tier: str = "standard"  # "light" (boilerplate) | "standard" (logic)


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
        self._chaining_blocks = 0
        self._consecutive_tool_failures = 0  # thrash-detection

        ws = WorkerState(
            worker_id=plan.worker_id,
            role=plan.role,
            task_summary=plan.task[:60],
            owned_files=list(plan.owned_files),
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
        realm = "Midgard" if self.plan.backend_name == "local" else "Asgard"
        self._log(f"▶ [{realm}] lane started — {self.plan.task[:72]}")

        self.history.append({"role": "user", "content": self._build_user_prompt()})

        result = self._loop()

        end_ts = time.monotonic()
        status = "done" if not self.cost_tracker.should_stop() else "aborted"
        self.registry.update(wid, status=status, end_ts=end_ts, current_action="")
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _initial_max_tokens(self) -> int:
        if self.plan.role == "integrator":
            return _HIGH_MAX_TOKENS
        if self.plan.role == "coder":
            for path in self.plan.owned_files:
                if "test" in path.lower():
                    return _HIGH_MAX_TOKENS
        return _BASE_MAX_TOKENS

    def _loop(self) -> str:
        wid = self.plan.worker_id
        # The integrator has the hardest job (read all files, fix cross-refs,
        # run + debug tests) so it gets more rounds than a single-file worker.
        rounds = self.config.max_rounds
        if self.plan.role == "integrator":
            rounds = int(rounds * 2)
        current_max_tokens = self._initial_max_tokens()
        length_retries = 0
        for round_num in range(rounds):

            # Cooperative stop check (D5)
            if self.cost_tracker.should_stop():
                self._log("Budget cap reached — aborting")
                self.registry.update(wid, status="aborted", current_action="aborted")
                raise BudgetExceeded("Stop signal set by another worker or cap")

            # Context engineering (VG.2, D6): compact history when threshold
            # exceeded OR when manually requested via UI button.
            force = self.registry.should_compact()
            if compact_if_needed(
                self.history, self.config,
                self._cloud.base_url, self._cloud.api_key,
                force=force,
            ):
                self._log("🗜 compacted history (context engineering)")
                # Clear only after a real compaction so a forced no-op on a
                # short-lived worker doesn't swallow the manual request.
                self.registry.clear_compact()

            model_short = self._active.model.split("/")[-1][:20]
            self.registry.update(
                wid,
                current_action=f"{model_short} thinking…"
            )
            response, prompt_tok, completion_tok = call_llm(
                messages=[{"role": "system", "content": self.system_prompt}] + self.history,
                model=self._active.model,
                base_url=self._active.base_url,
                api_key=self._active.api_key,
                tools=TOOL_SCHEMAS,
                max_tokens=current_max_tokens,
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
            raw_finish = response.choices[0].finish_reason

            if raw_finish == "length":
                if (
                    length_retries < _MAX_LENGTH_RETRIES
                    and current_max_tokens < _MAX_MAX_TOKENS
                ):
                    length_retries += 1
                    current_max_tokens = min(
                        current_max_tokens + _LENGTH_TOKEN_BUMP, _MAX_MAX_TOKENS
                    )
                    self._log(
                        f"⚠ output truncated — retrying with max_tokens={current_max_tokens}"
                    )
                    continue
                self._log("⚠ output truncated — giving up after token limit bumps")
                return "ERROR: LLM output truncated (max_tokens)"

            finish_reason = raw_finish
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
                    # Thrash-detection: local workers that keep failing are
                    # better off escalated than burning all their rounds.
                    is_failure = (
                        result.startswith("ERROR:")
                        or "old_str not found" in result
                        or result.startswith("BLOCKED")
                    )
                    if is_failure:
                        self._consecutive_tool_failures += 1
                    else:
                        self._consecutive_tool_failures = 0
                    if (
                        self._consecutive_tool_failures >= 3
                        and not self._escalated
                        and self._active.is_local
                    ):
                        self._log("⚡ Thrash detected — escalating to cloud")
                        self._escalate()
                        self._consecutive_tool_failures = 0
                    if (
                        self._consecutive_tool_failures >= _CLOUD_THRASH_ABORT
                        and not self._active.is_local
                    ):
                        self._log(
                            "Circuit breaker: too many consecutive cloud failures — aborting worker"
                        )
                        return "Aborted: repeated tool failures on cloud worker"

        self._log("Max rounds reached")
        return "Reached max rounds without final answer"

    def _dispatch(self, tc) -> str:
        name = tc.function.name
        raw_args = tc.function.arguments or "{}"
        try:
            inputs = json.loads(raw_args)
        except json.JSONDecodeError:
            repaired = repair_tool_arguments(raw_args)
            if repaired is None:
                self._log(f"⚠ malformed JSON from model for tool {name!r}")
                return "ERROR: invalid tool argument JSON from model"
            inputs = repaired
            self._log(f"⚠ repaired malformed JSON for tool {name!r}")

        model_short = self._active.model.split("/")[-1][:16]
        human_action = self._human_action(name, inputs, model_short)
        self.registry.update(self.plan.worker_id, current_action=human_action)
        if name == "edit_file":
            detail = f"{self._fmt_inputs(name, inputs)} [section-edit]"
        elif name == "write_file":
            detail = f"{self._fmt_inputs(name, inputs)} [write]"
        else:
            detail = self._fmt_inputs(name, inputs)
        self._log(f"▶ {name}: {detail}")

        result = dispatch_tool(
            name,
            inputs,
            workspace_dir=self.config.workspace_dir,
            max_output=self.config.max_output,
            auto_approve=True,   # D14: AUTO_APPROVE in container
        )
        if (
            name == "bash"
            and result.startswith("BLOCKED")
            and (
                "shell command separator" in result
                or "background execution" in result
            )
        ):
            self._chaining_blocks += 1
            if self._chaining_blocks >= 2:
                result += (
                    "\n\nYou have repeated blocked shell separators. "
                    "Cwd is already the workspace; use | or && instead of ;."
                )
        else:
            self._chaining_blocks = 0
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
                "Write complete, working code immediately using write_file(path, content). "
                "Use edit_file only to patch an existing section after read_file. "
                "Do NOT explore the workspace or list files first — you already know your task. "
                "You may read_file ONLY if you need to see an existing model/schema to "
                "import from. Finish in as few steps as possible."
            )
        return self.plan.task + files_note

    def _log(self, line: str) -> None:
        self.registry.append_log(self.plan.worker_id, line)

    @staticmethod
    def _human_action(tool: str, inputs: dict, model_short: str) -> str:
        """Return a human-readable status for the Status column."""
        if tool == "bash":
            cmd = inputs.get("command", "")[:30]
            return f"{model_short}: $ {cmd}"
        if tool == "write_file":
            path = inputs.get("path", "?")
            return f"{model_short}: writing {path}"
        if tool == "edit_file":
            path = inputs.get("path", "?")
            return f"{model_short}: editing {path}"
        if tool == "read_file":
            path = inputs.get("path", "?")
            return f"{model_short}: reading {path}"
        return f"{model_short}: {tool}"

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
        if name in ("read_file", "edit_file", "write_file"):
            return inputs.get("path", "")
        return str(inputs)[:60]
