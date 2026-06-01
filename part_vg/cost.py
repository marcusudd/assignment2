"""
Cost tracking with thread-safe budget enforcement (VG.3 + H3).

Design notes:
- TokenCounter uses threading.Lock — safe for N parallel workers.
- Hard cap is enforced by raising BudgetExceeded. Workers catch this
  at the top of their loop (cooperative abort — Python cannot kill threads
  mid-LLM-call, so pending calls finish but no new rounds start).
- Local models are priced at $0.
"""
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path


class BudgetExceeded(Exception):
    pass


@dataclass
class UsageRecord:
    worker_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


def _load_prices(prices_path: str = "model_prices.json") -> dict[str, dict]:
    path = Path(prices_path)
    if not path.exists():
        return {}
    with open(path) as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _calculate_cost(model: str, prompt_tokens: int, completion_tokens: int, prices: dict) -> float:
    # Local models (any model served via local backend) cost $0
    if model.startswith("local/") or model in ("lm-studio", "local"):
        return 0.0
    entry = prices.get(model)
    if entry is None:
        # Unknown model — return 0 rather than crashing
        return 0.0
    input_cost = entry.get("input_cost_per_token", 0.0) * prompt_tokens
    output_cost = entry.get("output_cost_per_token", 0.0) * completion_tokens
    return input_cost + output_cost


class CostTracker:
    def __init__(
        self,
        cap_usd: float,
        warning_threshold: float = 0.75,
        prices_path: str = "model_prices.json",
    ) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self.cap_usd = cap_usd
        self.warning_threshold = warning_threshold
        self.total_usd: float = 0.0
        self.records: list[UsageRecord] = []
        self._prices = _load_prices(prices_path)

        # Per-worker attribution
        self._worker_cost: dict[str, float] = {}
        self._worker_tokens: dict[str, int] = {}

    def add(
        self,
        worker_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """Record usage and return the cost. Raises BudgetExceeded at cap."""
        cost = _calculate_cost(model, prompt_tokens, completion_tokens, self._prices)
        with self._lock:
            self.total_usd += cost
            self.records.append(
                UsageRecord(worker_id, model, prompt_tokens, completion_tokens, cost)
            )
            self._worker_cost[worker_id] = self._worker_cost.get(worker_id, 0.0) + cost
            total_tokens = prompt_tokens + completion_tokens
            self._worker_tokens[worker_id] = (
                self._worker_tokens.get(worker_id, 0) + total_tokens
            )
            if self.total_usd >= self.cap_usd:
                self._stop_event.set()
                raise BudgetExceeded(
                    f"Budget cap ${self.cap_usd:.2f} exceeded "
                    f"(total: ${self.total_usd:.4f})"
                )
        return cost

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def is_warning(self) -> bool:
        with self._lock:
            return self.total_usd >= self.cap_usd * self.warning_threshold

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_usd": self.total_usd,
                "cap_usd": self.cap_usd,
                "fraction": self.total_usd / self.cap_usd if self.cap_usd > 0 else 0,
                "worker_cost": dict(self._worker_cost),
                "worker_tokens": dict(self._worker_tokens),
            }

    def counterfactual(self, comparison_models: list[str]) -> dict[str, float]:
        """Cost if the same token volumes were run entirely on each comparison model."""
        with self._lock:
            total_prompt = sum(r.prompt_tokens for r in self.records)
            total_completion = sum(r.completion_tokens for r in self.records)
        return {
            m: _calculate_cost(m, total_prompt, total_completion, self._prices)
            for m in comparison_models
        }
