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
_OPERATOR_ALIASES = frozenset({
    "humanoperator", "operator", "human", "graderbot", "grader",
})
_OPERATOR_SUBSTRINGS = ("grader", "operator", "judge", "examiner", "human")

# "I will..." promise detection — gemini-2.5-flash on complex tasks falls into
# planning-mode and sends prose intent without using tools. We catch those.
_PROMISE_RE = re.compile(
    r"\bi'?ll\b"  # I'll / Ill
    r"|\bi\s+will\b"
    r"|\bi\s+plan\s+to\b"
    r"|\bnext,?\s+i'?ll\b"
    r"|\bi'?m\s+(going\s+to|about\s+to)\b",
    re.IGNORECASE,
)
_DELIVERY_RE = re.compile(
    r"\b(created|wrote|added|edited|updated|removed|fixed|implemented|"
    r"installed|deleted|verified|ran|tested|built)\b",
    re.IGNORECASE,
)
_IMPERATIVE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _IMPERATIVES) + r")\b",
    re.IGNORECASE,
)
_MENTION_ME_RE = re.compile(rf"@{re.escape(AGENT_NAME)}\b")
_COLON_ADDRESS_RE = re.compile(r"^[\w][\w]*-[\w-]+\s*:", re.IGNORECASE)
_COORDINATION_RE = re.compile(
    r"\b(distribute|dela upp|koordinera|coordinate|assign.{0,5}roles?|fördela|"
    r"split.{0,10}roles?|decide.{0,10}roles?)\b",
    re.IGNORECASE,
)
# Explicit peer task-claim phrases — if a peer just claimed work, nudge is suppressed.
_PEER_CLAIM_RE = re.compile(
    r"\b(jag tar mig an|taking:|i'll handle|confirmed,?\s*taking|bekräftat)\b",
    re.IGNORECASE,
)
# Pure social messages — no SWE task implied.
_SOCIAL_ONLY_RE = re.compile(
    r"^(hej[!.]?|hi[!.]?|hello[!.]?|hey[!.]?|tjena[!.]?|hallå[!.]?"
    r"|good\s+(morning|afternoon|evening)[!.]?"
    r"|[\w-]+\s+is\s+(going\s+)?(offline|online)[.!]?.*"
    r"|goodbye[!.]?|bye[!.]?)$",
    re.IGNORECASE | re.DOTALL,
)
# Operator silence commands — force immediate PASS without calling LLM.
_SILENCE_DIRECTIVE_RE = re.compile(
    r"\b(cease|desist|be\s+quiet|stop\s+talking|stop\s+responding|go\s+silent|"
    r"tyst|håll\s+käften|var\s+tyst|silence)\b",
    re.IGNORECASE,
)
_SUCCESS_MARKERS = re.compile(
    r"\b(complete|completed|working|delivered|verified|fully working|"
    r"runs cleanly|full stack|is fully working)\b",
    re.IGNORECASE,
)


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


def is_operator_agent(agent_name: str) -> bool:
    """True for human-operator, grader-bot, graderbot, exam-judge, etc.

    Exact-alias match first (fast path); falls back to substring search
    on the normalized name so unknown live-hub variants (Grader-Tom,
    course-operator, exam-judge) still trigger the operator fast-path.
    """
    key = agent_name.lower().replace("-", "").replace("_", "")
    if key in _OPERATOR_ALIASES:
        return True
    return any(s in key for s in _OPERATOR_SUBSTRINGS)


def latest_operator_command(messages: list[dict]) -> str | None:
    """Return the active operator directive — latest message with an imperative.

    Short follow-ups like "go on" or "continue" do not replace a prior
    "build/create/..." spec; agents keep WORKSPACE GAP and fast-path context.
    """
    for m in reversed(messages):
        if is_operator_agent(m["agent_name"]) and has_imperative(m["content"]):
            return m["content"]
    return None


def latest_imperative_operator_message(messages: list[dict]) -> dict | None:
    """Like latest_operator_command but returns the full message dict (for seq)."""
    for m in reversed(messages):
        if is_operator_agent(m["agent_name"]) and has_imperative(m["content"]):
            return m
    return None


