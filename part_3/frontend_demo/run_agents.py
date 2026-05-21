"""
Multi-agent demo launcher.
Starts several agent instances that connect to the local mock hub and talk to each other.

Usage:
    # Terminal 1 — start the hub first
    python frontend_demo/mock_hub.py

    # Terminal 2 — launch agents
    python frontend_demo/run_agents.py

    # Open browser: http://localhost:8080
"""

import os
import subprocess
import sys
import threading
import signal
from pathlib import Path

# ---------------------------------------------------------------------------
# Agent configurations — tweak freely
# ---------------------------------------------------------------------------
AGENTS = [
    {
        "name": "mini_me1",
        "persona": "You are a software engineer who writes code and gets things done.",
        "msg_cap": "8",
        "token_cap": "30000",
        "response_delay": "1",   # lowest delay → first to act on unaddressed tasks
    },
    {
        "name": "mini_me2",
        "persona": "You are a software engineer who writes code and gets things done.",
        "msg_cap": "8",
        "token_cap": "30000",
        "response_delay": "5",   # sees mini_me1's work before deciding what to add
    },
    {
        "name": "mini_me3",
        "persona": "You are a software engineer who writes code and gets things done.",
        "msg_cap": "8",
        "token_cap": "30000",
        "response_delay": "9",   # sees both, fills remaining gaps
    },
]

# ---------------------------------------------------------------------------
# ANSI colors for terminal output
# ---------------------------------------------------------------------------
COLORS = ["\033[94m", "\033[92m", "\033[93m", "\033[95m", "\033[96m"]
RESET = "\033[0m"

# Path to the part_3 directory (parent of frontend_demo/)
PART3_DIR = Path(__file__).parent.parent.resolve()

# Prefer the local venv Python (has all deps); fall back to sys.executable
_venv_python = PART3_DIR / ".venv" / "bin" / "python"
PYTHON = str(_venv_python) if _venv_python.exists() else sys.executable

processes: list[subprocess.Popen] = []


def stream_output(proc: subprocess.Popen, prefix: str, color: str) -> None:
    """Read stdout from a subprocess and print with colored prefix."""
    for line in proc.stdout:
        print(f"{color}[{prefix}]{RESET} {line}", end="")
    print(f"{color}[{prefix}]{RESET} process ended")


def launch_agent(cfg: dict, color: str) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({
        "AGENT_NAME": cfg["name"],
        "AGENT_PERSONA": cfg["persona"],
        "MSG_CAP": cfg["msg_cap"],
        "TOKEN_CAP": cfg["token_cap"],
        "HUB_URL": "http://localhost:8080",
        "HUB_PASSWORD": "th25-agents-vg",
        "DRY_RUN": "false",
        "AUTO_APPROVE": "true",
        "POLL_INTERVAL": "5",
        "WORKSPACE_DIR": str(PART3_DIR / "workspace"),
        "RESPONSE_DELAY": cfg.get("response_delay", "0"),
        "MODEL": env.get("MODEL", "openai/gpt-4o-mini"),
    })

    proc = subprocess.Popen(
        [PYTHON, str(PART3_DIR / "main.py")],
        env=env,
        cwd=str(PART3_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    t = threading.Thread(target=stream_output, args=(proc, cfg["name"], color), daemon=True)
    t.start()
    return proc


def stop_all(signum=None, frame=None) -> None:
    print("\n\nStopping all agents…")
    for p in processes:
        p.terminate()
    for p in processes:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    print("Done.")
    sys.exit(0)


if __name__ == "__main__":
    # Load .env from part_3/ if it exists
    env_file = PART3_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    if not os.getenv("OPENROUTER_API_KEY"):
        print("ERROR: OPENROUTER_API_KEY is not set.")
        print("Set it in your environment or .env file in part_3/")
        sys.exit(1)

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    print("=" * 60)
    print("  Multi-Agent Demo")
    print(f"  Hub:    http://localhost:8080")
    print(f"  Agents: {', '.join(a['name'] for a in AGENTS)}")
    print("  Ctrl-C to stop all")
    print("=" * 60)
    print()

    for i, cfg in enumerate(AGENTS):
        color = COLORS[i % len(COLORS)]
        proc = launch_agent(cfg, color)
        processes.append(proc)
        print(f"{color}[{cfg['name']}]{RESET} started (pid {proc.pid})")

    print("\nOpen http://localhost:8080 in your browser to watch the conversation.\n")

    # Wait for all processes to finish
    for p in processes:
        p.wait()

    print("All agents finished.")
