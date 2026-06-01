"""
Context compaction for the main/orchestrator session (VG.2, D6).

When the main session history grows past token_threshold, the oldest
turns are summarised by a cheap LLM call and replaced with a single
summary message. Short-lived worker sessions rarely hit the threshold;
compaction lives in the orchestrator's session where context accumulates.

Demo tip: lower compaction.token_threshold in config.toml (e.g. to 500)
to guarantee visible triggering during the demo.
"""
import sys

from config import Config
from llm import call_llm

_COMPACT_SYSTEM = """\
You are a context compactor. The user will give you a list of conversation
turns. Summarise them into a compact paragraph (max 200 words) that
preserves all decisions made, files created or modified, and errors seen.
Omit greetings and filler. Be precise and dense.
"""

_APPROX_CHARS_PER_TOKEN = 4


def _estimate_tokens(history: list[dict]) -> int:
    total_chars = sum(len(str(m.get("content", ""))) for m in history)
    return total_chars // _APPROX_CHARS_PER_TOKEN


def compact_if_needed(
    history: list[dict],
    config: Config,
    cloud_base_url: str,
    cloud_api_key: str,
) -> bool:
    """
    Compact the oldest turns in-place if the history exceeds the threshold.
    Returns True if compaction ran, False otherwise.
    """
    estimated = _estimate_tokens(history)
    if estimated < config.compaction_token_threshold:
        return False

    # Keep the 4 most recent turns intact; summarise everything older.
    keep_tail = 4
    if len(history) <= keep_tail:
        return False

    to_summarise = history[:-keep_tail]
    tail = history[-keep_tail:]

    turns_text = "\n\n".join(
        f"[{m['role']}]: {str(m.get('content', ''))[:500]}" for m in to_summarise
    )

    # Use the compaction model (local if available, else cloud)
    if config.compaction_model == "local":
        from backends import resolve
        # We only have config here; re-check health inline for simplicity
        from llm import health_check
        from config import BackendConfig

        local_alive = health_check(config.local.base_url, config.local.api_key)
        if local_alive:
            comp_url = config.local.base_url
            comp_key = config.local.api_key
            comp_model = config.local.model
        else:
            comp_url = cloud_base_url
            comp_key = cloud_api_key
            comp_model = config.router_model
    else:
        comp_url = cloud_base_url
        comp_key = cloud_api_key
        comp_model = config.compaction_model

    response, _, _ = call_llm(
        messages=[
            {"role": "system", "content": _COMPACT_SYSTEM},
            {"role": "user", "content": turns_text},
        ],
        model=comp_model,
        base_url=comp_url,
        api_key=comp_key,
        tools=None,
        max_tokens=300,
    )

    if response is None:
        print("[compactor] summarisation failed — keeping full history", file=sys.stderr)
        return False

    summary = (response.choices[0].message.content or "").strip()
    summary_msg = {
        "role": "system",
        "content": f"[Compacted summary of {len(to_summarise)} earlier turns]: {summary}",
    }

    history.clear()
    history.append(summary_msg)
    history.extend(tail)
    print(
        f"[compactor] compacted {len(to_summarise)} turns → 1 summary "
        f"(~{estimated} → ~{_estimate_tokens(history)} tokens)",
        file=sys.stderr,
    )
    return True
