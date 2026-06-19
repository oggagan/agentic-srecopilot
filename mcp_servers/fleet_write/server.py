"""Fleet write MCP server: state changing remediation, SANDBOX ONLY.

Every tool requires a valid approval token (minted only by the execute node after the
human approval gate) and runs exclusively against the disposable sandbox via run_sandbox.
There is no path here that can touch production.
"""
import re

from fastmcp import FastMCP

from mcp_servers.common.approval import check_token
from mcp_servers.common.ssh import run_sandbox

mcp = FastMCP("fleet-write")

_SERVICE_RE = re.compile(r"^[A-Za-z0-9._@-]+$")


def _guard(service: str, approval_token: str) -> str | None:
    if not check_token(approval_token):
        return "DENIED: invalid or missing approval token"
    if not _SERVICE_RE.match(service or ""):
        return "DENIED: invalid service name"
    return None


@mcp.tool
def restart_service(service: str, approval_token: str) -> str:
    """Restart a systemd service on the SANDBOX. Requires a valid approval token."""
    err = _guard(service, approval_token)
    if err:
        return err
    r = run_sandbox(f"sudo systemctl restart {service}; sleep 1; systemctl is-active {service}")
    return f"restart {service} -> {r['stdout'] or r['stderr']}"


@mcp.tool
def start_service(service: str, approval_token: str) -> str:
    """Start a systemd service on the SANDBOX. Requires a valid approval token."""
    err = _guard(service, approval_token)
    if err:
        return err
    r = run_sandbox(f"sudo systemctl start {service}; sleep 1; systemctl is-active {service}")
    return f"start {service} -> {r['stdout'] or r['stderr']}"


if __name__ == "__main__":
    mcp.run(show_banner=False)
