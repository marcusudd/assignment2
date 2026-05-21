"""
Part 3 — Multi-Agent Group Chat
Connects to the Hell's Agents Hub and collaborates on a shared software project.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import random

from dotenv import load_dotenv

load_dotenv()

import log as _log
import agent as ag
import hub
from console import AgentState, Console

AGENT_NAME = os.getenv("AGENT_NAME", "mini_me1")
MSG_CAP = int(os.getenv("MSG_CAP", "10"))
TOKEN_CAP = int(os.getenv("TOKEN_CAP", "50000"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "4"))
RESPONSE_DELAY = float(os.getenv("RESPONSE_DELAY", "0"))


def validate_startup() -> None:
    if not Path("config/system_prompt.txt").exists():
        raise SystemExit("ERROR: config/system_prompt.txt not found. Run from part_3 directory.")
    workspace = Path(ag.WORKSPACE_DIR)
    if not workspace.exists():
        workspace.mkdir(parents=True)
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit("ERROR: OPENROUTER_API_KEY is not set.")


def main() -> None:
    validate_startup()

    log = _log.get()
    system_prompt = ag.load_system_prompt()
    token_counter = ag.TokenCounter(cap=TOKEN_CAP)
    state = AgentState(msg_cap=MSG_CAP, token_counter=token_counter)
    history: list = []

    console = Console(state)
    console.start()

    dry = hub.DRY_RUN
    log.info("=" * 50)
    log.info("Part 3 — Multi-Agent Group Chat")
    log.info("Agent  : %s", AGENT_NAME)
    log.info("Model  : %s", ag.MODEL)
    log.info("Hub    : %s", hub.HUB_URL)
    log.info("Mode   : %s", "DRY-RUN (no posts)" if dry else "LIVE")
    log.info("Caps   : %d msgs / %d tokens", MSG_CAP, TOKEN_CAP)
    log.info("Delay  : %.1fs", RESPONSE_DELAY)
    log.info("=" * 50)

    # Fast-forward: skip messages already in hub so we only react to new ones.
    # Without this, stale messages from a previous session with old agent names
    # would cause mention-routing to block all responses.
    try:
        bootstrap = hub.fetch_messages(0)
        if bootstrap:
            state.last_seen = bootstrap[-1]["seq"]
            log.info("fast-forward to seq %d (%d existing msgs skipped)", state.last_seen, len(bootstrap))
    except Exception as e:
        log.warning("bootstrap fetch failed: %s", e)

    while state.running:
        if state.paused:
            time.sleep(1)
            continue

        if state.messages_sent >= state.msg_cap:
            log.info("message cap reached (%d). sending sign-off.", state.msg_cap)
            signoff = f"[{AGENT_NAME} signing off — message cap reached. Handing off to the team.]"
            try:
                hub.send_message(AGENT_NAME, signoff)
            except Exception as e:
                log.warning("sign-off failed: %s", e)
            break

        if token_counter.exceeded():
            log.warning("token cap reached (%d). paused — use 'cap N' in console to raise.", token_counter.cap)
            state.paused = True
            time.sleep(POLL_INTERVAL)
            continue

        try:
            new_msgs = hub.fetch_messages(state.last_seen)
        except Exception as e:
            log.error("fetch error: %s", e)
            time.sleep(POLL_INTERVAL)
            continue

        if not new_msgs:
            log.debug("no new messages — polling again in %.1fs", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
            continue

        state.last_seen = new_msgs[-1]["seq"]
        log.info("← %d new msg(s), last seq=%d", len(new_msgs), state.last_seen)

        for m in new_msgs:
            log.info("  [%s]: %s", m["agent_name"], m["content"][:120])

        # Filter out own messages to avoid self-echo
        external = [m for m in new_msgs if m["agent_name"] != AGENT_NAME]
        if not external:
            log.debug("all messages are own — skipping")
            time.sleep(POLL_INTERVAL)
            continue

        # Mention routing: skip only if a message STARTS with @other (primary address).
        # Incidental @mentions mid-message ("great @mini_me2! now let's...") do not block.
        mentioned_me = any(f"@{AGENT_NAME}" in m["content"] for m in external)
        mentioned_other = (
            not mentioned_me and
            any(
                m["content"].strip().startswith("@") and f"@{AGENT_NAME}" not in m["content"]
                for m in external
            )
        )

        log.info("routing  mentioned_me=%s  mentioned_other=%s", mentioned_me, mentioned_other)

        if mentioned_other:
            log.info("SKIP — message is primarily addressed to another agent")
            time.sleep(POLL_INTERVAL)
            continue

        # Unaddressed task: wait RESPONSE_DELAY, then recheck — maybe someone
        # else already claimed it, in which case we fold their response into context.
        if not mentioned_me and RESPONSE_DELAY > 0:
            jitter = random.uniform(0, RESPONSE_DELAY * 0.3)
            wait = RESPONSE_DELAY + jitter
            log.info("unaddressed task — waiting %.1fs before responding", wait)
            time.sleep(wait)
            try:
                rechecked = hub.fetch_messages(state.last_seen)
                if rechecked:
                    state.last_seen = rechecked[-1]["seq"]
                    new_from_others = [m for m in rechecked if m["agent_name"] != AGENT_NAME]
                    if new_from_others:
                        log.info("recheck: %d new msg(s) from others — adding to context", len(new_from_others))
                        for m in new_from_others:
                            log.info("  [%s]: %s", m["agent_name"], m["content"][:120])
                    external += new_from_others
            except Exception:
                pass

        # When explicitly @mentioned, override PASS — the agent MUST respond.
        active_prompt = system_prompt
        if mentioned_me:
            active_prompt += (
                f"\n\nOVERRIDE: @{AGENT_NAME} was directly mentioned in the messages above. "
                f"You MUST reply with actual content. Replying with PASS is not allowed here. "
                f"If you cannot complete the full task right now, acknowledge and describe what you will do next."
            )
            log.info("@mentioned — PASS override active")

        log.info("→ calling LLM (history=%d entries)", len(history))
        reply = ag.decide(external, AGENT_NAME, active_prompt, history, token_counter)
        log.info("← LLM reply: %s", reply[:120] if reply != "PASS" else "PASS")

        # If @mentioned but still PASS: retry once with a stronger nudge, then fallback.
        if reply == "PASS" and mentioned_me:
            log.info("@mentioned but LLM said PASS — retrying with stronger nudge")
            retry_prompt = active_prompt + (
                "\n\nFINAL INSTRUCTION: Write your response now. "
                "Do not say PASS. Start writing immediately."
            )
            reply = ag.decide(external, AGENT_NAME, retry_prompt, history, token_counter)
            log.info("← retry reply: %s", reply[:120] if reply != "PASS" else "PASS")

        if reply == "PASS" and mentioned_me:
            reply = "On it! I'll take care of my part now."
            log.info("fallback reply used (still PASS after retry)")

        # For unaddressed tasks: nudge once to prevent total silence.
        # Applies to all agents regardless of RESPONSE_DELAY.
        if reply == "PASS" and not mentioned_me:
            log.info("unaddressed task PASS — retrying with workspace-aware nudge")
            try:
                ws_files = subprocess.run(
                    "find . -type f 2>/dev/null | head -40",
                    shell=True, capture_output=True, text=True,
                    timeout=5, cwd=ag.WORKSPACE_DIR,
                ).stdout[:600] or "(empty workspace)"
            except Exception:
                ws_files = "(workspace check failed)"
            nudge_prompt = active_prompt + (
                f"\n\nWORKSPACE FILES RIGHT NOW:\n{ws_files}\n\n"
                f"Based on what is MISSING from the workspace and what has been discussed: "
                f"pick ONE uncompleted piece of work and implement it with your tools. "
                f"Do NOT say PASS."
            )
            reply = ag.decide(external, AGENT_NAME, nudge_prompt, history, token_counter)
            log.info("← nudge reply: %s", reply[:120] if reply != "PASS" else "PASS")

        if reply == "PASS":
            log.info("PASS — sleeping %.1fs", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
            continue

        # Truncate to hub max
        if len(reply) > 4096:
            reply = reply[:4090] + "\n…"

        try:
            hub.send_message(AGENT_NAME, reply)
            state.messages_sent += 1
            log.info("SENT (%d/%d): %s", state.messages_sent, state.msg_cap, reply[:120])
        except hub.RateLimitError as e:
            log.warning("rate-limited: %s", e)
        except Exception as e:
            log.error("send error: %s", e)

        time.sleep(POLL_INTERVAL)

    log.info("agent stopped.")


if __name__ == "__main__":
    main()
