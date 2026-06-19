"""Run read only commands on the fleet via the EC2 Instance Connect SSH helper.

The helper (connect-ec2.sh) pushes a temporary key, resolves the current IP, and SSHes in.
We never read the PEM here; the helper owns that.
"""
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
_HELPER = os.getenv("FLEET_SSH_HELPER", "")


def run_sandbox(command: str, timeout: int = 45) -> dict:
    """Run a command on the disposable sandbox EC2 (writes allowed here).

    Resolves the instance public IP each call so it survives stop/start, then SSHes
    directly with the PEM (the sandbox uses the oggagan key pair).
    """
    iid = os.getenv("SANDBOX_INSTANCE_ID", "")
    pem = os.getenv("SANDBOX_PEM", "")
    region = os.getenv("AWS_REGION", "ap-south-1")
    user = os.getenv("SANDBOX_SSH_USER", "ubuntu")
    awscli = os.getenv("AWS_CLI") or str(Path.home() / ".local" / "bin" / "aws")
    if not iid or not Path(pem).exists():
        return {"ok": False, "stdout": "", "stderr": "sandbox not configured", "code": -1}
    try:
        ip = subprocess.run(
            [awscli, "ec2", "describe-instances", "--region", region, "--instance-ids", iid,
             "--query", "Reservations[0].Instances[0].PublicIpAddress", "--output", "text"],
            capture_output=True, text=True, timeout=25,
        ).stdout.strip()
        if not ip or ip == "None":
            return {"ok": False, "stdout": "", "stderr": "sandbox is not running", "code": -1}
        p = subprocess.run(
            ["ssh", "-i", pem, "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15",
             f"{user}@{ip}", command],
            capture_output=True, text=True, timeout=timeout,
        )
        return {"ok": p.returncode == 0, "stdout": p.stdout.strip(), "stderr": p.stderr.strip(), "code": p.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"timeout after {timeout}s", "code": -1}


def run_target(command: str, timeout: int = 45) -> dict:
    """Read from whichever target is configured: sandbox (default) or prod.

    The closed remediation loop runs against the sandbox; flip FLEET_READ_TARGET=prod
    for the read only diagnosis demo on the production fleet.
    """
    target = os.getenv("FLEET_READ_TARGET", "sandbox")
    return run_sandbox(command, timeout) if target == "sandbox" else run_remote(command, timeout)


def run_remote(command: str, timeout: int = 45) -> dict:
    """Execute one command on the prod fleet host via the SSH helper, returning structured output."""
    if not _HELPER or not Path(_HELPER).exists():
        return {"ok": False, "stdout": "", "stderr": f"ssh helper not found: {_HELPER}", "code": -1}
    try:
        p = subprocess.run(
            [_HELPER, command], capture_output=True, text=True, timeout=timeout
        )
        return {
            "ok": p.returncode == 0,
            "stdout": p.stdout.strip(),
            "stderr": p.stderr.strip(),
            "code": p.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"timeout after {timeout}s", "code": -1}
