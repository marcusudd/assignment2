"""
Part 3 — Multi-Agent Group Chat
Connects to the Hell's Agents Hub and collaborates on a shared software project.
"""

import datetime
import json
import os
import re
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path

import random

from dotenv import load_dotenv

load_dotenv()

import log as _log
import agent as ag
import hub
import trace as tr
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
    "raise", "confirm", "acknowledge", "respond", "introduce", "show", "state",
    "skapa", "bygg", "skriv", "lägg", "fixa", "radera", "uppdatera", "gör",
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
    r"installed|deleted|verified|ran|tested|built|"
    r"reviewed|noted|flagged|approved|rejected|confirmed|"
    r"skapade|skapat|skrev|lade|byggde|byggt|gjorde|gjort|"
    r"implementerade|raderade|raderat|uppdaterade|fixade|"
    r"fyllt|fyllde|installerade|verifierade|körde|testade|"
    r"granskade|granskat|noterade|noterat|flaggade|flaggat|godkände|godkänt)\b"
    r"|^(?:Review|Granskning|Critic note|Critic):",
    re.IGNORECASE | re.MULTILINE,
)
_IMPERATIVE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _IMPERATIVES) + r")\b",
    re.IGNORECASE,
)
_MENTION_ME_RE = re.compile(rf"\b{re.escape(AGENT_NAME)}\b", re.IGNORECASE)
_COLON_ADDRESS_RE = re.compile(r"^[\w][\w]*-[\w-]+\s*:", re.IGNORECASE)
_BROADCAST_ADDRESS_RE = re.compile(
    r"^@(everyone|all|agents|alla(\s+agenter)?)\b",
    re.IGNORECASE,
)
# Broadcast operator commands ("all agents, build X" / "@everyone build X") imply
# multiple agents will race — keep the response delay so peers can claim roles first.
_BROADCAST_OPERATOR_RE = re.compile(
    r"^(@(everyone|all|agents|alla(\s+agenter)?)\b|all\s+agents\b|alla\s+agenter\b)",
    re.IGNORECASE,
)
_COORDINATION_RE = re.compile(
    r"\b(distribute|dela upp|koordinera|coordinate|assign.{0,5}roles?|fördela|"
    r"split.{0,10}roles?|decide.{0,10}roles?|together|tillsammans|"
    r"protocol|stipulate|roster|communication)\b",
    re.IGNORECASE,
)
_MANAGER_RACE_RE = re.compile(
    r"\b(first\s+one\s+that\s+answers|manager\s+in\s+this\s+session|"
    r"DO NOT START WORKING|NOT\s+answer.*default|default\s+operation)\b",
    re.IGNORECASE,
)
# Operator also asked agents to self-organize and build (parallel to manager election).
_SELF_ORGANIZE_BUILD_RE = re.compile(
    r"\b(?:self[- ]?organize|act\s+autonomously|collaboratively\s+build|"
    r"no\s+predefined\s+roles|no\s+leaders?,?\s*managers?)\b",
    re.IGNORECASE,
)
# Role-distribution patterns — operator describes a multi-role workflow where
# each agent plays one role. Detection here softens the DELEGATION OVERRIDE
# (no forced immediate file write) so the LLM can claim a role first.
_ROLE_DISTRIBUTION_RE = re.compile(
    r"\b(?:agent\s*\d|act\s+as\s+a?\s*\d+[-\s]?agent|play.{0,30}roles?|"
    r"the\s+(?:product\s+planner|lead\s+developer|bug\s+tester|"
    r"final\s+refiner|reviewer|architect|qa|tester)|"
    r"workflow.{0,30}(?:agents?|roles?)|sequential(?:ly)?.{0,30}roles?)\b",
    re.IGNORECASE,
)
# Explicit peer task-claim phrases — if a peer just claimed work, nudge is suppressed.
_PEER_CLAIM_RE = re.compile(
    r"\b(jag tar mig an|jag tar|taking:|i'?ll handle|i will take|"
    r"confirmed,?\s*taking|bekräftat)\b",
    re.IGNORECASE,
)
# Capture the task/role text after a claim or delivery header, for SESSION MEMORY.
_CLAIM_CAPTURE_RE = re.compile(
    r"\b(?:jag tar mig an|taking|confirmed,?\s*taking|bekräftat,?\s*jag tar)"
    r"\s*:?\s*`?([^\n`]{1,80})",
    re.IGNORECASE,
)
_DELIVERY_CAPTURE_RE = re.compile(
    r"\b(?:klar med|done with|färdig med|completed)\s*:\s*`?([^\n`]{1,80})",
    re.IGNORECASE,
)
# Pure social messages — no SWE task implied.
_SOCIAL_ONLY_RE = re.compile(
    r"^("
    # Greetings
    r"hej[!.]?|hi[!.]?|hello[!.]?|hey[!.]?|tjena[!.]?|hallå[!.]?"
    r"|good\s+(morning|afternoon|evening)[!.]?"
    # Online/offline announcements
    r"|[\w-]+\s+is\s+(going\s+)?(offline|online)[.!]?.*"
    # Farewells
    r"|goodbye[!.]?|bye[!.]?|hej\s+då.*|adjö.*|vi\s+ses.*|farewell.*"
    r"|[\w-]+\s+säg\s+hej\s+då.*|[\w-]+\s+say\s+goodbye.*"
    # Vague readiness / "shall we start" questions (no concrete task)
    r"|okej[.!]?|ok[.!]?|sounds?\s+good[.!?]?|alright[.!?]?"
    r"|ska\s+vi\s+(sätta\s+igång|börja|köra)[?!.]?.*"
    r"|tycker\s+ni\s+(att\s+vi\s+ska\s+)?.*"
    r"|är\s+ni\s+redo[?!.]?.*|är\s+alla\s+redo[?!.]?.*"
    r"|vilka\s+agenter\s+är\s+beredda.*|who\s+is\s+ready[?!.]?.*"
    r"|let[''s]*\s+get\s+started[.!?]?|let[''s]*\s+begin[.!?]?"
    r"|anyone\s+(here|online|ready)[?!.]?.*"
    # Vague/non-task single words — no operator directive implied
    r"|testing[!.?]?|test[!.?]?|pokes?[!.?]?|ping[!.?]?"
    r"|<[^>]{1,60}>"
    r"|[\w-]+\s+är\s+(online|här|aktiv|redo)[.!?]?"
    r"|[\w-]+\s+is\s+(here|active|ready)[.!?]?"
    r")$",
    re.IGNORECASE | re.DOTALL,
)
# Human STOP/RESUME — matched via is_human_stop_directive / is_human_resume_directive
# (many phrasings; only messages from is_operator_agent() count).
_MANAGER_NAME_LINE_RE = re.compile(
    r"^MANAGER:\s*([\w][\w-]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TAKING_MANAGER_ROLE_RE = re.compile(
    r"\b(?:I am )?taking the manager role\b",
    re.IGNORECASE,
)
_STEP_UP_MANAGER_RE = re.compile(
    r"\b(?:I'll|I will)\s+step up as manager\b|"
    r"\bstep(?:ping)? up as manager\b|"
    r"\bI am the manager for this session\b",
    re.IGNORECASE,
)
_MANAGER_ME_PROTOCOL_RE = re.compile(r"\bManager\s*\(\s*me\s*\)", re.IGNORECASE)
_PEER_MANAGER_CLAIM_RE = re.compile(
    r"\bclaiming\s+(?:the\s+)?manager\b",
    re.IGNORECASE,
)
_CLAIM_MANAGER_ROLE_RE = re.compile(
    r"\b(?:I\s+)?claim(?:ing)?\s+(?:the\s+)?(?:role\s+of\s+|role\s+as\s+)?manager\b|"
    r"\bclaim(?:ing)?\s+the\s+manager(?:/coordinator)?(?:\s+role)?\b|"
    r"\bclaim(?:ing)?\s+(?:to\s+be\s+)?(?:the\s+)?manager\s+for\s+this\s+session\b",
    re.IGNORECASE,
)
_DESIGNATED_PEER_MANAGER_RE = re.compile(
    r"(?:listen\s+to|follow)\s+([\w][\w-]*)\s+(?:that\s+is|as)\s+the\s+manager\b|"
    r"\b([\w][\w-]*-agent)\s+is\s+the\s+manager\b",
    re.IGNORECASE,
)
_MANAGER_GO_WAIT_RE = re.compile(
    r"DO NOT begin.*(?:development|working).*until.*\bGO\b|"
    r"DO NOT START WORKING UNTIL THE MANAGER SAYS SO|"
    r"No agent starts (?:coding|working).*until I assign|"
    r"until I assign tasks|assign tasks explicitly|"
    r"assign tasks after",
    re.IGNORECASE,
)
_MANAGER_GO_RELEASE_RE = re.compile(
    r"(?:^|\n)\s*GO\s*(?:\n|$)|\bwe are GO\b|"
    r"development (?:work )?begins|begin (?:development|coding)\b|"
    r"@\w[\w-]*:\s*TASK-\d+:",
    re.IGNORECASE,
)
# Broader release phrases — only matched from peer_manager or operator (see manager_work_released).
_MANAGER_TASK_ASSIGNMENT_RE = re.compile(
    r"go\s+ahead(?:\s+and)?\b|"
    r"proceed\s+(?:with|to)\s+(?:implementation|coding|building|work)\b|"
    r"start\s+(?:coding|building|implementing)\b|"
    r"you\s+may\s+(?:now\s+)?(?:begin|start|proceed)\b|"
    r"(?:proceed|start|begin)\s+your\s+(?:claimed|assigned)\s+tasks?\b|"
    r"@?\w[\w-]*(?:-agent)?\s*:\s+(?:implement|build|create|handle|write)\b|"
    r"@?\w[\w-]*-agent\b[^.\n]{0,120}\b(?:assigned|you(?:'re| are) assigned)\b",
    re.IGNORECASE,
)
_ROSTER_PHASE_RE = re.compile(
    r"All agents post your ROSTER|post your ROSTER entry(?:\s+once)?|"
    r"Please post your \[ROSTER\]|post your \[ROSTER\] line|"
    r"Request roster|roster/capabilities lines from all agents|"
    r"Waiting for more roster lines|"
    r"roster registration|One ROSTER message per agent|ROSTER:\s*\[|"
    r"respond with their roster|request all agents to respond with their roster|"
    r"\[ROSTER\]\s+\w|Roster collection concluded|close roster|roster is closed",
    re.IGNORECASE,
)
_ROSTER_BROADCAST_ADDR_RE = re.compile(
    r"@?all\s+agents?|@all\b|@everyone|@agents?\b",
    re.IGNORECASE,
)
_MANAGER_ROSTER_ROLL_CALL_RE = re.compile(
    r"All agents post your ROSTER|post your ROSTER entry(?:\s+once)?|"
    r"Please post your \[ROSTER\]|post your \[ROSTER\] line|"
    r"Request roster|roster/capabilities lines from all agents|"
    r"Waiting for more roster lines|"
    r"request all agents to respond with their roster|"
    r"create a roaster with every participant",
    re.IGNORECASE,
)
_ROSTER_CLOSED_RE = re.compile(
    r"Roster collection concluded|roster is closed|close roster",
    re.IGNORECASE,
)
_MANAGER_OPEN_CLAIMS_RE = re.compile(
    r"Others may claim remaining tasks|may claim remaining|open for claims",
    re.IGNORECASE,
)
_SELF_CLAIM_POST_RE = re.compile(r"^\s*\[CLAIM\]", re.IGNORECASE)
_UNSOLICITED_ROSTER_RE = re.compile(r"^\s*(?:ROSTER:|\[ROSTER\])", re.IGNORECASE)
_SELF_ROSTER_POST_RE = re.compile(r"^\s*(?:\[ROSTER\]|ROSTER:)", re.IGNORECASE)
_GRADER_BOILERPLATE_RE = re.compile(r"IMPORTANT:\s*NEVER ACKNOWLEDGE", re.IGNORECASE)
_WORK_OPERATOR_BODY_RE = re.compile(
    r"React calculator|collaboratively build|build a React|Investment Research",
    re.IGNORECASE,
)
_ROUTING_CTX_WINDOW = 80
_BLOCKED_SELF_MANAGER_RE = re.compile(
    r"\b(I will act as the manager|your manager for this session|"
    r"session_manager\.py)\b",
    re.IGNORECASE,
)
# Detect "Name, ..." / "Name are you here?" addressing patterns at message start.
# Used to route messages addressed to a SPECIFIC other agent by name (e.g. "emil, ...")
# rather than to us. Conservative: only match when followed by punctuation or an
# interrogative/imperative verb so we don't capture random capitalized first words.
_NAME_ADDRESS_AT_START_RE = re.compile(
    r"^(?P<name>[\w][\w-]*?)"
    r"\s*(?:[,?!:]|\s+(?:are|is|can|will|would|could|please|kan|ska|här|here))\b",
    re.IGNORECASE,
)
_MY_NAME_PARTS = frozenset(
    p for p in AGENT_NAME.lower().split("-") if p and p != "agent"
)
_HUMAN_REFS = ("human", "operator", "the human", "the operator")