def should_suppress_autosum(reply: str, last_text: str, age_seconds: float) -> bool:
    """True if `reply` is a near-duplicate auto-summary recently sent by this agent.

    Suppression rule: reply starts with `[auto-summary]`, a previous auto-summary
    was sent less than 60s ago, and SequenceMatcher similarity > 0.8.
    """
    if not reply.startswith("[auto-summary]"):
        return False
    if not last_text or age_seconds >= 60:
        return False
    sim = SequenceMatcher(None, reply[:200], last_text[:200]).ratio()
    return sim > 0.8


def has_imperative(text: str | None) -> bool:
    """True if text contains an imperative command verb (whole-word match)."""
    if not text:
        return False
    return _IMPERATIVE_RE.search(text) is not None


def is_empty_promise(reply: str) -> bool:
    """True if reply contains future-tense intent without any past-tense delivery."""
    if not reply or reply == "PASS":
        return False
    if not _PROMISE_RE.search(reply):
        return False
    if _DELIVERY_RE.search(reply):
        return False
    return True


def has_disallowed_promise(reply: str) -> bool:
    """True if the hub message must not be sent — pure or mixed future-tense promises.

    Mixed pattern (the Project Tracker bug): "Created requirements.txt. Next, I will
    create models.py" — is_empty_promise returns False because of "Created", but the
    message still advertises work not done this turn.
    """
    if not reply or reply == "PASS" or reply.startswith("[auto-summary]"):
        return False
    if is_empty_promise(reply):
        return True
    if _DELIVERY_RE.search(reply) and _PROMISE_RE.search(reply):
        return True
    return False


_NON_DELIVERY_RE = re.compile(
    r"\b(facing|blocked|cannot|can't|failed|error|issue|problem|stuck|"
    r"repeated|unable|was not|doesn't work|does not work)\b",
    re.IGNORECASE,
)


def is_non_delivery_reply(reply: str) -> bool:
    """True when the message complains or stalls without showing completed work."""
    if not reply or reply == "PASS" or reply.startswith("[auto-summary]"):
        return False
    if _DELIVERY_RE.search(reply):
        return False
    return _NON_DELIVERY_RE.search(reply) is not None


def hub_reply_blocked(reply: str) -> bool:
    """True if this reply must not be posted to the hub."""
    return has_disallowed_promise(reply) or is_non_delivery_reply(reply)


def split_for_hub(reply: str, max_len: int = 4090) -> list[str]:
    """Split reply into chunks ≤ max_len at code-block or newline boundaries."""
    if len(reply) <= max_len:
        return [reply]
    chunks: list[str] = []
    rest = reply
    while len(rest) > max_len:
        fence = rest.rfind("```", 0, max_len)
        if fence > 50:
            cut = fence + 3
            if cut < len(rest) and rest[cut] == "\n":
                cut += 1
        else:
            cut = rest.rfind("\n", 0, max_len - 10)
            if cut < 0:
                cut = max_len - 10
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip("\n")
        if rest:
            rest = "(cont.) " + rest
    if rest:
        chunks.append(rest)
    return chunks


_FILE_EXT = r"(?:py|js|ts|jsx|tsx|sh|md|sql|json|ya?ml|html|css|toml|ini|cfg)"

_CREATED_FILE_RE = re.compile(
    r"(?:^|[.!:\n])\s*"
    r"\b(skapade|skrev|created|modified|wrote|added|implementerade|implementerat|"
    r"updated|uppdaterade|skapat|skrivit)\b"
    r"\s+(?:filen?\s+|the\s+|den\s+|en\s+|new\s+|ny\s+)?[`']?"
    rf"([\w./-]+\.{_FILE_EXT})[`']?",
    re.IGNORECASE | re.MULTILINE,
)

_PASSIVE_VERB_RE = re.compile(
    r"\b(?:have been|has been|were|was|är|har blivit|har)\s+"
    r"(?:created|skapade|skapats|modified|modifierade|uppdaterade|"
    r"written|skrivna|verified|verifierade)\b",
    re.IGNORECASE,
)

_CLAUSE_FILE_RE = re.compile(
    rf"[`']([\w./-]+\.{_FILE_EXT})[`']|\b([\w./-]+\.{_FILE_EXT})\b",
    re.IGNORECASE,
)


