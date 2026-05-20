# =============================================================================
# RunPod Connection Helper
# =============================================================================
#
# SETUP — do these steps once before running:
#
#   1. Install dependencies:
#        pip install -r requirements.txt
#
#   2. Create your .env file (copy from the example):
#        cp .env.example .env
#
#   3. Fill in the two RunPod values inside .env:
#
#        RUNPOD_API_KEY   — from https://www.runpod.io > Settings > API Keys
#        RUNPOD_POD_ID    — from your Pods page on the RunPod dashboard
#
#      NEVER commit .env to git — it is already listed in .dockerignore / .gitignore.
#
#   4. Add your SSH public key on RunPod so you can actually connect:
#        RunPod dashboard > Settings > SSH Keys > Add SSH Key
#        (paste the contents of ~/.ssh/id_rsa.pub or your preferred key)
#
#   5. Run:
#        python runpod_connect.py
#
#      The script will print the exact SSH command — copy it and paste it into
#      your terminal to open a shell on the pod.
#
# =============================================================================

import os
import sys
import time

import runpod
from dotenv import load_dotenv

# =============================================================================
# LOAD ENVIRONMENT VARIABLES from .env (must live alongside this file)
# =============================================================================

load_dotenv()  # reads part_2/.env into os.environ — never hard-code secrets

# =============================================================================
# VALIDATE required env vars — fail fast with a clear message if any are missing
# =============================================================================

_REQUIRED = {
    "RUNPOD_API_KEY": "Your RunPod API key  (runpod.io > Settings > API Keys)",
    "RUNPOD_POD_ID":  "Your pod ID          (visible on the RunPod Pods page)",
}

_missing = [f"  {var}  — {desc}" for var, desc in _REQUIRED.items() if not os.getenv(var)]
if _missing:
    print("ERROR: The following required variables are missing from your .env file:\n")
    print("\n".join(_missing))
    print("\nCopy .env.example to .env and fill in the values.")
    sys.exit(1)

# Pull values from the environment — credentials never appear in source code
API_KEY = os.environ["RUNPOD_API_KEY"]
POD_ID  = os.environ["RUNPOD_POD_ID"]

# =============================================================================
# INITIALISE the RunPod SDK with the key loaded from .env
# =============================================================================

runpod.api_key = API_KEY


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_pod_status(pod_id: str) -> dict:
    """
    Fetch the current status of a pod.
    Returns a dict with pod details — the most useful fields are:
      - desiredStatus : "RUNNING" | "EXITED" | "TERMINATED"
      - runtime       : present only when the pod is active (contains port info)
      - name          : human-readable pod name
    """
    return runpod.get_pod(pod_id)


def start_pod(pod_id: str) -> dict:
    """
    Resume a pod that is currently stopped/exited.
    Billing starts once the pod reaches RUNNING status.
    """
    return runpod.resume_pod(pod_id)


def stop_pod(pod_id: str) -> dict:
    """
    Stop (pause) a running pod to halt billing.
    Volume data is preserved; resume later with start_pod().
    """
    return runpod.stop_pod(pod_id)


def wait_until_running(pod_id: str, timeout: int = 120, poll_interval: int = 5) -> bool:
    """
    Poll pod status every `poll_interval` seconds until it is RUNNING
    or `timeout` seconds have elapsed.

    Args:
        pod_id:        ID of the pod to monitor.
        timeout:       Maximum seconds to wait before giving up (default: 120).
        poll_interval: Seconds between status checks (default: 5).

    Returns:
        True  — pod reached RUNNING within the timeout.
        False — timed out before the pod became ready.
    """
    elapsed = 0
    print(f"Waiting for pod {pod_id} to reach RUNNING status...")

    while elapsed < timeout:
        pod    = get_pod_status(pod_id)
        status = pod.get("desiredStatus", "UNKNOWN")
        print(f"  [{elapsed:>3}s] Status: {status}")

        if status == "RUNNING":
            print("✓ Pod is RUNNING.")
            return True

        time.sleep(poll_interval)
        elapsed += poll_interval

    print(f"✗ Timed out after {timeout}s. Pod did not reach RUNNING.")
    return False


def get_ssh_command(pod_id: str) -> str:
    """
    Build the SSH command string needed to connect to a running pod.

    RunPod maps the container's port 22 to a random public port on an
    external IP — this function looks that mapping up automatically.

    Returns:
        A ready-to-run SSH command string if the pod is up and port 22 is
        exposed, or a descriptive error message otherwise.
    """
    pod = get_pod_status(pod_id)

    runtime = pod.get("runtime")
    if not runtime:
        return (
            "Pod is not running — start it first with start_pod(), "
            "then wait for RUNNING status."
        )

    # Scan the port mappings for the SSH port (private port 22)
    for port_info in runtime.get("ports", []):
        if port_info.get("privatePort") == 22:
            ip          = port_info.get("ip")
            public_port = port_info.get("publicPort")
            # Uses your default private key; change -i if yours is elsewhere
            return f"ssh root@{ip} -p {public_port} -i ~/.ssh/id_rsa"

    return (
        "SSH port (22) not found in the port mappings. "
        "Make sure your pod template exposes TCP port 22."
    )


# =============================================================================
# MAIN — standard connect workflow
# =============================================================================

if __name__ == "__main__":

    # -------------------------------------------------------------------------
    # STEP 1 — Check current pod status
    # -------------------------------------------------------------------------
    print("=== Pod Status ===")
    pod_info       = get_pod_status(POD_ID)
    current_status = pod_info.get("desiredStatus", "UNKNOWN")
    print(f"  Pod ID : {POD_ID}")
    print(f"  Status : {current_status}")

    # -------------------------------------------------------------------------
    # STEP 2 — Start the pod if it is not already running
    # -------------------------------------------------------------------------
    if current_status != "RUNNING":
        print("\n=== Starting Pod ===")
        start_pod(POD_ID)
        is_running = wait_until_running(POD_ID)
        if not is_running:
            print("\nPod failed to start within the timeout.")
            print("Check the RunPod dashboard for details.")
            sys.exit(1)

    # -------------------------------------------------------------------------
    # STEP 3 — Print the SSH command to connect
    # -------------------------------------------------------------------------
    print("\n=== SSH Connection Command ===")
    ssh_cmd = get_ssh_command(POD_ID)
    print(f"\n  {ssh_cmd}\n")
    print("Copy the command above and paste it into your terminal to connect.")

    # -------------------------------------------------------------------------
    # OPTIONAL — stop the pod when you are done to avoid unnecessary billing.
    # Uncomment the three lines below and re-run, or call stop_pod() manually.
    # -------------------------------------------------------------------------
    # print("\n=== Stopping Pod ===")
    # stop_pod(POD_ID)
    # print("Pod stopped. Billing has ended.")
