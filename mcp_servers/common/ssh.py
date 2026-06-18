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


def run_remote(command: str, timeout: int = 45) -> dict:
    """Execute one command on the fleet host, returning structured output."""
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
