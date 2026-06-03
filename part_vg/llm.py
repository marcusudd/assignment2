"""
Thin wrapper around the OpenAI-compatible chat API.
Supports any base_url — LM Studio local or OpenRouter cloud.
"""
import sys
from typing import Any

from openai import APIError, OpenAI

_RESOURCE_GUARD_MARKERS = (
    "insufficient system resources",
    "model loading was stopped",
)


def _log_api_error(model: str, base_url: str, err: APIError) -> None:
    msg = str(err).lower()
    if any(m in msg for m in _RESOURCE_GUARD_MARKERS):
        print(
            f"[llm] LM Studio resource guard for {model!r} — "
            "use single-local (one model loaded) or unload other models in LM Studio",
            file=sys.stderr,
        )
    else:
        print(f"[llm] API error ({model!r} @ {base_url}): {err}", file=sys.stderr)


def call_llm(
    messages: list[dict],
    model: str,
    base_url: str,
    api_key: str,
    tools: list[dict] | None = None,
    max_tokens: int = 2048,
    json_mode: bool = False,
) -> tuple[Any | None, int, int]:
    """
    Call the LLM and return (response, prompt_tokens, completion_tokens).
    Returns (None, 0, 0) on any error.
    """
    try:
        client = OpenAI(base_url=base_url, api_key=api_key)
        kwargs: dict = dict(model=model, max_tokens=max_tokens, messages=messages)
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**kwargs)
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        return response, prompt_tokens, completion_tokens
    except APIError as e:
        _log_api_error(model, base_url, e)
        return None, 0, 0
    except Exception as e:
        print(f"[llm] unexpected error ({type(e).__name__}): {e}", file=sys.stderr)
        return None, 0, 0


def health_check(base_url: str, api_key: str, timeout: float = 3.0) -> bool:
    """Return True if the endpoint responds to a model-list request."""
    import httpx

    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return r.status_code < 500
    except Exception:
        return False


def list_models(base_url: str, api_key: str, timeout: float = 3.0) -> list[str]:
    """Return the model IDs the endpoint currently serves (empty on failure)."""
    import httpx

    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        data = r.json().get("data", [])
        return [m.get("id", "") for m in data]
    except Exception:
        return []