def _iter_claimed_filenames(reply: str) -> list[str]:
    """Filenames the reply claims were created or modified (active or passive voice)."""
    seen: set[str] = set()
    out: list[str] = []

    def add(name: str) -> None:
        if name not in seen:
            seen.add(name)
            out.append(name)

    for m in _CREATED_FILE_RE.finditer(reply):
        add(m.group(2))

    for m in _PASSIVE_VERB_RE.finditer(reply):
        clause = reply[max(0, m.start() - 200):m.start()]
        for fm in _CLAUSE_FILE_RE.finditer(clause):
            add(fm.group(1) or fm.group(2))

    return out


def claims_file_without_code_block(reply: str) -> str | None:
    """If reply claims a created/modified code file but pastes no fenced block, return its name.

    CODE TRANSFER rule: when an agent creates a file the hub message must include
    the full content so peers can sync their local workspace. Returns the first
    claimed filename when the rule is violated, or None when the message is fine.
    """
    if not reply or reply == "PASS" or reply.startswith("[auto-summary]"):
        return None
    if "```" in reply:
        return None
    names = _iter_claimed_filenames(reply)
    return names[0] if names else None


_CODE_FILE_SUFFIXES = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".sh", ".md", ".sql", ".json",
    ".yaml", ".yml", ".html", ".css", ".toml", ".ini", ".cfg",
})


def _filename_mentioned(reply: str, filename: str) -> bool:
    """True if filename appears as its own token (not as substring of another name)."""
    return bool(
        re.search(rf"(?<![\w./-]){re.escape(filename)}(?![\w-])", reply),
    )


def _filename_near_codeblock(reply: str, filename: str) -> bool:
    """True if filename appears just before a fence or inside a fenced block."""
    for m in re.finditer(r"```", reply):
        window = reply[max(0, m.start() - 120):m.start()]
        if filename in window:
            return True
    for block in re.findall(r"```[^\n]*\n(.*?)```", reply, re.DOTALL):
        if filename in block:
            return True
    return False


def written_files_missing_paste(reply: str, written_files: list[str]) -> str | None:
    """First code file written via tools this turn that lacks a fenced paste in reply."""
    if not written_files or not reply or reply == "PASS" or reply.startswith("[auto-summary]"):
        return None
    names = [
        Path(f).name
        for f in written_files
        if Path(f).suffix.lower() in _CODE_FILE_SUFFIXES
    ]
    if not names:
        return None
    if "```" not in reply:
        return names[0]
    for name in names:
        if not _filename_mentioned(reply, name):
            return name
        if not _filename_near_codeblock(reply, name):
            return name
    return None


def claims_nonexistent_file(reply: str, workspace_dir: str) -> str | None:
    """If reply claims a created/modified file but it isn't on disk, return its name.

    Anti-hallucination gate: catches LLM messages that look like clean deliveries
    ('Klar med: Created app.py ...') when the agent actually invoked zero tools
    and the file does not exist in the workspace. Matched by filename (not path)
    via rglob so files nested in subdirs still count.
    """
    if not reply or reply == "PASS" or reply.startswith("[auto-summary]"):
        return None
    names = _iter_claimed_filenames(reply)
    if not names:
        return None
    root = Path(workspace_dir)
    for claimed in names:
        target = Path(claimed).name
        if not root.exists():
            return claimed
        if not any(p.is_file() and p.name == target for p in root.rglob("*")):
            return claimed
    return None


_NAMED_FILE_RE = re.compile(
    r"`([\w./-]+\.(?:py|sh|md|txt|sql|json))`"
    r"|\b([a-z][\w]*\.(?:py|sh|md|txt|sql))\b",
    re.IGNORECASE,
)
_DELEGATION_HINT_RE = re.compile(
    r"\b(please|take|your turn|next file|handle|over to you|go ahead)\b",
    re.IGNORECASE,
)


def extract_required_filenames(operator_text: str | None) -> list[str]:
    """Filenames mentioned in an operator directive (multi-file tasks)."""
    if not operator_text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _NAMED_FILE_RE.finditer(operator_text):
        name = (m.group(1) or m.group(2) or "").strip()
        if name and name not in seen and name != ".gitkeep":
            seen.add(name)
            out.append(name)
    return out


def list_workspace_filenames(workspace_dir: str) -> set[str]:
    root = Path(workspace_dir)
    if not root.exists():
        return set()
    return {
        p.name for p in root.rglob("*")
        if p.is_file() and p.name != ".gitkeep"
    }