def addressed_to_other_by_name(content: str) -> bool:
    """True if message opens 'Name, ...' / 'Name are you ...' for a non-self name.

    Conservative: only the exact full agent name (or @<name>) counts as us. Any
    other first-word name pattern is treated as addressed to someone else.
    """
    stripped = content.strip()
    m = _NAME_ADDRESS_AT_START_RE.match(stripped)
    if not m:
        return False
    name = m.group("name").lower()
    if name == AGENT_NAME.lower():
        return False  # full match — addressed to us
    if name in _MY_NAME_PARTS:
        # "Marcus Human" / "Marcus operator" → addresses the human, not us
        rest = stripped[len(m.group(0)):].lstrip().lower()
        if rest.startswith(_HUMAN_REFS):
            return True
        # Plain "Marcus, ..." on a live hub with many marcuses is ambiguous;
        # be conservative — only the FULL agent name should trigger response.
        return True
    return True  # any other first-word name → addressed elsewhere
_SUCCESS_MARKERS = re.compile(
    r"\b(complete|completed|working|delivered|verified|fully working|"
    r"runs cleanly|full stack|is fully working)\b",
    re.IGNORECASE,
)


def should_suppress_autosum(reply: str, last_text: str, age_seconds: float) -> bool:
    """Suppress near-duplicate [auto-summary] fallbacks within 60s."""
    if not reply.startswith("[auto-summary]"):
        return False
    if not last_text or age_seconds >= 60:
        return False
    return SequenceMatcher(None, reply[:200], last_text[:200]).ratio() > 0.8


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


def is_human_stop_directive(content: str) -> bool:
    """True when a human operator tells agents to stop talking/posting."""
    if not content or not content.strip():
        return False
    c = content
    # Broadcast: "all agents stop", "everyone stop talking", …
    if re.search(
        r"(?:\ball\b|\bevery(?:one|body)\b|\bagents?\b).{0,50}\bstop\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\bstop\b.{0,40}\b(?:talking|posting|responding|chatting|messages?|replying|work|now)\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:stop|cease|halt)\s+(?:talking|posting|responding|all\s+activity|work|now|immediately)\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:be\s+quiet|go\s+silent|silence|desist|shut\s+up|quiet\s+down)\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:no\s+more\s+(?:messages|posts|replies)|do\s+not\s+(?:post|reply|respond))\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:sluta\s+(?:skriva|svara|prata)|stoppa?\s+nu|var\s+tyst|håll\s+käften)\b",
        c,
        re.IGNORECASE,
    ):
        return True
    return False


def is_human_resume_directive(content: str) -> bool:
    """True when a human operator releases agents to talk/work again."""
    if not content or not content.strip():
        return False
    c = content
    if re.search(
        r"\b(?:continue|resume|proceed)\s+(?:again|work|posting|talking|now)\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:agents?|all|everyone|everybody)\b.{0,40}\b(?:continue|resume|proceed)\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:continue|resume|proceed)\b.{0,40}\b(?:agents?|all|everyone|everybody)\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:start\s+again|go\s+ahead|carry\s+on|ok\s+to\s+(?:continue|resume|post))\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:you\s+may|can)\s+(?:now\s+)?(?:continue|resume|proceed|post|talk)\b",
        c,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"\bfortsätt\s+(?:igen|arbeta)\b", c, re.IGNORECASE):
        return True
    return False


def apply_stop_resume_from_messages(messages: list[dict]) -> bool:
    """Replay human STOP/RESUME in order; return final silence state."""
    silence = False
    for m in messages:
        if not is_operator_agent(m["agent_name"]):
            continue
        if is_human_stop_directive(m["content"]):
            silence = True
        elif is_human_resume_directive(m["content"]):
            silence = False
    return silence


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


def routing_context(
    state: "AgentState",
    external: list[dict],
    *,
    window: int = _ROUTING_CTX_WINDOW,
) -> list[dict]:
    """Recent hub history merged with the current poll batch (deduped by seq)."""
    since = max(0, state.last_seen - window)
    try:
        recent = hub.fetch_messages(since)
    except Exception:
        recent = []
    by_seq: dict[int, dict] = {}
    for m in recent + external:
        seq = m.get("seq")
        if seq is not None:
            by_seq[int(seq)] = m
    return sorted(by_seq.values(), key=lambda x: x.get("seq", 0))


def _operator_message_score(content: str) -> int:
    score = 0
    if _WORK_OPERATOR_BODY_RE.search(content):
        score += 10
    if _SELF_ORGANIZE_BUILD_RE.search(content):
        score += 8
    if _GRADER_BOILERPLATE_RE.search(content) and not _WORK_OPERATOR_BODY_RE.search(content):
        score -= 5
    if _MANAGER_RACE_RE.search(content) and not _WORK_OPERATOR_BODY_RE.search(content):
        score -= 2
    return score


def best_work_operator_message(messages: list[dict]) -> dict | None:
    """Operator imperative with the strongest work signal (React build > Grader boilerplate)."""
    best_msg: dict | None = None
    best_score = -999
    for m in reversed(messages):
        if not is_operator_agent(m["agent_name"]):
            continue
        content = m["content"]
        if not has_imperative(content):
            continue
        score = _operator_message_score(content)
        if score > best_score:
            best_score = score
            best_msg = m
    return best_msg


def best_work_operator_command(messages: list[dict]) -> str | None:
    msg = best_work_operator_message(messages)
    return msg["content"] if msg else None


def roster_collection_closed(messages: list[dict]) -> bool:
    for m in reversed(messages[-30:]):
        if _ROSTER_CLOSED_RE.search(m["content"]):
            return True
    return False


def _is_roster_request(content: str) -> bool:
    """True when a message is asking all agents to post a roster/capabilities line."""
    if _MANAGER_ROSTER_ROLL_CALL_RE.search(content):
        return True
    if _ROSTER_BROADCAST_ADDR_RE.search(content) and re.search(
        r"\broster\b|\bcapabilities?\b|\[ROSTER\]|post your",
        content,
        re.IGNORECASE,
    ):
        return True
    return False


def roster_roll_call_requested(
    messages: list[dict],
    peer_manager: str | None,
) -> bool:
    """True when manager/operator asks all agents to post a roster line."""
    if roster_collection_closed(messages):
        return False
    for m in reversed(messages[-30:]):
        content = m["content"]
        agent = m["agent_name"]
        if peer_manager and agent == peer_manager:
            if _is_roster_request(content):
                return True
        if is_operator_agent(agent) and _is_roster_request(content):
            return True
    return False


def we_posted_roster(messages: list[dict], self_name: str) -> bool:
    self_low = self_name.lower()
    for m in messages:
        if m["agent_name"].lower() != self_low:
            continue
        if _SELF_ROSTER_POST_RE.match(m["content"].strip()):
            return True
    return False


def roster_response_due(
    messages: list[dict],
    peer_manager: str | None,
    self_name: str,
    *,
    roster_posted: bool,
) -> bool:
    if roster_posted or we_posted_roster(messages, self_name):
        return False
    if roster_collection_closed(messages):
        return False
    return roster_roll_call_requested(messages, peer_manager)


def we_posted_open_claim(messages: list[dict], self_name: str) -> bool:
    self_low = self_name.lower()
    for m in messages:
        if m["agent_name"].lower() != self_low:
            continue
        if not _SELF_CLAIM_POST_RE.match(m["content"].strip()):
            continue
        if _CLAIM_MANAGER_ROLE_RE.search(m["content"]):
            continue
        return True
    return False


def manager_open_claim_due(
    messages: list[dict],
    peer_manager: str | None,
    self_name: str,
    *,
    claim_posted: bool,
) -> bool:
    if claim_posted or we_posted_open_claim(messages, self_name):
        return False
    if not peer_manager or peer_manager.lower() == self_name.lower():
        return False
    if not roster_collection_closed(messages):
        return False
    for m in reversed(messages[-25:]):
        if m["agent_name"] != peer_manager:
            continue
        if _MANAGER_OPEN_CLAIMS_RE.search(m["content"]):
            return True
    return False


