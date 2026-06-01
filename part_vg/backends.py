"""
Backend resolution: local (LM Studio) + cloud (OpenRouter).

On startup, health-check the local endpoint. If it is unreachable, fall
back to cloud for all routing slots so the system still runs (VG.7 H2).
The decision is logged once and visible in the UI.
"""
import sys
from dataclasses import dataclass

from config import BackendConfig, Config
from llm import health_check


@dataclass
class BackendSpec:
    name: str          # "local" | "cloud" | "cloud (local unavailable)"
    base_url: str
    api_key: str
    model: str
    is_local: bool


def resolve(config: Config) -> tuple[BackendSpec, BackendSpec]:
    """
    Return (local_spec, cloud_spec).

    If the local endpoint fails its health check, local_spec is wired to the
    cloud backend so callers can use it without special-casing.  The name
    field reflects the override so the UI can show it.
    """
    cloud = BackendSpec(
        name="cloud",
        base_url=config.cloud.base_url,
        api_key=config.cloud.api_key,
        model=config.cloud.model,
        is_local=False,
    )

    local_alive = health_check(config.local.base_url, config.local.api_key)
    if local_alive:
        local = BackendSpec(
            name="local",
            base_url=config.local.base_url,
            api_key=config.local.api_key,
            model=config.local.model,
            is_local=True,
        )
    else:
        print(
            f"[backends] local endpoint {config.local.base_url!r} unreachable "
            f"— routing all slots to cloud (H2 fallback)",
            file=sys.stderr,
        )
        local = BackendSpec(
            name="cloud (local unavailable)",
            base_url=config.cloud.base_url,
            api_key=config.cloud.api_key,
            model=config.cloud.model,
            is_local=False,
        )

    return local, cloud