def reply_mentions_missing_required(
    reply: str, op_cmd: str | None, workspace_dir: str,
) -> bool:
    """True if reply names a required file that is STILL missing on disk.

    Used to bypass dup-ABORT when a peer's prior claim was a promise that
    didn't deliver — silencing our reply would lose the only actual progress.
    """
    required = extract_required_filenames(op_cmd)
    if not required:
        return False
    present = list_workspace_filenames(workspace_dir)
    missing = {f for f in required if f not in present}
    if not missing:
        return False
    for m in _NAMED_FILE_RE.finditer(reply):
        name = (m.group(1) or m.group(2) or "").strip()
        if name and name in missing:
            return True
    return False


def build_workspace_gap_section(op_cmd: str | None, workspace_dir: str) -> str:
    """Inject missing/existing filenames for large multi-file operator tasks."""
    required = extract_required_filenames(op_cmd)
    if len(required) < 2:
        return ""
    present = list_workspace_filenames(workspace_dir)
    missing = [f for f in required if f not in present]
    present_named = [f for f in required if f in present]
    if not missing and not present_named:
        return ""
    lines: list[str] = []
    if missing:
        lines.append(f"Missing on disk (pick ONE to create this turn): {', '.join(missing)}")
    if present_named:
        lines.append(f"Already on disk: {', '.join(present_named)}")
    return "\n\n*** WORKSPACE GAP ***\n" + "\n".join(lines) + "\n"


def read_project_status_section(workspace_dir: str) -> str:
    """Optional PROJECT_STATUS.md maintained by agents between turns."""
    path = Path(workspace_dir) / "PROJECT_STATUS.md"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:600]
    except OSError:
        return ""
    return f"\n\n*** PROJECT STATUS (disk) ***\n{text}\n"


def was_delegated_to_me(messages: list[dict]) -> bool:
    """True if a peer @mentioned this agent and asked them to take work."""
    for m in messages:
        if m["agent_name"] == AGENT_NAME:
            continue
        content = m["content"]
        if _MENTION_ME_RE.search(content) and _DELEGATION_HINT_RE.search(content):
            return True
    return False


def build_active_prompt(
    system_prompt: str,
    external: list[dict],
    *,
    operator_directive: bool,
    op_cmd: str | None,
    mentioned_me: bool,
) -> str:
    active = system_prompt
    if operator_directive and op_cmd:
        active += build_operator_prompt_section(op_cmd)
        active += build_workspace_gap_section(op_cmd, ag.WORKSPACE_DIR)
        active += read_project_status_section(ag.WORKSPACE_DIR)
    # Warn about active peer claims so the LLM doesn't duplicate claimed work.
    for m in external:
        if m["agent_name"] != AGENT_NAME and _PEER_CLAIM_RE.search(m["content"]):
            snippet = m["content"][:80].replace("\n", " ")
            active += (
                f"\n\n⚠️ PEER CLAIM ACTIVE: {m['agent_name']} just claimed \"{snippet}\"."
                f" PASS unless you have a clearly different, non-overlapping deliverable."
            )
            break
    if mentioned_me:
        if operator_directive or was_delegated_to_me(external):
            active += (
                f"\n\nDELEGATION OVERRIDE: @{AGENT_NAME} was mentioned during an active "
                f"operator task. Use bash or edit_file THIS turn — deliver ONE file or "
                f"run ONE verification with quoted output. PASS and 'I will...' are FORBIDDEN."
            )
        else:
            active += (
                f"\n\nOVERRIDE: @{AGENT_NAME} was directly mentioned. "
                f"You MUST reply with actual content. PASS is not allowed."
            )
    return active