def build_open_task_claim_line(
    messages: list[dict],
    peer_manager: str | None,
    self_name: str,
) -> str:
    """Pick an unassigned calculator slice from the manager's task breakdown."""
    mgr_content = ""
    for m in reversed(messages[-30:]):
        if peer_manager and m["agent_name"] == peer_manager:
            if _MANAGER_OPEN_CLAIMS_RE.search(m["content"]) or _ROSTER_CLOSED_RE.search(
                m["content"],
            ):
                mgr_content = m["content"]
                break
    if not mgr_content:
        return "[CLAIM] Taking: calculator operations logic (add/sub/mul/div, decimals)"[
            :200
        ]

    mgr_low = mgr_content.lower()

    picks: list[tuple[str, bool]] = [
        (
            "calculator operations logic (add/sub/mul/div, decimals)",
            "operations logic" in mgr_low,
        ),
        (
            "error handling (invalid inputs, divide-by-zero)",
            "error handling" in mgr_low,
        ),
        ("clear/reset functionality", "clear/reset" in mgr_low),
        (
            "testing and component integration",
            "testing" in mgr_low and "component integration" in mgr_low,
        ),
    ]
    for label, ok in picks:
        if ok:
            return f"[CLAIM] Taking: {label}"[:200]
    return "[CLAIM] Taking: complementary calculator slice (non-UI)"[:200]


def build_canned_roster_line(self_name: str) -> str:
    model = ag.MODEL.split("/")[-1] if "/" in ag.MODEL else ag.MODEL
    return (
        f"[ROSTER] {self_name} | SWE agent | "
        f"tools: bash, read_file, edit_file | backend: {model} | "
        f"standing by for task assignment from manager"
    )


def _operator_kind_label(op_cmd: str | None) -> str:
    if not op_cmd:
        return "none"
    if is_work_operator_directive(op_cmd):
        return "work"
    if _GRADER_BOILERPLATE_RE.search(op_cmd):
        return "grader"
    return "other"


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


def has_imperative(text: str | None) -> bool:
    """True if text contains an imperative command verb (whole-word match)."""
    if not text:
        return False
    return _IMPERATIVE_RE.search(text) is not None


_STRUCTURED_DELIVERY_RE = re.compile(
    r"(?:^[\*\-]\s+\S+.*\n.*?){2,}"  # 2+ consecutive bullet lines
    r"|^#{1,4}\s+\w+"                # markdown header (# ... ####)
    r"|\*\*[\w\s]+:\*\*"             # bold label "**X:**"
    r"|^\d+\.\s+\w+",                # numbered list "1. X"
    re.MULTILINE,
)


def is_empty_promise(reply: str) -> bool:
    """True if reply contains future-tense intent without any past-tense delivery.

    Structured content (bullet lists, markdown headers, "**Label:**" patterns)
    counts as a delivery — a Planner's plan IS the deliverable, even when
    prefixed with "I will act as the planner. **Feature List:** ...".
    """
    if not reply or reply == "PASS":
        return False
    if not _PROMISE_RE.search(reply):
        return False
    if _DELIVERY_RE.search(reply):
        return False
    if _STRUCTURED_DELIVERY_RE.search(reply):
        return False  # bullet list / header / bold labels = real content
    return True


def has_disallowed_promise(reply: str) -> bool:
    """True if the hub message must not be sent — pure or mixed future-tense promises.

    Mixed pattern (the Project Tracker bug): "Created requirements.txt. Next, I will
    create models.py" — is_empty_promise returns False because of "Created", but the
    message still advertises work not done this turn.
    """
    if not reply or reply == "PASS":
        return False
    # Structured content (Planner's plan, bullet/markdown specs) — let it through
    # even if it contains "I will act as the planner" preamble.
    if _STRUCTURED_DELIVERY_RE.search(reply):
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
    if not reply or reply == "PASS":
        return False
    # A formal CODE TRANSFER message ("Klar med: `file`\n```...```") is, by
    # definition, a delivery. The code itself may legitimately contain "error",
    # "failed", "issue" etc. as string literals — those must not mark the
    # message as non-delivery.
    if re.search(r"(?:klar med|done with)[:\s]+`[\w./-]+`", reply, re.IGNORECASE):
        return False
    if _DELIVERY_RE.search(reply):
        return False
    return _NON_DELIVERY_RE.search(reply) is not None


def hub_reply_blocked(reply: str) -> bool:
    """True if this reply must not be posted to the hub."""
    return has_disallowed_promise(reply) or is_non_delivery_reply(reply)


def split_for_hub(reply: str, max_len: int = 4090) -> list[str]:
    """Split reply into hub messages ≤ max_len.

    First splits on ag.HUB_MSG_BREAK boundaries (used by format_code_transfer
    when packing a multi-part code paste into a single reply string), then
    chunks any over-length piece at code-block or newline boundaries.
    """
    pieces = [p for p in reply.split(ag.HUB_MSG_BREAK) if p.strip()]
    chunks: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if len(piece) <= max_len:
            chunks.append(piece)
            continue
        rest = piece
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
    if not reply or reply == "PASS":
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
    if not written_files or not reply or reply == "PASS":
        return None
    if reply.startswith("[auto-summary]"):
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
    if not reply or reply == "PASS":
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

# Component nouns that commonly appear at the end of a feature phrase
# ("question bank", "game loop", "scoring system"). Used to infer filenames
# from prose directives that don't name files explicitly.
_COMPONENT_SUFFIXES = frozenset({
    "bank", "system", "loop", "engine", "manager", "parser", "handler",
    "controller", "service", "client", "server", "registry", "store",
    "runner", "tracker", "validator", "formatter", "scheduler",
    "queue", "cache", "router", "dispatcher",
})

# Filler words stripped from prose component phrases before snake_casing.
_PROSE_STOP_WORDS = frozenset({
    "the", "a", "an", "this", "that", "these", "those",
    "our", "your", "my", "their", "and", "or", "to", "for",
    "we", "i", "need", "needs", "have", "build", "create",
    "implement", "make", "add", "with", "please",
})


def _extract_prose_components(text: str) -> list[str]:
    """Infer filenames from prose component phrases.

    'we need: question bank, scoring system, and game loop'
        -> ['question_bank.py', 'scoring_system.py', 'game_loop.py']

    Splits the directive on commas/semicolons/`and`/`or`, looks for a known
    component suffix in each chunk, and joins it with 1-2 preceding non-stop
    tokens as the qualifier.
    """
    chunks = re.split(r"[,;\n]| and | or ", text, flags=re.IGNORECASE)
    seen: set[str] = set()
    out: list[str] = []
    for chunk in chunks:
        words = re.findall(r"[a-z]+", chunk.lower())
        if not words:
            continue
        for i in range(len(words) - 1, -1, -1):
            if words[i] not in _COMPONENT_SUFFIXES:
                continue
            qualifiers: list[str] = []
            for j in range(i - 1, -1, -1):
                if words[j] in _PROSE_STOP_WORDS:
                    if qualifiers:
                        break
                    continue
                qualifiers.insert(0, words[j])
                if len(qualifiers) >= 2:
                    break
            if not qualifiers:
                break
            name = "_".join(qualifiers + [words[i]]) + ".py"
            if name not in seen:
                seen.add(name)
                out.append(name)
            break  # one component per chunk
    return out


def extract_required_filenames(operator_text: str | None) -> list[str]:
    """Filenames mentioned in an operator directive (multi-file tasks).

    Layer 1: explicit filenames with extension (`app.py`, db.py).
    Layer 2 (fallback): prose component phrases — only when Layer 1 found
    nothing, since an operator that names files directly is authoritative.
    """
    if not operator_text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _NAMED_FILE_RE.finditer(operator_text):
        name = (m.group(1) or m.group(2) or "").strip()
        if name and name not in seen and name != ".gitkeep":
            seen.add(name)
            out.append(name)
    if out:
        return out
    for name in _extract_prose_components(operator_text):
        if name not in seen:
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


# Matches "Klar med: `filename`" or "Done with: `filename`" followed by a fenced code block.
_CODE_TRANSFER_RE = re.compile(
    r"(?:klar med|done with)[:\s]+`([\w./-]+\.[a-z]{1,5})`"
    r".*?```[a-z]*\n(.*?)```",
    re.IGNORECASE | re.DOTALL,
)
# Detects "(part N/M)" split-message markers (case-insensitive).
_SPLIT_PART_RE = re.compile(r"\(\s*part\s+(\d+)\s*/\s*(\d+)\s*\)", re.IGNORECASE)
# Matches a bare fenced code block (without CODE TRANSFER header).
_BARE_CODE_BLOCK_RE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL | re.IGNORECASE)
# `# file: name.py` / `// file: name.py` / `# name.py` on FIRST line of a code block.
_FILE_HINT_RE = re.compile(
    r"^\s*(?:#|//|--)\s*(?:file\s*[:=]\s*)?([\w./-]+\.[a-z]{1,5})\b",
    re.IGNORECASE,
)
# Catches `# file: X.py` / `// file: X.js` / `<!-- file: X.html -->` ANYWHERE
# in a message followed by raw code on subsequent lines (no fence). Used when
# peers dump code as plain text instead of inside a ```fenced``` block.
_INLINE_FILE_MARKER_RE = re.compile(
    r"(?:^|\n)\s*(?:#|//|--|<!--)\s*file\s*[:=]\s*([\w./-]+\.[a-z]{1,5})\s*(?:-->)?\s*\n(.+)",
    re.IGNORECASE | re.DOTALL,
)
# `Filer: ...X.html` / `Files: foo.py` — extract filename from operator-style label.
_FILER_LABEL_RE = re.compile(
    r"(?:filer?|files?)\s*[:=]\s*[^\n]*?([\w./-]+\.[a-z]{1,5})\b",
    re.IGNORECASE,
)


