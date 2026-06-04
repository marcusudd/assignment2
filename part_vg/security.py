"""
Security guard — adapted from part_3/agent.py.
All checks run BEFORE execution (VG.4).
"""
import re
from pathlib import Path

# Note: rm / rmdir / unlink are intentionally NOT here. Deletion inside the
# workspace is allowed by policy; staying inside it is enforced by the
# parent-traversal and external-path checks below, not by banning the command.
_BLOCKED: list[tuple[str, str]] = [
    (r"\bdd\b", "dd command"),
    (r"\bmkfs\b", "filesystem format"),
    (r"(?<!2)>\s*/dev/(?!null)", "write to device"),
    (r":\s*\(\s*\)\s*\{", "fork bomb"),
    (r"\bsudo\b", "sudo"),
    (r"\bsu\b(?:\s|$)", "su"),
    (r"\b(?:pkexec|doas|run0)\b", "privilege escalation"),
    (r"\b(?:shutdown|reboot|halt|poweroff)\b", "system power command"),
    (r"(?:curl|wget)\b.*\|\s*(?:ba)?sh", "remote code execution"),
    (r"\|\s*(?:ba)?sh\b", "pipe to shell interpreter"),
    (r"\|\s*python[23]?\b", "pipe to python interpreter"),
    (r"(?:curl|wget)\b.*>\s*\S+\.sh\b", "downloading shell scripts"),
    (r"\bnc\b(?:\s|$)|\bnetcat\b", "netcat"),
    (r"(?:cat|less|head|tail|more)\b.*\.env\b", "reading secrets file"),
    (r"\benv\b(?:\s|$)", "environment variable dump"),
    (r"\bprintenv\b", "environment variable dump"),
    (
        r"\$\{?(?:OPENROUTER_API_KEY|ANTHROPIC_API_KEY|API_KEY|SECRET|PASSWORD|TOKEN|PRIVATE_KEY)\}?",
        "secret variable expansion",
    ),
    (r"\$\{?(?:HOME|OLDPWD)\}?", "home/external directory variable"),
    (r"(?:^|\s|['\"`])~[/\s~]|(?:^|\s|['\"`])~$", "home directory access"),
]

_ALLOWED_ABS_PREFIXES: tuple[str, ...] = (
    "/usr/",
    "/bin/",
    "/sbin/",
    "/lib/",
    "/opt/",
    "/dev/null",
)


def _strip_heredoc(command: str) -> str:
    """Strip heredoc bodies before pattern scanning — code inside heredocs
    (JS/Python with && / || etc.) would otherwise trigger false positives."""
    return re.split(r"<<-?\s*['\"]?\w+['\"]?", command, maxsplit=1)[0]


def _strip_quoted_strings(command: str) -> str:
    """Replace quoted regions so shell-level ; / & scans ignore python -c bodies."""
    out: list[str] = []
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if ch not in "'\"":
            out.append(ch)
            i += 1
            continue
        quote = ch
        j = i + 1
        while j < n:
            if command[j] == "\\" and quote == "\"":
                j += 2
                continue
            if command[j] == quote:
                break
            j += 1
        out.append(" " * (j - i + 1))
        i = j + 1 if j < n else n
    return "".join(out)


def _shell_separator_blocked(command: str) -> str | None:
    """Block shell-level ; and background & — allow |, &&, ||, 2>&1, &>."""
    head = _strip_quoted_strings(_strip_heredoc(command))
    if ";" in head:
        return "shell command separator"
    cleaned = re.sub(r"\d*>&\d*|&>", " ", head)
    if re.search(r"(?<![&])&(?![&])", cleaned):
        return "background execution"
    return None


def _has_parent_traversal(command: str) -> bool:
    """Block `..` path segments. Bash runs with cwd = workspace, so any parent
    reference escapes it. Quotes are deliberately NOT stripped, so `rm "../x"`
    is caught too."""
    return re.search(r"""(?:^|[\s=:/'"])\.\.(?:[/\s'"]|$)""", command) is not None


def _has_external_path(command: str, workspace_dir: str) -> bool:
    workspace = str(Path(workspace_dir).resolve())
    head = _strip_heredoc(command)
    # `*` (not `+`) so a bare "/" (root) is caught, e.g. `rm -rf /`.
    for m in re.finditer(r'(?:^|\s|[\'"`])(\/[^\s\'"`|&;,<>]*)', head):
        path = m.group(1)
        if path.startswith(workspace):
            continue
        if any(path.startswith(p) for p in _ALLOWED_ABS_PREFIXES):
            continue
        return True
    return False


def security_check(command: str, workspace_dir: str) -> str | None:
    """Return a rejection reason if the command should be blocked, else None.

    Policy: the agent may freely create/edit/delete inside the workspace, but
    must never reach outside it — no `..` traversal, no absolute paths outside
    the workspace.
    """
    sep = _shell_separator_blocked(command)
    if sep:
        return sep
    head = _strip_heredoc(command)
    if _has_parent_traversal(head):
        return "parent-directory traversal (.. escapes the workspace)"
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