def apply_send_quality_retries(
    reply: str,
    external: list[dict],
    active_prompt: str,
    history: list,
    token_counter: ag.TokenCounter,
    soft_limit: bool,
    log,
    max_retries: int = 2,
) -> str:
    """Re-prompt until reply is deliverable (no promises / complaint / missing paste / hallucinated)."""
    written_this_turn = ag.get_last_turn_written_files()
    attempts = 0
    while not soft_limit and reply != "PASS" and attempts < max_retries:
        hallucinated = claims_nonexistent_file(reply, ag.WORKSPACE_DIR)
        missing_paste = claims_file_without_code_block(reply)
        missing_written = written_files_missing_paste(reply, written_this_turn)
        bad_file = hallucinated or missing_paste or missing_written
        if has_disallowed_promise(reply):
            log.info(
                "disallowed promise in reply — retry %d/%d",
                attempts + 1,
                max_retries,
            )
            extra = (
                "Your reply contained a PROMISE ('I will...' / 'Next, I'll...'). "
                "That cannot be sent."
            )
        elif is_non_delivery_reply(reply):
            log.info(
                "non-delivery reply — retry %d/%d",
                attempts + 1,
                max_retries,
            )
            extra = (
                "Your reply described a problem but showed no completed work. "
                "That cannot be sent."
            )
        elif hallucinated:
            log.info(
                "claim of `%s` but file not on disk — retry %d/%d",
                hallucinated,
                attempts + 1,
                max_retries,
            )
            extra = (
                f"Your reply claims you created or modified `{hallucinated}`, but that "
                f"file does NOT exist in the workspace. You may be hallucinating delivery. "
                f"Use bash (heredoc `cat > {hallucinated} <<'EOF'`) NOW to ACTUALLY "
                f"create the file, then resend with the real content."
            )
        elif missing_paste:
            log.info(
                "missing code paste for `%s` — retry %d/%d",
                missing_paste,
                attempts + 1,
                max_retries,
            )
            extra = (
                f"Your reply claims you created or modified `{missing_paste}` but did not "
                f"paste the file. CODE TRANSFER rule: include the full file content inside "
                f"a fenced ```language ... ``` block so peers can sync their workspace."
            )
        elif missing_written:
            log.info(
                "tool wrote `%s` but no code block in reply — retry %d/%d",
                missing_written,
                attempts + 1,
                max_retries,
            )
            extra = (
                f"You wrote `{missing_written}` via tools this turn but did not paste its "
                f"content in your message. CODE TRANSFER: every file you create must appear "
                f"in a fenced ```language ... ``` block (one block per file) so peers can sync."
            )
        else:
            break
        nudge = active_prompt + (
            f"\n\n{extra} Use bash (`cat {bad_file or 'file'}`) or edit_file NOW, "
            f"then resend WITH the full file pasted in a fenced code block. "
            f"If you cannot deliver this turn, reply PASS."
        )
        reply = ag.decide(external, AGENT_NAME, nudge, history, token_counter)
        log.info(
            "← send-quality retry reply: %s",
            reply[:120] if reply != "PASS" else "PASS",
        )
        attempts += 1
    return reply


def operator_directive_pending(messages: list[dict]) -> bool:
    """True when an operator/grader imperative directive is still active."""
    return latest_operator_command(messages) is not None


def build_operator_prompt_section(op_cmd: str) -> str:
    """Injected into the system prompt when an operator directive is active."""
    return (
        f"\n\n*** OPERATOR'S DIRECT COMMAND ***\n"
        f'"{op_cmd[:300]}"\n'
        f"The operator gave a direct directive above. You MUST act on it "
        f"using your tools (bash, edit_file). If it says 'delete' or 'clean' — "
        f"remove old workspace files first (e.g. find . -type f ! -name .gitkeep -delete), "
        f"then confirm with find. If 'build' — build. 'Work already exists' is NOT a valid "
        f"reason to PASS when the operator gives a NEW command.\n"
    )


def task_completed_heuristic(
    messages: list[dict],
    op_cmd: str | None = None,
    workspace_dir: str | None = None,
) -> bool:
    """True when peers reported success AND all operator-spec files exist on disk.

    Chat-only heuristic when op_cmd / workspace_dir are not provided.
    When provided: also requires that every filename in the operator's
    spec is actually present in the workspace. Prevents premature PASS
    on multi-file tasks where peers said "X works" but other required
    files (e.g. README.md) are still missing.
    """
    imp_op = latest_imperative_operator_message(messages)
    latest_op_seq = imp_op.get("seq", 0) if imp_op else -1
    latest_op_imperative = imp_op is not None

    last_success_seq = -1
    for m in messages:
        name = m["agent_name"].lower()
        if is_operator_agent(m["agent_name"]) or name == AGENT_NAME.lower():
            continue
        if _SUCCESS_MARKERS.search(m["content"]):
            last_success_seq = max(last_success_seq, m.get("seq", 0))

    if last_success_seq < 0:
        return False
    if latest_op_imperative and latest_op_seq > last_success_seq:
        return False

    # Workspace-aware check (only when caller provides both args).
    # If the operator's spec named multiple files and some are still
    # missing on disk, the task is NOT complete regardless of chat claims.
    if op_cmd and workspace_dir:
        required = extract_required_filenames(op_cmd)
        if len(required) >= 2:
            present = list_workspace_filenames(workspace_dir)
            if any(f not in present for f in required):
                return False
    return True


