"""
Security guard — adapted from part_3/agent.py.
All checks run BEFORE execution (VG.4).
"""
import re
from pathlib import Path

_BLOCKED: list[tuple[str, str]] = [
    (r"(?:^|[^|&])(&&|\|\||;|&|\|)(?:[^|&]|$)", "command chaining"),
    (r"\brm\b.*-[rRfF]", "recursive/force delete"),
    (r"\bdd\b", "dd command"),
    (r"\bmkfs\b", "filesystem format"),
    (r">\s*/dev/", "write to device"),
    (r":\s*\(\s*\)\s*\{", "fork bomb"),
    (r"\bsudo\b", "sudo"),
    (r"\bsu\b(?:\s|$)", "su"),
    (r"\b(?:pkexec|doas|run0)\b", "privilege escalation"),
    (r"\b(?:shutdown|reboot|halt|poweroff)\b", "system power command"),
    (r"(?:curl|wget)\b.*\|\s*(?:ba)?sh", "remote code execution"),
    (r"(?:curl|wget)\b.*>\s*\S+\.sh\b", "downloading shell scripts"),
    (r"\bnc\b(?:\s|$)|\bnetcat\b", "netcat"),
    (r"(?:cat|less|head|tail|more)\b.*\.env\b", "reading secrets file"),
    (r"\benv\b(?:\s|$)", "environment variable dump"),
    (r"\bprintenv\b", "environment variable dump"),
    (
        r"\$\{?(?:OPENROUTER_API_KEY|ANTHROPIC_API_KEY|API_KEY|SECRET|PASSWORD|TOKEN|PRIVATE_KEY)\}?",
        "secret variable expansion",
    ),
    (r"(?:^|\s|['\"`])~[/\s~]|(?:^|\s|['\"`])~$", "home directory access"),
]

_ALLOWED_ABS_PREFIXES: tuple[str, ...] = (
    "/usr/",
    "/bin/",
    "/sbin/",
    "/lib/",
    "/opt/",
    "/tmp/",
    "/dev/null",
)


def _strip_heredoc(command: str) -> str:
    """Strip heredoc bodies before pattern scanning — code inside heredocs
    (JS/Python with && / || etc.) would otherwise trigger false positives."""
    return re.split(r"<<-?\s*['\"]?\w+['\"]?", command, maxsplit=1)[0]


def _has_external_path(command: str, workspace_dir: str) -> bool:
    workspace = str(Path(workspace_dir).resolve())
    head = _strip_heredoc(command)
    for m in re.finditer(r'(?:^|\s|[\'"`])(\/[^\s\'"`|&;,<>]+)', head):
        path = m.group(1)
        if path.startswith(workspace):
            continue
        if any(path.startswith(p) for p in _ALLOWED_ABS_PREFIXES):
            continue
        return True
    return False


def security_check(command: str, workspace_dir: str) -> str | None:
    """Return a rejection reason if the command should be blocked, else None."""
    head = _strip_heredoc(command)
    for pattern, reason in _BLOCKED:
        if re.search(pattern, head, re.IGNORECASE):
            return reason
    if _has_external_path(command, workspace_dir):
        return "absolute path outside workspace — use relative paths"
    return None


def resolve_path(rel_path: str, workspace_dir: str) -> Path | None:
    """Resolve rel_path inside workspace. Returns None on path traversal."""
    workspace = Path(workspace_dir).resolve()
    target = (workspace / rel_path).resolve()
    if not str(target).startswith(str(workspace)):
        return None
    return target
