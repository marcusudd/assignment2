"""Realm toggle policy: workers-only backend remapping."""
from pathlib import Path

from backends import BackendSpec
from config import BackendConfig, Config
from orchestrator import Orchestrator
from subagent import WorkerPlan


def _spec(name: str, model: str, *, is_local: bool) -> BackendSpec:
    return BackendSpec(
        name=name,
        base_url="http://localhost:1234/v1",
        api_key="k",
        model=model,
        is_local=is_local,
    )


def _orch(allow_local: bool, allow_cloud: bool) -> Orchestrator:
    local = _spec("local-0", "gemma-local", is_local=True)
    cloud = _spec("cloud", "anthropic/claude-haiku-4-5", is_local=False)
    cfg = Config(
        openrouter_api_key="test-key",
        locals=[BackendConfig("local-0", local.base_url, local.api_key, local.model)],
        cloud=BackendConfig("cloud", cloud.base_url, cloud.api_key, cloud.model),
        router_model=cloud.model,
        compaction_model="local",
        compaction_token_threshold=8000,
        cost_cap_usd=1.0,
        cost_warning_threshold=0.75,
        comparison_models=[],
        max_output=5000,
        max_rounds=10,
        workspace_dir="./workspace",
    )
    from cost import CostTracker
    from state import StateRegistry

    return Orchestrator(
        config=cfg,
        local_backends=[local],
        cloud_backend=cloud,
        cost_tracker=CostTracker(
            cap_usd=1.0,
            prices_path=str(Path(__file__).resolve().parent.parent / "model_prices.json"),
        ),
        registry=StateRegistry(),
        worker_system_prompt="test",
        allow_local=allow_local,
        allow_cloud=allow_cloud,
    )


def test_local_worker_forced_to_cloud_when_midgard_off():
    orch = _orch(allow_local=False, allow_cloud=True)
    wp = WorkerPlan("midgard.primary", "coder", "task", [], "local", "standard")
    assert orch._backend_for(wp).is_local is False
    assert orch._backend_for(wp).name == "cloud"


def test_cloud_worker_forced_to_local_when_asgard_off():
    orch = _orch(allow_local=True, allow_cloud=False)
    wp = WorkerPlan("asgard.primary", "coder", "task", [], "cloud", "standard")
    assert orch._backend_for(wp).is_local is True
    assert orch._backend_for(wp).name == "local-0"


def test_normal_routing_when_both_enabled():
    orch = _orch(allow_local=True, allow_cloud=True)
    local_wp = WorkerPlan("midgard.primary", "coder", "task", [], "local", "standard")
    cloud_wp = WorkerPlan("asgard.primary", "coder", "task", [], "cloud", "standard")
    assert orch._backend_for(local_wp).is_local is True
    assert orch._backend_for(cloud_wp).is_local is False


def _orch_dual() -> Orchestrator:
    """Orchestrator with two local backends: capable (local-0) + light (local-1)."""
    capable = _spec("local-0", "gemma-26b", is_local=True)
    light = _spec("local-1", "gemma-4b", is_local=True)
    cloud = _spec("cloud", "anthropic/claude-haiku-4-5", is_local=False)
    cfg = Config(
        openrouter_api_key="test-key",
        locals=[
            BackendConfig("local-0", capable.base_url, capable.api_key, capable.model),
            BackendConfig("local-1", light.base_url, light.api_key, light.model),
        ],
        cloud=BackendConfig("cloud", cloud.base_url, cloud.api_key, cloud.model),
        router_model=cloud.model,
        compaction_model="local",
        compaction_token_threshold=8000,
        cost_cap_usd=1.0,
        cost_warning_threshold=0.75,
        comparison_models=[],
        max_output=5000,
        max_rounds=10,
        workspace_dir="./workspace",
    )
    from cost import CostTracker
    from state import StateRegistry

    return Orchestrator(
        config=cfg,
        local_backends=[capable, light],
        cloud_backend=cloud,
        cost_tracker=CostTracker(
            cap_usd=1.0,
            prices_path=str(Path(__file__).resolve().parent.parent / "model_prices.json"),
        ),
        registry=StateRegistry(),
        worker_system_prompt="test",
        allow_local=True,
        allow_cloud=True,
    )


def test_dual_local_standard_gets_capable_slot():
    orch = _orch_dual()
    wp = WorkerPlan("midgard.routers-orders", "coder", "task", ["routers/orders.py"], "local", "standard")
    backend = orch._backend_for(wp)
    assert backend.model == "gemma-26b"  # locals[0]


def test_dual_local_light_gets_small_slot():
    orch = _orch_dual()
    wp = WorkerPlan("midgard.models-order", "coder", "task", ["models/order.py"], "local", "light")
    backend = orch._backend_for(wp)
    assert backend.model == "gemma-4b"  # locals[-1]


def test_single_local_both_tiers_same_slot():
    orch = _orch(allow_local=True, allow_cloud=True)
    standard_wp = WorkerPlan("midgard.routers-orders", "coder", "task", [], "local", "standard")
    light_wp = WorkerPlan("midgard.models-order", "coder", "task", [], "local", "light")
    # Single local loaded → both tiers get the same slot
    assert orch._backend_for(standard_wp).name == orch._backend_for(light_wp).name