def _merge_rechecked_messages(
    state: AgentState,
    external: list[dict],
    log,
) -> list[dict]:
    """Fetch messages since last_seen and append new peer messages to external."""
    try:
        rechecked = hub.fetch_messages(state.last_seen)
    except Exception:
        return external
    if not rechecked:
        return external
    state.last_seen = rechecked[-1]["seq"]
    new_from_others = [m for m in rechecked if m["agent_name"] != AGENT_NAME]
    if new_from_others:
        log.info("recheck: %d new msg(s) from others — adding to context", len(new_from_others))
        for m in new_from_others:
            log.info("  [%s]: %s", m["agent_name"], m["content"][:120])
        external = external + new_from_others
    return external


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
            if len(history) > 12:
                history[:] = history[-12:]
                log.info("history trimmed to %d entries (soft limit)", len(history))

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
        mentioned_me = any(_MENTION_ME_RE.search(m["content"]) for m in external)
        mentioned_other = (
            not mentioned_me and
            any(
                (
                    m["content"].strip().startswith("@") or
                    _COLON_ADDRESS_RE.match(m["content"].strip())
                ) and f"@{AGENT_NAME}" not in m["content"]
                for m in external
            )
        )

        log.info("routing  mentioned_me=%s  mentioned_other=%s", mentioned_me, mentioned_other)

        if mentioned_other:
            log.info("SKIP — message is primarily addressed to another agent")
            time.sleep(POLL_INTERVAL)
            continue

        op_cmd = latest_operator_command(external)
        operator_directive = operator_directive_pending(external)

        # Operator/grader directives skip stagger delay — UNLESS they ask agents to
        # coordinate/distribute roles first (racing causes duplicate files).
        _is_coordination = operator_directive and _COORDINATION_RE.search(op_cmd or "")
        if operator_directive and not _is_coordination:
            log.info("operator directive — skipping response delay")
            external = _merge_rechecked_messages(state, external, log)
            op_cmd = latest_operator_command(external)
        elif not mentioned_me and RESPONSE_DELAY > 0:
            jitter = random.uniform(0, RESPONSE_DELAY * 0.3)
            wait = RESPONSE_DELAY + jitter
            log.info("unaddressed task — waiting %.1fs before responding", wait)
            time.sleep(wait)
            external = _merge_rechecked_messages(state, external, log)
            op_cmd = latest_operator_command(external)
            operator_directive = operator_directive_pending(external)
            if operator_directive:
                log.info("operator directive detected after recheck — applying priority")

        # Operator silence commands ("cease and desist", "be quiet", etc.) — PASS immediately.
        if op_cmd and _SILENCE_DIRECTIVE_RE.search(op_cmd):
            log.info("PASS — silence directive from operator")
            time.sleep(POLL_INTERVAL)
            continue

        delegated = was_delegated_to_me(external)
        active_prompt = build_active_prompt(
            system_prompt,
            external,
            operator_directive=operator_directive,
            op_cmd=op_cmd,
            mentioned_me=mentioned_me,
        )
        if mentioned_me:
            log.info("@mentioned — PASS override active")
        if delegated and operator_directive:
            log.info("delegation override — tools required this turn")

        # Tell the security guard which files are off-limits for rm/find -delete
        # this turn. Cleared when no operator imperative is active so we don't
        # block routine cleanup of unrelated files.
        ag.set_protected_files(extract_required_filenames(op_cmd) if op_cmd else [])

        # Skip LLM entirely when all new messages are purely social and there is
        # no operator directive. Prevents the agent from hallucinating tasks from greetings.
        if not operator_directive and not mentioned_me:
            all_social = all(
                _SOCIAL_ONLY_RE.match(m["content"].strip())
                for m in external
            )
            if all_social:
                log.info("PASS — all-social messages, skipping LLM call")
                time.sleep(POLL_INTERVAL)
                continue

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
            if task_completed_heuristic(external, op_cmd, ag.WORKSPACE_DIR):
                log.info("task completed — skipping canned ack, staying PASS")
            elif operator_directive and delegated:
                log.info("@mentioned + delegation — tool nudge instead of canned ack")
                tool_nudge = active_prompt + (
                    "\n\nYou were assigned work. Use bash or edit_file NOW. "
                    "Do not say PASS. Create or verify ONE file from WORKSPACE GAP."
                )
                reply = ag.decide(
                    external, AGENT_NAME, tool_nudge, history, token_counter,
                )
                log.info(
                    "← delegation-tool reply: %s",
                    reply[:120] if reply != "PASS" else "PASS",
                )
            else:
                canned = "On it! I'll take care of my part now."
                now_ts = time.time()
                recent_same = (
                    state.last_canned_text == canned
                    and (now_ts - state.last_canned_at) < 60
                )
                if recent_same:
                    log.info("skipping repeat canned ack (sent %ds ago) — PASS instead",
                             int(now_ts - state.last_canned_at))
                else:
                    reply = canned
                    state.last_canned_text = canned
                    state.last_canned_at = now_ts
                    log.info("fallback reply used (still PASS after retry)")

        reply = apply_send_quality_retries(
            reply, external, active_prompt, history, token_counter, soft_limit, log,
        )

        # For unaddressed tasks: nudge once to prevent total silence when the operator
        # gave a directive that is still active. Without an operator directive the LLM's
        # PASS is authoritative — don't invent work from peer discussions.
        if reply == "PASS" and not mentioned_me and operator_directive and not soft_limit:
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
            op_section = build_operator_prompt_section(op_cmd) if op_cmd else ""
            gap_section = (
                build_workspace_gap_section(op_cmd, ag.WORKSPACE_DIR)
                if op_cmd else ""
            )

            nudge_prompt = active_prompt + op_section + gap_section + (
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

        if hub_reply_blocked(reply):
            reason = "promises" if has_disallowed_promise(reply) else "non-delivery"
            log.info("ABORT send — reply blocked (%s)", reason)
            time.sleep(POLL_INTERVAL)
            continue

        # Split long messages instead of truncating (hub cap is 4096 server-side)
        chunks = split_for_hub(reply)

        # Suppress repeated auto-summary fallbacks from THIS agent within 60s.
        # Haiku hits MAX_ROUNDS frequently → identical-shape `[auto-summary]`
        # messages would otherwise spam the hub on consecutive cycles.
        if reply.startswith("[auto-summary]"):
            now_ts = time.time()
            age = now_ts - state.last_autosum_at
            if should_suppress_autosum(reply, state.last_autosum_text, age):
                log.info("skipping repeat auto-summary (%ds ago) — PASS instead",
                         int(age))
                time.sleep(POLL_INTERVAL)
                continue
            state.last_autosum_text = reply
            state.last_autosum_at = now_ts

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
                # Bypass: if our reply names a REQUIRED file that is STILL missing
                # on disk, the prior "claim" was a promise (not delivery). Send so
                # the actual delivery isn't silenced by a duplicate filter.
                if reply_mentions_missing_required(reply, op_cmd, ag.WORKSPACE_DIR):
                    log.info("dup detected but reply fills a missing required file — sending anyway")
                else:
                    log.info("ABORT send — duplicate of another agent's recent message")
                    time.sleep(POLL_INTERVAL)
                    continue
        except Exception:
            pass

        try:
            for i, chunk in enumerate(chunks):
                if state.messages_sent >= state.msg_cap:
                    log.warning("msg_cap reached mid-split — dropping %d chunk(s)", len(chunks) - i)
                    break
                hub.send_message(AGENT_NAME, chunk)
                state.messages_sent += 1
                log.info(
                    "SENT (%d/%d)%s: %s",
                    state.messages_sent, state.msg_cap,
                    f" chunk {i+1}/{len(chunks)}" if len(chunks) > 1 else "",
                    chunk[:120],
                )
                if i < len(chunks) - 1:
                    time.sleep(POLL_INTERVAL)
            time.sleep(POLL_INTERVAL * 2)  # cooldown after full send
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
