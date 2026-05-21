"""
Part 3 — Multi-Agent Group Chat
Connects to the Hell's Agents Hub and collaborates on a shared software project.
"""

import datetime
import os
import re
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import random

from dotenv import load_dotenv

load_dotenv()

import log as _log
import agent as ag
import hub
from console import AgentState, Console

AGENT_NAME = os.getenv("AGENT_NAME", "macmini1")
MSG_CAP = int(os.getenv("MSG_CAP", "10"))
TOKEN_CAP = int(os.getenv("TOKEN_CAP", "50000"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "4"))
RESPONSE_DELAY = float(os.getenv("RESPONSE_DELAY", "0"))

_FILE_RE = re.compile(r'`([\w./-]+\.[a-z]{1,4})`')
_DUP_ACTIONS = ("created", "verified", "added", "updated", "wrote", "implemented")
_IMPERATIVES = (
    "build", "create", "delete", "remove", "fix", "implement", "write",
    "add", "make", "update", "refactor", "rewrite", "clean", "rebuild",
)
_OPERATOR_NAMES = ("human-operator", "operator", "graderbot", "human")


def looks_duplicate(reply: str, others: list[dict]) -> bool:
    """True if reply duplicates another agent's recent message — by file+action OR by text similarity."""
    reply_low = reply.strip().lower()
    reply_files = set(_FILE_RE.findall(reply_low))
    reply_has_action = any(a in reply_low for a in _DUP_ACTIONS)

    for m in others:
        other_low = m["content"].strip().lower()

        # File+action match (handles "I created `app.py`" duplicates)
        if reply_files and reply_has_action:
            other_files = set(_FILE_RE.findall(other_low))
            if reply_files & other_files and any(a in other_low for a in _DUP_ACTIONS):
                return True

        # Text similarity match (handles non-file duplicates like "Hi — what should we build?")
        if min(len(reply_low), len(other_low)) >= 15:
            similarity = SequenceMatcher(None, reply_low[:200], other_low[:200]).ratio()
            if similarity > 0.75:
                return True

    return False


def latest_operator_command(messages: list[dict]) -> str | None:
    """Return the most recent message from a human/operator/grader, or None."""
    for m in reversed(messages):
        if m["agent_name"].lower() in _OPERATOR_NAMES:
            return m["content"]
    return None


