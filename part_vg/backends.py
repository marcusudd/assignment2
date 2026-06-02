"""
Backend resolution: local (LM Studio, 1 or 2 models) + cloud (OpenRouter).

On startup we health-check the local endpoint and confirm each configured
local model is actually loaded (via /v1/models). Models that aren't served
are dropped. If NO local model is available, we fall back to a single cloud
slot so the system still runs (VG.7 H2).

The dual-local switch lives in .env: set LOCAL_MODEL_2 to a second model ID
and config.locals will contain two entries → two local workers run truly in
parallel.
"""
import sys
from dataclasses import dataclass

from config import Config
from llm import list_models


@dataclass
class BackendSpec:
    name: str          # "local-0" | "local-1" | "cloud" | "cloud (local unavailable)"
    base_url: str
    api_key: str
    model: str
    is_local: bool


def resolve(config: Config) -> tuple[list[BackendSpec], BackendSpec]:
    """
    Return (local_specs, cloud_spec).

    local_specs has one entry per configured local model that is actually
    loaded in LM Studio. If none are loaded, it contains a single cloud-backed
    spec (H2 fallback) so callers can still route "local" work somewhere.
    """
    cloud = BackendSpec(
        name="cloud",
        base_url=config.cloud.base_url,
        api_key=config.cloud.api_key,
        model=config.cloud.model,
        is_local=False,
    )

    # Which models does the local endpoint actually serve right now?
    served = set(list_models(config.locals[0].base_url, config.locals[0].api_key))

    local_specs: list[BackendSpec] = []
    for bc in config.locals:
        if bc.model in served:
            local_specs.append(
                BackendSpec(
                    name=bc.name,
                    base_url=bc.base_url,
                    api_key=bc.api_key,
                    model=bc.model,
                    is_local=True,
                )
            )
        else:
            print(
                f"[backends] local model {bc.model!r} not loaded in LM Studio "
                f"— skipping {bc.name}",
                file=sys.stderr,
            )

    if not local_specs:
        print(
            "[backends] no local models available — routing local work to cloud "
            "(H2 fallback)",
            file=sys.stderr,
        )
        local_specs = [
            BackendSpec(
                name="cloud (local unavailable)",
                base_url=config.cloud.base_url,
                api_key=config.cloud.api_key,
                model=config.cloud.model,
                is_local=False,
            )
        ]
    else:
        mode = "dual-local" if len(local_specs) >= 2 else "single-local"
        print(
            f"[backends] {mode}: "
            + ", ".join(f"{s.name}={s.model}" for s in local_specs),
            file=sys.stderr,
        )

    return local_specs, cloud