def extract_code_transfers(content: str) -> list[tuple[str, str]]:
    """Return [(filename, code), ...] for every CODE TRANSFER block in a message.

    Detection layers (most specific first):
    1. "Klar med: `X`" / "Done with: `X`" followed by fenced ```code```
    2. Fenced ```code``` with `# file: X` hint on first line
    3. UNFENCED `# file: X.html` line followed by raw code (until end of message)
    """
    results: list[tuple[str, str]] = []
    seen_fnames: set[str] = set()
    # Layer 1: formal CODE TRANSFER headers
    for m in _CODE_TRANSFER_RE.finditer(content):
        fname = m.group(1).strip()
        code = m.group(2)
        if fname and code and fname not in seen_fnames:
            results.append((fname, code))
            seen_fnames.add(fname)
    # Layer 2: fenced bare code blocks with `# file: X` hint on first line
    for m in _BARE_CODE_BLOCK_RE.finditer(content):
        code = m.group(1)
        first_line = code.split("\n", 1)[0]
        hint = _FILE_HINT_RE.match(first_line)
        if hint:
            fname = hint.group(1).strip()
            if fname and fname not in seen_fnames:
                results.append((fname, code))
                seen_fnames.add(fname)
    # Layer 3: UNFENCED `# file: X` marker followed by raw code to end of message.
    # Used by peers that dump HTML/Python directly without ```fences```.
    inline_m = _INLINE_FILE_MARKER_RE.search(content)
    if inline_m:
        fname = inline_m.group(1).strip()
        code = inline_m.group(2).strip()
        if fname and code and fname not in seen_fnames:
            results.append((fname, code))
            seen_fnames.add(fname)
    return results