def has_imperative(text: str | None) -> bool:
    """True if text contains an imperative command verb."""
    if not text:
        return False
    return any(w in text.lower() for w in _IMPERATIVES)


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

    # Fast-forward: skip OLD messages but process FRESH ones (<60s).
    # Without this an agent that crashed mid-LLM would re-bootstrap and skip
    # the very message it was working on.
    try:
        bootstrap = hub.fetch_messages(0)
        if bootstrap:
            now = datetime.datetime.now(datetime.timezone.utc)
            last_old_seq = 0
            fresh_count = 0
            for m in bootstrap:
                try:
                    ts_str = m.get("timestamp", "")
                    ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    age = (now - ts).total_seconds()
                except (ValueError, AttributeError):
                    age = 9999  # treat missing/bad timestamps as old
                if age > 60:
                    last_old_seq = m["seq"]
                else:
                    fresh_count += 1
            state.last_seen = last_old_seq
            log.info("fast-forward to seq %d (%d old skipped, %d fresh kept)",
                     state.last_seen, len(bootstrap) - fresh_count, fresh_count)
    except Exception as e:
        log.warning("bootstrap fetch failed: %s", e)

    while state.running:
      try:
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

        if token_counter.hard_exceeded():
            if not state.token_signoff_sent:
                signoff = f"[{AGENT_NAME} stepping back — token budget at 90%. Handing off to the team.]"
                try:
                    hub.send_message(AGENT_NAME, signoff)
                except Exception as e:
                    log.warning("token sign-off failed: %s", e)
                state.token_signoff_sent = True
                log.warning("token hard limit (%d) — sign-off sent, going silent", token_counter.cap)
            time.sleep(POLL_INTERVAL)
            continue

        soft_limit = token_counter.soft_exceeded()
        if soft_limit and not state.soft_limit_logged:
            log.info("soft token limit (75%%) — nudge/retries disabled")
            state.soft_limit_logged = True

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
        if reply.startswith("[auto-summary]"):
            log.info("← LLM reply (auto-fallback): %s", reply[:120])
        else:
            log.info("← LLM reply: %s", reply[:120] if reply != "PASS" else "PASS")

        # If @mentioned but still PASS: retry once with a stronger nudge, then fallback.
        # Skipped at soft limit to conserve tokens — first-pass already ran.
        if reply == "PASS" and mentioned_me and not soft_limit:
            log.info("@mentioned but LLM said PASS — retrying with stronger nudge")
            retry_prompt = active_prompt + (
                "\n\nFINAL INSTRUCTION: Write your response now. "
                "Do not say PASS. Start writing immediately."
            )
            reply = ag.decide(external, AGENT_NAME, retry_prompt, history, token_counter)
            log.info("← retry reply: %s", reply[:120] if reply != "PASS" else "PASS")

        if reply == "PASS" and mentioned_me:
            # Don't repeat the same canned ack within 60s — go silent instead
            canned = "On it! I'll take care of my part now."
            now_ts = time.time()
            recent_same = (
                state.last_canned_text == canned
                and (now_ts - state.last_canned_at) < 60
            )
            if recent_same:
                log.info("skipping repeat canned ack (sent %ds ago) — PASS instead",
                         int(now_ts - state.last_canned_at))
                # leave reply = "PASS" — will hit the PASS-sleep below
            else:
                reply = canned
                state.last_canned_text = canned
                state.last_canned_at = now_ts
                log.info("fallback reply used (still PASS after retry)")

        # For unaddressed tasks: nudge once to prevent total silence.
        # Skip nudge for short social messages (greetings etc.) — not SWE tasks.
        # Also skipped at soft token limit.
        combined_text = " ".join(m["content"] for m in external)
        looks_like_swe = any(w in combined_text.lower() for w in (
            "build", "create", "write", "implement", "add", "fix", "test",
            "code", "file", "function", "class", "api", "app", "script",
            "bug", "error", "run", "deploy", "docker", "install", "refactor",
        ))
        if reply == "PASS" and not mentioned_me and looks_like_swe and not soft_limit:
            log.info("unaddressed task PASS — retrying with workspace-aware nudge")
            try:
                ws_files = subprocess.run(
                    "find . -type f 2>/dev/null | head -40",
                    shell=True, capture_output=True, text=True,
                    timeout=5, cwd=ag.WORKSPACE_DIR,
                ).stdout[:600] or "(empty workspace)"
            except Exception:
                ws_files = "(workspace check failed)"

            op_cmd = latest_operator_command(external)
            op_section = ""
            if op_cmd and has_imperative(op_cmd):
                op_section = (
                    f"\n\n*** OPERATOR'S DIRECT COMMAND ***\n"
                    f'"{op_cmd[:300]}"\n'
                    f"The operator gave a direct directive above. You MUST act on it "
                    f"using your tools (bash, edit_file). If it says 'delete' — delete. "
                    f"If 'build' — build. 'Work already exists' is NOT a valid reason "
                    f"to PASS when the operator gives a NEW command.\n"
                )

            nudge_prompt = active_prompt + op_section + (
                f"\n\nWORKSPACE FILES RIGHT NOW:\n{ws_files}\n\n"
                f"Pick ONE concrete piece of work and execute it with your tools NOW. "
                f"PASS is FORBIDDEN here."
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

        # Final-check: did anyone — in our existing context OR during our LLM call —
        # already say something near-identical? Compare against both.
        try:
            last_check = hub.fetch_messages(state.last_seen)
            others_during: list = []
            if last_check:
                state.last_seen = last_check[-1]["seq"]
                others_during = [m for m in last_check if m["agent_name"] != AGENT_NAME]
            others_total = external + others_during
            if others_total and looks_duplicate(reply, others_total):
                log.info("ABORT send — duplicate of another agent's recent message")
                time.sleep(POLL_INTERVAL)
                continue
        except Exception:
            pass

        try:
            hub.send_message(AGENT_NAME, reply)
            state.messages_sent += 1
            log.info("SENT (%d/%d): %s", state.messages_sent, state.msg_cap, reply[:120])
            time.sleep(POLL_INTERVAL * 2)  # extra cooldown — let team see our message
            continue
        except hub.RateLimitError as e:
            log.warning("rate-limited: %s", e)
        except Exception as e:
            log.error("send error: %s", e)

        time.sleep(POLL_INTERVAL)
      except KeyboardInterrupt:
        log.info("interrupt — shutting down")
        break
      except Exception as e:
        log.error("loop iteration crashed: %s", e, exc_info=True)
        time.sleep(POLL_INTERVAL)

    log.info("agent stopped.")


if __name__ == "__main__":
    main()
