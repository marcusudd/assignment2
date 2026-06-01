import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class BackendConfig:
    base_url: str
    api_key: str
    model: str


@dataclass
class Config:
    openrouter_api_key: str
    local: BackendConfig
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

        local_api_key = os.getenv("LOCAL_API_KEY", data["local"].get("api_key", "lm-studio"))
        compaction_raw = data["compaction"]["model"]

        return cls(
            openrouter_api_key=openrouter_api_key,
            local=BackendConfig(
                base_url=data["local"]["base_url"],
                api_key=local_api_key,
                model=data["local"]["model"],
            ),
            cloud=BackendConfig(
                base_url=data["cloud"]["base_url"],
                api_key=openrouter_api_key,
                model=data["cloud"]["model"],
            ),
            router_model=data["router"]["model"],
            compaction_model=compaction_raw,
            compaction_token_threshold=data["compaction"]["token_threshold"],
            cost_cap_usd=data["cost"]["cap_usd"],
            cost_warning_threshold=data["cost"]["warning_threshold"],
            max_output=data["agent"]["max_output"],
            max_rounds=data["agent"]["max_rounds"],
            workspace_dir=data["agent"].get("workspace_dir", "./workspace"),
            comparison_models=data["cost"].get("comparison_models", []),
        )
