import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class BackendConfig:
    name: str          # "local-0", "local-1", "cloud"
    base_url: str
    api_key: str
    model: str


@dataclass
class Config:
    openrouter_api_key: str
    locals: list[BackendConfig]      # 1 or 2 local backends (dual-local switch)
    cloud: BackendConfig
    router_model: str
    compaction_model: str
    compaction_token_threshold: int
    cost_cap_usd: float
    cost_warning_threshold: float
    max_output: int
    max_rounds: int
    workspace_dir: str
    comparison_models: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, toml_path: str = "config.toml", env_path: str = ".env") -> "Config":
        load_dotenv(env_path)

        cfg_file = Path(toml_path)
        if not cfg_file.exists():
            raise FileNotFoundError(f"Config file not found: {toml_path}")
        with open(cfg_file, "rb") as f:
            data = tomllib.load(f)

        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not openrouter_api_key:
            raise ValueError(
                "OPENROUTER_API_KEY not set. Copy .env.example to .env and fill it in."
            )

        # --- Model choices: .env wins, config.toml is a structural fallback ---
        def _pick(env_key: str, *toml_path_keys: str, default: str = "") -> str:
            val = os.getenv(env_key)
            if val is not None and val.strip():
                return val.strip()
            node: object = data
            for k in toml_path_keys:
                if isinstance(node, dict) and k in node:
                    node = node[k]
                else:
                    return default
            return node if isinstance(node, str) else default

        # --- Local backends (1 or 2) ---
        local_base_url = _pick(
            "LOCAL_BASE_URL", "local", "base_url",
            default="http://localhost:1234/v1",
        )
        local_api_key = os.getenv("LOCAL_API_KEY", "lm-studio")
        local_model_1 = _pick("LOCAL_MODEL", "local", "model")
        local_model_2 = os.getenv("LOCAL_MODEL_2", "").strip()

        locals_: list[BackendConfig] = [
            BackendConfig("local-0", local_base_url, local_api_key, local_model_1)
        ]
        if local_model_2:
            locals_.append(
                BackendConfig("local-1", local_base_url, local_api_key, local_model_2)
            )

        cloud_base_url = _pick(
            "CLOUD_BASE_URL", "cloud", "base_url",
            default="https://openrouter.ai/api/v1",
        )

        return cls(
            openrouter_api_key=openrouter_api_key,
            locals=locals_,
            cloud=BackendConfig(
                name="cloud",
                base_url=cloud_base_url,
                api_key=openrouter_api_key,
                model=_pick("CLOUD_MODEL", "cloud", "model",
                            default="anthropic/claude-sonnet-4-6"),
            ),
            router_model=_pick("ROUTER_MODEL", "router", "model",
                               default="openai/gpt-5-mini"),
            compaction_model=_pick("COMPACTION_MODEL", "compaction", "model",
                                   default="local"),
            compaction_token_threshold=data["compaction"]["token_threshold"],
            cost_cap_usd=data["cost"]["cap_usd"],
            cost_warning_threshold=data["cost"]["warning_threshold"],
            max_output=data["agent"]["max_output"],
            max_rounds=data["agent"]["max_rounds"],
            workspace_dir=data["agent"].get("workspace_dir", "./workspace"),
            comparison_models=data["cost"].get("comparison_models", []),
        )