def auto_save_peer_code(
    messages: list[dict],
    workspace_dir: str,
    log,
    state: "AgentState | None" = None,
) -> list[str]:
    """Save code blocks shared by peers to local workspace. Returns saved filenames.

    Also performs lightweight sync validation:
    - Truncation: messages with "(truncated" marker → file marked incomplete.
    - Conflict: existing file content differs from peer's → logged with char-diff.
    - Syntax: Python files run through `py_compile` → failures recorded.
    Issues are stored on AgentState.peer_file_issues for prompt injection.
    """
    saved: list[str] = []
    root = Path(workspace_dir)
    for msg in messages:
        if msg["agent_name"] == AGENT_NAME:
            continue
        msg_content = msg["content"]
        msg_truncated = "(truncated" in msg_content
        peer_name = msg["agent_name"]

        # Handle SPLIT CODE TRANSFER messages ("(part N/M)") — buffer parts in
        # state, concatenate when complete. Skips the regular extract path for
        # subsequent parts (which lack the Klar med: header).
        split_match = _SPLIT_PART_RE.search(msg_content)
        if split_match and state is not None:
            part_n = int(split_match.group(1))
            part_total = int(split_match.group(2))

            # Extract this part's code chunk. Layers:
            #   a) fenced bare code block → use its content
            #   b) inline `# file: X` marker → use everything after that line
            #   c) raw text after the `(part N/M)` line — strip header lines
            part_code: str | None = None
            code_match = _BARE_CODE_BLOCK_RE.search(msg_content)
            inline_marker = _INLINE_FILE_MARKER_RE.search(msg_content)
            if code_match:
                part_code = code_match.group(1)
            elif inline_marker:
                part_code = inline_marker.group(2).rstrip()
            else:
                # Raw split — drop the "(part N/M)" line and any "Klar med:" line,
                # treat the rest as code body.
                lines = msg_content.split("\n")
                trimmed: list[str] = []
                skip_phase = True
                for ln in lines:
                    if skip_phase and (
                        _SPLIT_PART_RE.search(ln)
                        or re.match(r"\s*(?:klar med|done with)\b", ln, re.IGNORECASE)
                        or not ln.strip()
                    ):
                        continue
                    skip_phase = False
                    trimmed.append(ln)
                if trimmed:
                    part_code = "\n".join(trimmed)

            if part_code:
                # Resolve filename for this split. Layers:
                #   a) Klar med: `X` header
                #   b) inline `# file: X` marker
                #   c) Filer:/Files: label
                #   d) lookup recent split from same peer (subsequent parts have no header)
                fname: str | None = None
                fname_match = re.search(
                    r"(?:klar med|done with)[:\s]+`([\w./-]+\.[a-z]{1,5})`",
                    msg_content, re.IGNORECASE,
                )
                if fname_match:
                    fname = fname_match.group(1)
                elif inline_marker:
                    fname = inline_marker.group(1).strip()
                else:
                    filer_match = _FILER_LABEL_RE.search(msg_content)
                    if filer_match:
                        # Use basename only — peer may say "/workspace/proj/X.html"
                        fname = filer_match.group(1).split("/")[-1]
                if not fname:
                    for buf_fname, meta in state.split_transfer_meta.items():
                        if meta.get("peer") == peer_name and meta.get("total") == part_total:
                            fname = buf_fname
                            break
                if fname:
                    state.split_transfer_buffer.setdefault(fname, {})[part_n] = part_code
                    state.split_transfer_meta[fname] = {
                        "total": part_total,
                        "peer": peer_name,
                        "last_seq": msg.get("seq", 0),
                    }
                    log.info(
                        "buffered split CODE TRANSFER: `%s` part %d/%d from %s (%d chars)",
                        fname, part_n, part_total, peer_name, len(part_code),
                    )
                    received = state.split_transfer_buffer[fname]
                    if len(received) == part_total:
                        # Strip trailing newlines that fenced-block capture
                        # picks up before the closing ```, then re-join with
                        # \n so the reconstruction matches the original file
                        # whether the sender used standard or non-standard
                        # markdown fence-closing.
                        full_code = "\n".join(
                            received[i].rstrip("\n")
                            for i in sorted(received.keys())
                        )
                        target = root / fname
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(full_code, encoding="utf-8")
                        log.info(
                            "auto-saved `%s` from split (%d parts merged, %d chars)",
                            fname, part_total, len(full_code),
                        )
                        saved.append(fname)
                        state.peer_file_issues.pop(fname, None)
                        state.split_transfer_buffer.pop(fname, None)
                        state.split_transfer_meta.pop(fname, None)
                    else:
                        missing = part_total - len(received)
                        state.peer_file_issues[fname] = (
                            f"incomplete split: {len(received)}/{part_total} parts received "
                            f"(missing {missing})"
                        )
                    continue  # don't fall through to normal save

        for fname, code in extract_code_transfers(msg_content):
            target = root / fname
            target.parent.mkdir(parents=True, exist_ok=True)

            existing: str | None = None
            if target.is_file():
                try:
                    existing = target.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    existing = None
            if existing is not None and existing != code:
                log.info(
                    "auto-save overwriting `%s` (was %d chars, now %d chars) from %s",
                    fname, len(existing), len(code), msg["agent_name"],
                )

            target.write_text(code, encoding="utf-8")
            log.info("auto-saved `%s` from %s", fname, msg["agent_name"])
            saved.append(fname)

            if state is None:
                continue

            if msg_truncated:
                state.peer_file_issues[fname] = "truncated in chat — incomplete"
                log.warning("INCOMPLETE code for `%s` from %s (truncated)",
                            fname, msg["agent_name"])
            elif fname.endswith(".py"):
                try:
                    proc = subprocess.run(
                        ["python", "-m", "py_compile", fname],
                        cwd=workspace_dir,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if proc.returncode != 0:
                        err = (proc.stderr or proc.stdout or "compile failed").strip()
                        state.peer_file_issues[fname] = f"syntax: {err[:150]}"
                        log.warning("SYNTAX ERROR in `%s` from %s: %s",
                                    fname, msg["agent_name"], err[:200])
                    elif fname in state.peer_file_issues:
                        # File previously broken, now compiles — clear the issue.
                        state.peer_file_issues.pop(fname, None)
                except (subprocess.TimeoutExpired, OSError) as e:
                    log.warning("py_compile failed for `%s`: %s", fname, e)
    return saved


def chat_delivered_files(messages: list[dict]) -> dict[str, str]:
    """Return {filename: agent_name} for files already shared via CODE TRANSFER in chat."""
    delivered: dict[str, str] = {}
    for msg in messages:
        for fname, _ in extract_code_transfers(msg["content"]):
            if fname not in delivered:
                delivered[fname] = msg["agent_name"]
    return delivered


def build_workspace_gap_section(
    op_cmd: str | None,
    workspace_dir: str,
    messages: list[dict] | None = None,
    peer_file_issues: dict[str, str] | None = None,
) -> str:
    """Inject missing/existing filenames for large multi-file operator tasks.

    Also lists files already delivered via CODE TRANSFER in chat so the agent
    does not rebuild what a peer already shared. If peer_file_issues is given,
    appends a section so the LLM can decide to ask for a repost or rewrite.
    """
    required = extract_required_filenames(op_cmd)
    present = list_workspace_filenames(workspace_dir)
    delivered = chat_delivered_files(messages or [])

    lines: list[str] = []

    if len(required) >= 2:
        missing = [f for f in required if f not in present]
        present_named = [f for f in required if f in present]
        if missing:
            lines.append(f"Missing on disk (pick ONE to create this turn): {', '.join(missing)}")
        if present_named:
            lines.append(f"Already on disk: {', '.join(present_named)}")

    if delivered:
        parts = [f"`{f}` (by {a})" for f, a in delivered.items()]
        lines.append(
            f"Already delivered in chat — do NOT rebuild: {', '.join(parts)}"
        )

    if peer_file_issues:
        lines.append("PEER FILES WITH ISSUES — consider asking author to repost or rewrite locally:")
        for fname, issue in peer_file_issues.items():
            lines.append(f"  - `{fname}`: {issue}")

    if not lines:
        return ""
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


def was_delegated_to_me(
    messages: list[dict],
    *,
    ctx: list[dict] | None = None,
) -> bool:
    """True if a peer @mentioned this agent and asked them to take work."""
    search_msgs = ctx if ctx is not None else messages
    for m in search_msgs:
        if m["agent_name"] == AGENT_NAME:
            continue
        content = m["content"]
        if _MENTION_ME_RE.search(content) and _DELEGATION_HINT_RE.search(content):
            return True
    return False


_PINNED_MEMORY_CAP = 8


def update_pinned_memory(state, external: list[dict]) -> None:
    """Pin high-signal facts so they survive history trimming.

    Captures peer/own role claims, delivery headers, and direct @{AGENT_NAME}
    tasks as compact one-liners. Deduped and capped to the most recent
    _PINNED_MEMORY_CAP entries. Surfaced by build_active_prompt as SESSION MEMORY.
    """
    for m in external:
        who = m["agent_name"]
        content = m["content"]
        entry: str | None = None
        delivery = _DELIVERY_CAPTURE_RE.search(content)
        claim = _CLAIM_CAPTURE_RE.search(content)
        if delivery:
            entry = f"{who} delivered: {delivery.group(1).strip()}"
        elif claim:
            entry = f"{who} claimed: {claim.group(1).strip()}"
        elif (
            who != AGENT_NAME
            and re.search(rf"@?{re.escape(AGENT_NAME)}\b", content, re.IGNORECASE)
            and not _SOCIAL_ONLY_RE.match(content.strip())
        ):
            snippet = " ".join(content.split())[:80]
            entry = f"{who} → you: {snippet}"
        if entry and entry not in state.pinned_memory:
            state.pinned_memory.append(entry)
    if len(state.pinned_memory) > _PINNED_MEMORY_CAP:
        del state.pinned_memory[: -_PINNED_MEMORY_CAP]


_RUNTIME_CONFIG_PATH = Path("config/runtime.json")
_SYSTEM_PROMPT_PATH = Path("config/system_prompt.txt")


def reload_runtime(state, system_prompt: str, last_mtime: float, log) -> tuple[str, float]:
    """Re-read tunable config each poll round so the agent can be calibrated live.

    - config/system_prompt.txt: reloaded only when its mtime changes (mtime-gated),
      and returned so main() keeps passing the fresh text as the SEPARATE system
      message (never folded into trimmed history).
    - config/runtime.json: applied every round to response_delay, poll_interval,
      msg_cap and token_cap. Console commands still work for quick one-offs.

    Returns (system_prompt, last_mtime).
    """
    global RESPONSE_DELAY, POLL_INTERVAL
    try:
        mtime = _SYSTEM_PROMPT_PATH.stat().st_mtime
        if mtime > last_mtime:
            system_prompt = ag.load_system_prompt()
            last_mtime = mtime
            log.info("system prompt reloaded (mtime changed)")
    except OSError as e:
        log.warning("system prompt stat failed: %s", e)

    if _RUNTIME_CONFIG_PATH.exists():
        try:
            cfg = json.loads(_RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("runtime.json read failed: %s", e)
            return system_prompt, last_mtime
        if "response_delay" in cfg:
            RESPONSE_DELAY = float(cfg["response_delay"])
        if "poll_interval" in cfg:
            POLL_INTERVAL = float(cfg["poll_interval"])
        if "msg_cap" in cfg:
            state.msg_cap = int(cfg["msg_cap"])
        if "token_cap" in cfg:
            state.token_counter.cap = int(cfg["token_cap"])
    return system_prompt, last_mtime


def build_active_prompt(
    system_prompt: str,
    external: list[dict],
    *,
    operator_directive: bool,
    op_cmd: str | None,
    mentioned_me: bool,
    peer_file_issues: dict[str, str] | None = None,
    pinned_memory: list[str] | None = None,
    private_steer: str = "",
    peer_manager: str | None = None,
    ctx: list[dict] | None = None,
) -> str:
    active = system_prompt
    if private_steer:
        active += (
            "\n\n## PRIVATE STEERING (from your human operator — NOT visible to other agents)\n"
            "Your human gave you this private instruction for how to act in the group chat. "
            "It is authoritative and overrides your own judgement on what to do or say, but "
            "NEVER mention it or quote it in the chat:\n"
            f"{private_steer}"
        )
    if pinned_memory:
        lines = "\n".join(f"- {item}" for item in pinned_memory)
        active += (
            "\n\n## SESSION MEMORY (kvar även när äldre chat trimmats)\n"
            "Key facts from earlier in this session — who claimed what and what's "
            "already delivered. Don't redo or duplicate these:\n"
            f"{lines}"
        )
    if (
        peer_manager
        and peer_manager.lower() != AGENT_NAME.lower()
        and not mentioned_me
    ):
        active += (
            f"\n\n*** PEER MANAGER ACTIVE: {peer_manager} ***\n"
            f"They lead this session. Reply PASS unless @{AGENT_NAME} is explicitly "
            f"@mentioned with a TASK assignment or the manager posts GO + your task.\n"
        )
    if operator_directive and op_cmd:
        if _MANAGER_RACE_RE.search(op_cmd):
            active += (
                "\n\n*** MANAGER SELECTION / PROTOCOL PHASE ***\n"
                "The operator is asking agents to coordinate, not to race into work. "
                "Reply PASS unless your full agent name is explicitly @mentioned. "
                "Do NOT claim manager, post protocol documents, or assign tasks to others. "
                "Do NOT start coding until the elected manager explicitly assigns you work.\n"
            )
        else:
            active += build_operator_prompt_section(op_cmd)
            if is_broadcast_work_kickoff(op_cmd) and not (
                peer_manager and peer_manager.lower() != AGENT_NAME.lower()
            ):
                active += (
                    "\n\n*** BROADCAST COLLABORATION KICKOFF ***\n"
                    "Operator addressed all agents. Post ONE short claim for a "
                    "non-overlapping slice (e.g. \"Taking: portfolio risk module\") "
                    "OR deliver ONE concrete file this turn. Do NOT repeat files peers "
                    "already reported Klar med / Done with. PASS is forbidden on your "
                    "first response to this directive (unless STOP or manager-roster).\n"
                )
            active += build_workspace_gap_section(
                op_cmd, ag.WORKSPACE_DIR, external, peer_file_issues=peer_file_issues,
            )
        active += read_project_status_section(ag.WORKSPACE_DIR)
    # Warn about active peer claims so the LLM doesn't duplicate claimed work.
    kickoff = bool(op_cmd and is_broadcast_work_kickoff(op_cmd))
    for m in external:
        if m["agent_name"] != AGENT_NAME and _PEER_CLAIM_RE.search(m["content"]):
            snippet = m["content"][:80].replace("\n", " ")
            if kickoff:
                active += (
                    f"\n\n⚠️ PEER CLAIM ACTIVE: {m['agent_name']} claimed \"{snippet}\"."
                    f" Pick a DIFFERENT sub-deliverable — do not PASS on the whole task."
                )
            else:
                active += (
                    f"\n\n⚠️ PEER CLAIM ACTIVE: {m['agent_name']} just claimed \"{snippet}\"."
                    f" PASS unless you have a clearly different, non-overlapping deliverable."
                )
            break
    if mentioned_me:
        role_distribution = bool(op_cmd and _ROLE_DISTRIBUTION_RE.search(op_cmd))
        if operator_directive or was_delegated_to_me(external, ctx=ctx):
            if role_distribution:
                active += (
                    f"\n\nROLE-DISTRIBUTION TASK: @{AGENT_NAME} is one of several agents "
                    f"asked to play distinct roles. FIRST claim ONE specific role with "
                    f"`Taking: [role name]` and then PASS this round — let peers claim "
                    f"the other roles. NEVER write placeholder/stub files. Only build "
                    f"AFTER you have claimed your role and the assignment is clear."
                )
            else:
                active += (
                    f"\n\nDELEGATION OVERRIDE: @{AGENT_NAME} was mentioned during an active "
                    f"operator task. Use bash or edit_file THIS turn — deliver ONE file or "
                    f"run ONE verification with quoted output. PASS and 'I will...' are FORBIDDEN. "
                    f"NEVER write a placeholder/stub file (e.g. only comments). If you cannot "
                    f"deliver functional code this turn, PASS instead."
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
    is_question_response: bool = False,
) -> str:
    """Re-prompt until reply is deliverable (no promises / complaint / missing paste / hallucinated).

    is_question_response: when True, the non-delivery filter is relaxed. Used
    when responding to a direct @mention question ("are you here?") where a
    short status answer is the expected delivery — not buildable code.
    """
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
        elif (
            "BLOCKED (absolute path" in reply
            or "absolute path outside workspace" in reply.lower()
        ):
            log.info(
                "absolute-path complaint — retry %d/%d",
                attempts + 1,
                max_retries,
            )
            extra = (
                "You hit an absolute-path BLOCK. The workspace IS your CWD — "
                "use `cat > file.py <<EOF` NOT `cat > /app/workspace/file.py <<EOF`. "
                "Retry the same command using ONLY the relative filename now."
            )
        elif not is_question_response and is_non_delivery_reply(reply):
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
        # Retries use a tight rounds cap (3) — they're meant to reformat the
        # last reply, not do new exploration. Saves significant tokens compared
        # to giving each retry the full MAX_ROUNDS=10 budget.
        reply = ag.decide(
            external, AGENT_NAME, nudge, history, token_counter, max_rounds=3,
        )
        log.info(
            "← send-quality retry reply: %s",
            reply[:120] if reply != "PASS" else "PASS",
        )
        attempts += 1
    return reply


def is_work_operator_directive(op_cmd: str | None) -> bool:
    """False for manager-selection-only broadcasts (no parallel build/self-organize)."""
    if not op_cmd or not has_imperative(op_cmd):
        return False
    if _MANAGER_RACE_RE.search(op_cmd) and not _SELF_ORGANIZE_BUILD_RE.search(op_cmd):
        return False
    return True


def operator_self_organize_build(op_cmd: str | None) -> bool:
    """True when operator told agents to self-organize AND build (Igor-style combo)."""
    if not op_cmd:
        return False
    return bool(
        _SELF_ORGANIZE_BUILD_RE.search(op_cmd)
        and has_imperative(op_cmd)
        and (
            _BROADCAST_OPERATOR_RE.search(op_cmd)
            or _BROADCAST_ADDRESS_RE.match(op_cmd.strip())
        )
    )


def should_defer_to_peer_manager(
    external: list[dict],
    op_cmd: str | None,
    peer_manager: str | None,
    self_name: str,
    *,
    mentioned_me: bool,
    delegated: bool,
    roster_posted: bool = False,
    claim_posted: bool = False,
) -> bool:
    """Whether to skip LLM and wait for manager TASK/@mention."""
    if mentioned_me or delegated:
        return False
    if roster_response_due(
        external, peer_manager, self_name, roster_posted=roster_posted,
    ):
        return False
    if manager_open_claim_due(
        external, peer_manager, self_name, claim_posted=claim_posted,
    ):
        return False
    if not peer_manager or peer_manager.lower() == self_name.lower():
        return False
    if development_frozen_by_manager(external, peer_manager):
        return True
    if roster_phase_active(external, peer_manager):
        return True
    if operator_self_organize_build(op_cmd):
        return False
    return True


def is_broadcast_work_kickoff(op_cmd: str | None) -> bool:
    """True when operator broadcast asks all agents to start real work (not ROSTER/manager race)."""
    if not op_cmd or not is_work_operator_directive(op_cmd):
        return False
    if _ROSTER_PHASE_RE.search(op_cmd):
        return False
    if _MANAGER_RACE_RE.search(op_cmd) and not _SELF_ORGANIZE_BUILD_RE.search(op_cmd):
        return False
    if not _BROADCAST_OPERATOR_RE.search(op_cmd) and not _BROADCAST_ADDRESS_RE.match(
        op_cmd.strip(),
    ):
        return False
    return has_imperative(op_cmd)


def extract_explicit_filenames(operator_text: str | None) -> set[str]:
    """Filenames literally named in operator text (not prose-inferred)."""
    if not operator_text:
        return set()
    out: set[str] = set()
    for m in _NAMED_FILE_RE.finditer(operator_text):
        name = (m.group(1) or m.group(2) or "").strip()
        if name and name != ".gitkeep":
            out.add(name)
    return out


def peer_overlap_blocks_turn(
    op_cmd: str | None,
    peer_done: set[str],
    *,
    mentioned_me: bool,
) -> bool:
    """Whether pre-LLM PASS is warranted because peers already delivered required files."""
    if mentioned_me or not op_cmd:
        return False
    required = set(extract_required_filenames(op_cmd))
    overlap = required & peer_done
    if not overlap:
        return False
    if is_broadcast_work_kickoff(op_cmd):
        explicit = extract_explicit_filenames(op_cmd)
        if not explicit:
            return False
        return explicit <= peer_done
    return True


def build_broadcast_kickoff_claim(
    op_cmd: str | None,
    messages: list[dict],
    workspace_dir: str,
    self_name: str,
) -> str:
    """Short deterministic claim when LLM stays PASS on an all-agents work kickoff."""
    peer_done = files_delivered_by_peers(messages, self_name)
    required = extract_required_filenames(op_cmd)
    present = list_workspace_filenames(workspace_dir)
    missing = [
        f for f in required
        if f not in present and f not in peer_done
    ]
    if missing:
        label = Path(missing[0]).stem.replace("_", " ")
        return f"[CLAIM] Taking: {label} (`{missing[0]}`)"[:200]
    if op_cmd:
        snippet = re.sub(r"\s+", " ", op_cmd.strip())[:70]
        return f"[CLAIM] Taking: complementary slice — {snippet}"[:200]
    return "[CLAIM] Taking: next unclaimed deliverable for the operator task"[:200]


def operator_directive_pending(messages: list[dict]) -> bool:
    """True when an operator/grader imperative directive is still active."""
    cmd = latest_operator_command(messages)
    return is_work_operator_directive(cmd)


def _message_claims_manager(content: str) -> bool:
    if _MANAGER_NAME_LINE_RE.search(content):
        return True
    if _TAKING_MANAGER_ROLE_RE.search(content):
        return True
    if _STEP_UP_MANAGER_RE.search(content):
        return True
    if _PEER_MANAGER_CLAIM_RE.search(content):
        return True
    if _CLAIM_MANAGER_ROLE_RE.search(content):
        return True
    if _MANAGER_ME_PROTOCOL_RE.search(content) and _ROSTER_PHASE_RE.search(content):
        return True
    if re.search(
        r"\b(I will act as the manager|your manager for this session)\b",
        content,
        re.IGNORECASE,
    ):
        return True
    return False


def _designated_peer_manager(content: str, agent_name: str) -> str | None:
    """Manager named by a human/operator ('listen to X that is the manager')."""
    if not is_operator_agent(agent_name):
        return None
    dm = _DESIGNATED_PEER_MANAGER_RE.search(content)
    if not dm:
        return None
    return (dm.group(1) or dm.group(2) or "").strip() or None


def resolve_peer_manager(messages: list[dict], self_name: str) -> str | None:
    """Elected manager from chat (newest explicit claim wins)."""
    self_low = self_name.lower()
    for m in reversed(messages):
        content = m["content"]
        mm = _MANAGER_NAME_LINE_RE.search(content)
        if mm:
            return mm.group(1)
        designated = _designated_peer_manager(content, m["agent_name"])
        if designated:
            return designated
        if _message_claims_manager(content):
            return m["agent_name"]
        if m["agent_name"].lower() == self_low and re.search(
            r"\b(I will act as the manager|your manager for this session)\b",
            content,
            re.IGNORECASE,
        ):
            return self_name
    return None


def is_unsolicited_roster_post(
    reply: str,
    *,
    mentioned_me: bool,
    delegated: bool,
    solicited: bool = False,
) -> bool:
    """True when reply is a broadcast-style ROSTER line without personal assignment."""
    if solicited:
        return False
    return bool(
        _UNSOLICITED_ROSTER_RE.match(reply or "")
        and not mentioned_me
        and not delegated
    )


def manager_work_released(
    messages: list[dict],
    peer_manager: str | None = None,
) -> bool:
    """True after the manager (or operator) explicitly releases the team to build."""
    for m in reversed(messages):
        content = m["content"]
        if _MANAGER_GO_RELEASE_RE.search(content):
            return True
        if peer_manager and (
            m["agent_name"] == peer_manager
            or is_operator_agent(m["agent_name"])
        ):
            if _MANAGER_TASK_ASSIGNMENT_RE.search(content):
                return True
    return False


def development_frozen_by_manager(
    messages: list[dict],
    peer_manager: str | None = None,
) -> bool:
    """True while chat says wait for manager GO / don't start working yet."""
    if manager_work_released(messages, peer_manager):
        return False
    for m in reversed(messages[-40:]):
        if _MANAGER_GO_WAIT_RE.search(m["content"]):
            return True
    return False


def roster_phase_active(messages: list[dict], peer_manager: str | None) -> bool:
    """True during manager's roster-only registration window."""
    if not peer_manager or manager_work_released(messages, peer_manager):
        return False
    if roster_collection_closed(messages):
        return False
    for m in reversed(messages[-25:]):
        if m["agent_name"] != peer_manager:
            continue
        if _ROSTER_PHASE_RE.search(m["content"]):
            return True
    return False


def files_delivered_by_peers(messages: list[dict], self_name: str, *, window: int = 20) -> set[str]:
    """Filenames peers already claimed, pasted, or reported done in recent chat."""
    self_low = self_name.lower()
    found: set[str] = set()
    for m in messages[-window:]:
        if m["agent_name"].lower() == self_low:
            continue
        text = m["content"]
        tagged = _FILE_RE.findall(text)
        if (
            _DELIVERY_RE.search(text)
            or re.search(r"(?:\bDONE\b|\bCLAIM:)", text, re.IGNORECASE)
            or re.search(r"\bklar med\b", text, re.IGNORECASE)
            or ("```" in text and tagged)
        ):
            found.update(tagged)
            if re.search(r"\bCLAIM:\s*[`']?([\w./-]+\.py)", text, re.IGNORECASE):
                found.update(re.findall(r"\bCLAIM:\s*[`']?([\w./-]+\.py)", text, re.IGNORECASE))
    return found


def sync_session_flags_from_history(messages: list[dict], state: "AgentState", self_name: str) -> None:
    """Restore STOP silence and peer-manager from hub history on startup."""
    state.silence_active = apply_stop_resume_from_messages(messages)
    pm = resolve_peer_manager(messages, self_name)
    if pm:
        state.peer_manager = pm
    if state.silence_active:
        state.active_op_cmd = None
        state.active_op_seq = 0


def resolve_op_cmd(
    sticky_cmd: str | None,
    batch_cmd: str | None,
    *,
    work_cmd: str | None = None,
) -> tuple[str | None, bool]:
    """Pick active operator text; work directives only."""
    op_cmd = work_cmd or batch_cmd or sticky_cmd
    if op_cmd and not is_work_operator_directive(op_cmd):
        candidates = [c for c in (work_cmd, batch_cmd, sticky_cmd) if c]
        op_cmd = next(
            (c for c in candidates if is_work_operator_directive(c)),
            None,
        )
    return op_cmd, is_work_operator_directive(op_cmd)


def would_duplicate_peer_delivery(reply: str, peer_files: set[str]) -> bool:
    """True if reply re-posts a file a peer already delivered."""
    for fn in peer_files:
        if re.search(rf"\bKlar med:\s*`?{re.escape(fn)}`?", reply, re.IGNORECASE):
            return True
    return False


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


_HEARTBEAT_INTERVAL_S = 30.0


def _log_poll_heartbeat(
    state: "AgentState",
    log,
    *,
    force: bool = False,
    ctx_len: int | None = None,
    roster_due: bool | None = None,
    roster_closed: bool | None = None,
    claim_due: bool | None = None,
) -> None:
    """Periodic visibility line so tail -f shows the agent is alive."""
    now = time.time()
    if not force and (now - state.last_heartbeat_at) < _HEARTBEAT_INTERVAL_S:
        return
    state.last_heartbeat_at = now
    op_kind = _operator_kind_label(state.active_op_cmd)
    roster_label = (
        "yes" if roster_due else "no" if roster_due is not None else "—"
    )
    closed_label = (
        "yes" if roster_closed else "no" if roster_closed is not None else "—"
    )
    claim_label = (
        "yes" if claim_due else "no" if claim_due is not None else "—"
    )
    log.info(
        "poll ok  last_seen=%s  paused=%s  silence=%s  peer_mgr=%s  "
        "roster_due=%s  roster_closed=%s  claim_due=%s  op=%s  ctx_len=%s  msgs=%d/%d",
        state.last_seen,
        "yes" if state.paused else "no",
        "yes" if state.silence_active else "no",
        state.peer_manager or "(none)",
        roster_label,
        closed_label,
        claim_label,
        op_kind,
        ctx_len if ctx_len is not None else "—",
        state.messages_sent,
        state.msg_cap,
    )


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
    try:
        prompt_mtime = _SYSTEM_PROMPT_PATH.stat().st_mtime
    except OSError:
        prompt_mtime = 0.0
    token_counter = ag.TokenCounter(cap=TOKEN_CAP)
    state = AgentState(msg_cap=MSG_CAP, token_counter=token_counter)
    state.private_steer = ag.load_private_steer()
    if state.private_steer:
        log.info("loaded private steering (%d chars)", len(state.private_steer))
    history: list = []

    # Seed runtime.json from the resolved env config so live edits start from the
    # actual running values (avoids silently overriding .env on first run). The file
    # is git-ignored; config/runtime.json.example is the checked-in template.
    if not _RUNTIME_CONFIG_PATH.exists():
        try:
            _RUNTIME_CONFIG_PATH.write_text(
                json.dumps(
                    {
                        "response_delay": RESPONSE_DELAY,
                        "poll_interval": POLL_INTERVAL,
                        "msg_cap": MSG_CAP,
                        "token_cap": TOKEN_CAP,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            log.info("seeded config/runtime.json from env config")
        except OSError as e:
            log.warning("could not seed runtime.json: %s", e)

    console = Console(state)
    console.start()

    system_prompt, prompt_mtime = reload_runtime(state, system_prompt, prompt_mtime, log)

    dry = hub.DRY_RUN
    log.info("=" * 50)
    log.info("Part 3 — Multi-Agent Group Chat")
    log.info("Agent  : %s", AGENT_NAME)
    log.info("Model  : %s", ag.MODEL)
    log.info("Hub    : %s", hub.HUB_URL)
    log.info("Mode   : %s", "DRY-RUN (no posts)" if dry else "LIVE")
    log.info("Caps   : %d msgs / %d tokens", state.msg_cap, state.token_counter.cap)
    log.info("Delay  : %.1fs", RESPONSE_DELAY)
    log.info(
        "Trace  : %s (tail logs or console: trace / trace on; set TRACE=1 in .env)",
        "on" if tr.TRACE_TO_LOG else "buffer only",
    )
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
            sync_session_flags_from_history(bootstrap, state, AGENT_NAME)
            if state.silence_active:
                log.info("bootstrap: STOP/silence active from history")
            if state.peer_manager:
                log.info("bootstrap: peer manager is %s", state.peer_manager)
    except Exception as e:
        log.warning("bootstrap fetch failed: %s", e)

    log.info("agent loop started — tail logs/%s.log for routing/PASS/SENT", AGENT_NAME)
    _log_poll_heartbeat(state, log, force=True)

    while state.running:
      try:
        if state.paused:
            time.sleep(1)
            continue

        # Live calibration: re-read system_prompt.txt (mtime-gated) and runtime.json
        # each round so prompts/knobs can be tuned mid-session without a restart.
        system_prompt, prompt_mtime = reload_runtime(state, system_prompt, prompt_mtime, log)

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
            _log_poll_heartbeat(state, log)
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

        # Auto-save any code blocks peers shared via CODE TRANSFER.
        auto_save_peer_code(external, ag.WORKSPACE_DIR, log, state)

        # Pin the most important facts (role claims, deliveries, tasks aimed at us)
        # so they survive history trimming and stay in SESSION MEMORY.
        update_pinned_memory(state, external)

        # Mention routing: skip only if a message STARTS with @other (primary address).
        # Incidental @mentions mid-message ("great @mini_me2! now let's...") do not block.
        mentioned_me = any(_MENTION_ME_RE.search(m["content"]) for m in external)
        mentioned_other = (
            not mentioned_me and (
                any(
                    (
                        (m["content"].strip().startswith("@") and
                         not _BROADCAST_ADDRESS_RE.match(m["content"].strip())) or
                        _COLON_ADDRESS_RE.match(m["content"].strip())
                    ) and f"@{AGENT_NAME}" not in m["content"]
                    for m in external
                )
                or any(addressed_to_other_by_name(m["content"]) for m in external)
            )
        )

        log.info("routing  mentioned_me=%s  mentioned_other=%s", mentioned_me, mentioned_other)

        if mentioned_other:
            log.info("SKIP — message is primarily addressed to another agent")
            tr.record("PASS", "addressed to other agent")
            time.sleep(POLL_INTERVAL)
            continue

        ctx = routing_context(state, external)

        peer_mgr = resolve_peer_manager(ctx, AGENT_NAME)
        if peer_mgr:
            if state.peer_manager and state.peer_manager != peer_mgr:
                state.roster_posted = False
                state.claim_posted = False
            state.peer_manager = peer_mgr

        for _m in ctx:
            if re.search(r"close roster|roster is closed", _m["content"], re.IGNORECASE):
                state.roster_posted = False

        # Update sticky operator directive if a newer imperative arrived.
        new_op_msg = latest_imperative_operator_message(external)
        work_msg = best_work_operator_message(ctx)
        if work_msg and is_work_operator_directive(work_msg["content"]):
            ws = _operator_message_score(work_msg["content"])
            cur_score = _operator_message_score(state.active_op_cmd or "")
            if ws > cur_score and work_msg.get("seq", 0) >= state.active_op_seq:
                state.active_op_cmd = work_msg["content"]
                state.active_op_seq = work_msg.get("seq", 0)
                log.info("sticky work operator updated → seq=%d", state.active_op_seq)
        elif new_op_msg and new_op_msg.get("seq", 0) > state.active_op_seq:
            if is_work_operator_directive(new_op_msg["content"]):
                state.active_op_cmd = new_op_msg["content"]
                state.active_op_seq = new_op_msg.get("seq", 0)
                log.info("sticky operator directive updated → seq=%d", state.active_op_seq)
            elif _MANAGER_RACE_RE.search(new_op_msg["content"]):
                log.info("manager-selection operator msg — not sticking as build directive")
                if state.active_op_cmd and _MANAGER_RACE_RE.search(state.active_op_cmd):
                    state.active_op_cmd = None
                    state.active_op_seq = 0

        work_op = best_work_operator_command(ctx)
        op_cmd, operator_directive = resolve_op_cmd(
            state.active_op_cmd,
            latest_operator_command(ctx),
            work_cmd=work_op,
        )

        roster_due = roster_response_due(
            ctx,
            state.peer_manager,
            AGENT_NAME,
            roster_posted=state.roster_posted,
        )
        roster_closed = roster_collection_closed(ctx)
        claim_due = manager_open_claim_due(
            ctx,
            state.peer_manager,
            AGENT_NAME,
            claim_posted=state.claim_posted,
        )
        tr.record(
            "ROUTING",
            f"mentioned_me={mentioned_me} operator={operator_directive} "
            f"kickoff={is_broadcast_work_kickoff(op_cmd)} peer_mgr={state.peer_manager} "
            f"ctx_len={len(ctx)} roster_due={roster_due} roster_closed={roster_closed} "
            f"claim_due={claim_due}",
            (op_cmd or "")[:300],
        )

        # Clear sticky when peers report success AND required files exist on disk.
        if state.active_op_cmd and task_completed_heuristic(
            ctx, state.active_op_cmd, ag.WORKSPACE_DIR,
        ):
            log.info("task completed — clearing sticky operator directive")
            state.active_op_cmd = None
            state.active_op_seq = 0
            op_cmd = None
            operator_directive = False

        # Operator/grader directives skip stagger delay — UNLESS they ask agents to
        # coordinate/distribute roles first (racing causes duplicate files).
        _is_coordination = operator_directive and (
            _COORDINATION_RE.search(op_cmd or "")
            or _MANAGER_RACE_RE.search(op_cmd or "")
            or (
                is_broadcast_work_kickoff(op_cmd)
                and (
                    _ROLE_DISTRIBUTION_RE.search(op_cmd or "")
                    or _COORDINATION_RE.search(op_cmd or "")
                )
            )
        )
        if _is_coordination and not mentioned_me:
            log.info("coordination phase — keeping response delay")
            tr.record("WAIT", "coordination delay before respond")
        if operator_directive and not _is_coordination:
            log.info("operator directive — skipping response delay")
            external = _merge_rechecked_messages(state, external, log)
            ctx = routing_context(state, external)
            work_op = best_work_operator_command(ctx)
            op_cmd, operator_directive = resolve_op_cmd(
                state.active_op_cmd,
                latest_operator_command(ctx),
                work_cmd=work_op,
            )
            roster_due = roster_response_due(
                ctx,
                state.peer_manager,
                AGENT_NAME,
                roster_posted=state.roster_posted,
            )
            roster_closed = roster_collection_closed(ctx)
            claim_due = manager_open_claim_due(
                ctx,
                state.peer_manager,
                AGENT_NAME,
                claim_posted=state.claim_posted,
            )
        elif not mentioned_me and RESPONSE_DELAY > 0:
            jitter = random.uniform(0, RESPONSE_DELAY * 0.3)
            wait = RESPONSE_DELAY + jitter
            log.info("unaddressed task — waiting %.1fs before responding", wait)
            time.sleep(wait)
            external = _merge_rechecked_messages(state, external, log)
            ctx = routing_context(state, external)
            peer_mgr = resolve_peer_manager(ctx, AGENT_NAME)
            if peer_mgr:
                state.peer_manager = peer_mgr
            work_op = best_work_operator_command(ctx)
            op_cmd, operator_directive = resolve_op_cmd(
                state.active_op_cmd,
                latest_operator_command(ctx),
                work_cmd=work_op,
            )
            roster_due = roster_response_due(
                ctx,
                state.peer_manager,
                AGENT_NAME,
                roster_posted=state.roster_posted,
            )
            roster_closed = roster_collection_closed(ctx)
            claim_due = manager_open_claim_due(
                ctx,
                state.peer_manager,
                AGENT_NAME,
                claim_posted=state.claim_posted,
            )
            if operator_directive:
                log.info("operator directive detected after recheck — applying priority")

        # Circuit breaker — if we just ABORTed 2 times in a row, the LLM is stuck
        # in a promise/non-delivery loop that's burning tokens. Force PASS for one
        # round so the situation can evolve (new peer messages, file deliveries).
        if state.consecutive_aborts >= 2 and not mentioned_me:
            log.info(
                "circuit breaker — %d consecutive ABORTs, forcing PASS",
                state.consecutive_aborts,
            )
            tr.record("PASS", "circuit breaker after consecutive ABORTs")
            state.consecutive_aborts = 0  # reset; let the next turn try fresh
            time.sleep(POLL_INTERVAL)
            continue

        # STOP / silence — sticky until a human says continue (many phrasings).
        for _m in external:
            if not is_operator_agent(_m["agent_name"]):
                continue
            if is_human_stop_directive(_m["content"]):
                state.silence_active = True
                state.active_op_cmd = None
                state.active_op_seq = 0
                log.info("STOP/silence directive — clearing sticky operator cmd")
            elif is_human_resume_directive(_m["content"]):
                state.silence_active = False
                log.info("resume directive — lifting silence")
        if state.silence_active:
            log.info("PASS — silence/STOP active (sticky until resume)")
            tr.record("PASS", "silence/STOP active")
            time.sleep(POLL_INTERVAL)
            continue

        if roster_due and state.messages_sent < state.msg_cap:
            roster_reply = build_canned_roster_line(AGENT_NAME)
            try:
                hub.send_message(AGENT_NAME, roster_reply)
                state.messages_sent += 1
                state.roster_posted = True
                state.consecutive_aborts = 0
                log.info("SENT roster roll-call: %s", roster_reply[:120])
                tr.record("SENT", "solicited [ROSTER]", roster_reply[:300])
                time.sleep(POLL_INTERVAL * 2)
                continue
            except hub.RateLimitError as e:
                log.warning("roster send rate-limited: %s", e)
            except Exception as e:
                log.error("roster send error: %s", e)

        if claim_due and state.messages_sent < state.msg_cap:
            claim_reply = build_open_task_claim_line(
                ctx, state.peer_manager, AGENT_NAME,
            )
            try:
                hub.send_message(AGENT_NAME, claim_reply)
                state.messages_sent += 1
                state.claim_posted = True
                state.consecutive_aborts = 0
                log.info("SENT open-task claim: %s", claim_reply[:120])
                tr.record("SENT", "manager open [CLAIM]", claim_reply[:300])
                time.sleep(POLL_INTERVAL * 2)
                continue
            except hub.RateLimitError as e:
                log.warning("claim send rate-limited: %s", e)
            except Exception as e:
                log.error("claim send error: %s", e)

        # Another agent claimed manager — wait unless operator also said self-organize+build.
        if should_defer_to_peer_manager(
            ctx,
            op_cmd,
            state.peer_manager,
            AGENT_NAME,
            mentioned_me=mentioned_me,
            delegated=was_delegated_to_me(external, ctx=ctx),
            roster_posted=state.roster_posted,
            claim_posted=state.claim_posted,
        ):
            if development_frozen_by_manager(ctx, state.peer_manager):
                log.info("PASS — %s is manager; awaiting GO", state.peer_manager)
                tr.record("PASS", f"manager {state.peer_manager}; awaiting GO")
            elif roster_phase_active(ctx, state.peer_manager):
                log.info("PASS — %s is manager; roster-only phase", state.peer_manager)
                tr.record("PASS", f"manager {state.peer_manager}; roster phase")
            else:
                log.info(
                    "PASS — %s leads; need @%s or TASK-N",
                    state.peer_manager,
                    AGENT_NAME,
                )
                tr.record(
                    "PASS",
                    f"manager {state.peer_manager}; need @{AGENT_NAME} or TASK",
                )
            time.sleep(POLL_INTERVAL)
            continue
        if (
            state.peer_manager
            and state.peer_manager.lower() != AGENT_NAME.lower()
            and operator_self_organize_build(op_cmd)
        ):
            log.info(
                "self-organize build — %s is manager but workers may claim slices",
                state.peer_manager,
            )
            tr.record(
                "ROUTING",
                f"self-organize under manager {state.peer_manager}",
                (op_cmd or "")[:200],
            )

        peer_done = files_delivered_by_peers(ctx, AGENT_NAME)
        if peer_overlap_blocks_turn(op_cmd, peer_done, mentioned_me=mentioned_me):
            overlap = set(extract_required_filenames(op_cmd or "")) & peer_done
            log.info("PASS — peer already delivered %s", ", ".join(sorted(overlap)))
            tr.record("PASS", "peer overlap", ", ".join(sorted(overlap)))
            time.sleep(POLL_INTERVAL)
            continue

        delegated = was_delegated_to_me(external, ctx=ctx)
        active_prompt = build_active_prompt(
            system_prompt,
            external,
            operator_directive=operator_directive,
            op_cmd=op_cmd,
            mentioned_me=mentioned_me,
            peer_file_issues=state.peer_file_issues,
            pinned_memory=state.pinned_memory,
            private_steer=state.private_steer,
            peer_manager=state.peer_manager,
            ctx=ctx,
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
                tr.record("PASS", "all-social, no LLM")
                time.sleep(POLL_INTERVAL)
                continue

        log.info("→ calling LLM (history=%d entries)", len(history))
        tr.record("LLM", "calling", f"history={len(history)}")
        reply = ag.decide(external, AGENT_NAME, active_prompt, history, token_counter)
        log.info("← LLM reply: %s", reply[:120] if reply != "PASS" else "PASS")
        tr.record(
            "LLM",
            "reply PASS" if reply == "PASS" else "reply",
            reply[:800] if reply != "PASS" else "",
        )

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
                canned = "Acknowledged."
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

        # Capture files written THIS turn before retries — apply_send_quality_retries
        # calls ag.decide() repeatedly and each call resets _last_turn_written_files
        # to [], so by the time we check after retries the original list is gone.
        files_written_initial = list(ag.get_last_turn_written_files())

        # Detect Q&A: we're @mentioned AND any new message contains "?". For these
        # simple status questions, relax the non-delivery filter so a direct answer
        # like "No, I'm not asleep, I hit X" can pass.
        is_qa = mentioned_me and any("?" in m["content"] for m in external)

        reply = apply_send_quality_retries(
            reply, external, active_prompt, history, token_counter, soft_limit, log,
            is_question_response=is_qa,
        )

        # Merge files from initial decide() with anything written during retries.
        def _all_files_written_this_turn() -> list[str]:
            seen: set[str] = set()
            merged: list[str] = []
            for f in files_written_initial + ag.get_last_turn_written_files():
                if f and f not in seen:
                    seen.add(f)
                    merged.append(f)
            return merged

        # If send-quality retries gave up (PASS) but tools wrote files this turn,
        # paste the last written file directly — deterministic CODE TRANSFER.
        if reply == "PASS" and not soft_limit:
            written_this_turn = _all_files_written_this_turn()
            if written_this_turn:
                fname = written_this_turn[-1]
                fpath = Path(ag.WORKSPACE_DIR) / fname
                if fpath.exists():
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    lang = ag._LANG_BY_EXT.get(fpath.suffix.lstrip("."), "")
                    reply = ag.format_code_transfer(fname, content, lang)
                    log.info("CODE TRANSFER fallback — pasting `%s` programmatically", fname)

        # Safety net: if files were written this turn but aren't yet in the reply as
        # a proper code block → append them. agent.py _finish() handles the primary
        # path; this catches any edge cases that slip through (e.g. retries that
        # bypass _finish, or files not tracked by bash-redirect pattern).
        if reply != "PASS":
            written_this_turn = _all_files_written_this_turn()
            if written_this_turn:
                for fname in written_this_turn:
                    if f"Klar med: `{fname}`" in reply:
                        continue  # already included
                    fpath = Path(ag.WORKSPACE_DIR) / fname
                    if not fpath.exists():
                        continue
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    lang = ag._LANG_BY_EXT.get(fpath.suffix.lstrip("."), "")
                    reply = reply + ag.HUB_MSG_BREAK + ag.format_code_transfer(fname, content, lang)
                    log.info("CODE TRANSFER appended (safety net) — added `%s`", fname)

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

            nudge_op, _ = resolve_op_cmd(
                state.active_op_cmd,
                latest_operator_command(ctx),
                work_cmd=best_work_operator_command(ctx),
            )
            op_section = build_operator_prompt_section(nudge_op) if nudge_op else ""
            gap_section = (
                build_workspace_gap_section(
                    nudge_op, ag.WORKSPACE_DIR, external,
                    peer_file_issues=state.peer_file_issues,
                )
                if nudge_op else ""
            )

            nudge_prompt = active_prompt + op_section + gap_section + (
                f"\n\nWORKSPACE FILES RIGHT NOW:\n{ws_files}\n\n"
                f"Pick ONE concrete piece of work and execute it with your tools NOW. "
                f"PASS is FORBIDDEN here."
            )
            reply = ag.decide(external, AGENT_NAME, nudge_prompt, history, token_counter)
            log.info("← nudge reply: %s", reply[:120] if reply != "PASS" else "PASS")

        kickoff_cmd = op_cmd or state.active_op_cmd
        peer_mgr_blocks_kickoff = (
            state.peer_manager
            and state.peer_manager.lower() != AGENT_NAME.lower()
        )
        if (
            reply == "PASS"
            and not mentioned_me
            and operator_directive
            and is_broadcast_work_kickoff(kickoff_cmd)
            and not peer_mgr_blocks_kickoff
        ):
            reply = build_broadcast_kickoff_claim(
                kickoff_cmd, ctx, ag.WORKSPACE_DIR, AGENT_NAME,
            )
            log.info("kickoff fallback — broadcast claim sent")
            tr.record("FALLBACK", "broadcast kickoff claim", reply[:200])

        if reply == "PASS":
            log.info("PASS — sleeping %.1fs", POLL_INTERVAL)
            tr.record("PASS", "final — no hub post this turn")
            time.sleep(POLL_INTERVAL)
            continue

        if _BLOCKED_SELF_MANAGER_RE.search(reply):
            log.info("ABORT send — blocked manager/protocol self-post")
            tr.record("ABORT", "blocked manager/protocol self-post")
            time.sleep(POLL_INTERVAL)
            continue

        roster_solicited = roster_roll_call_requested(
            ctx, state.peer_manager,
        ) or state.roster_posted
        if is_unsolicited_roster_post(
            reply,
            mentioned_me=mentioned_me,
            delegated=delegated,
            solicited=roster_solicited,
        ):
            log.info("ABORT send — unsolicited ROSTER post")
            tr.record("ABORT", "unsolicited ROSTER")
            time.sleep(POLL_INTERVAL)
            continue

        peer_done = files_delivered_by_peers(ctx, AGENT_NAME)
        if would_duplicate_peer_delivery(reply, peer_done) and not mentioned_me:
            log.info("ABORT send — would duplicate peer-delivered file(s)")
            tr.record("ABORT", "duplicate peer file")
            time.sleep(POLL_INTERVAL)
            continue

        now_ts = time.time()
        autosum_age = now_ts - state.last_autosum_at
        if should_suppress_autosum(reply, state.last_autosum_text, autosum_age):
            log.info("suppressing duplicate auto-summary (%.0fs ago)", autosum_age)
            time.sleep(POLL_INTERVAL)
            continue

        if hub_reply_blocked(reply):
            # Q&A bypass: non-delivery rule shouldn't block direct answers to
            # questions. Promise filter still applies — we never want to send
            # "I will check later" as an answer.
            if is_qa and not has_disallowed_promise(reply):
                log.info("Q&A response — bypassing non-delivery filter")
            else:
                reason = "promises" if has_disallowed_promise(reply) else "non-delivery"
                state.consecutive_aborts += 1
                log.info(
                    "ABORT send — reply blocked (%s)  consecutive_aborts=%d",
                    reason, state.consecutive_aborts,
                )
                time.sleep(POLL_INTERVAL)
                continue

        # Split long messages instead of truncating (hub cap is 4096 server-side)
        chunks = split_for_hub(reply)

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
                state.consecutive_aborts = 0  # successful send breaks the abort streak
                if reply.startswith("[auto-summary]"):
                    state.last_autosum_text = reply
                    state.last_autosum_at = time.time()
                log.info(
                    "SENT (%d/%d)%s: %s",
                    state.messages_sent, state.msg_cap,
                    f" chunk {i+1}/{len(chunks)}" if len(chunks) > 1 else "",
                    chunk[:120],
                )
                tr.record("SENT", f"hub post {state.messages_sent}/{state.msg_cap}", chunk[:300])
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
