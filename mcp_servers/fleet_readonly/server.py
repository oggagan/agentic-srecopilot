"""Fleet read only MCP server.

Exposes a fixed set of safe, read only diagnostics. Every tool maps to a hardcoded command;
user supplied arguments are validated, never interpolated as shell. No write actions live here.
"""
import re

from fastmcp import FastMCP

from mcp_servers.common.ssh import run_target

mcp = FastMCP("fleet-readonly")

_SERVICE_RE = re.compile(r"^[A-Za-z0-9._@-]+$")


def _svc(service: str) -> str | None:
    return service if _SERVICE_RE.match(service or "") else None


def _fmt(result: dict) -> str:
    if result["ok"]:
        return result["stdout"] or "(no output)"
    return f"ERROR (code {result['code']}): {result['stderr'] or result['stdout']}"


@mcp.tool
def service_status(service: str) -> str:
    """Show systemd status for a service, for example fuelroute or veridoc or nginx."""
    s = _svc(service)
    if not s:
        return "invalid service name"
    return _fmt(run_target(f"systemctl status {s} --no-pager -l | head -40"))


@mcp.tool
def list_failed_services() -> str:
    """List systemd services currently in a failed state."""
    out = run_target("systemctl list-units --type=service --state=failed --no-pager --no-legend")
    return _fmt(out) if out["stdout"] else "no failed services"


@mcp.tool
def tail_log(service: str, lines: int = 50) -> str:
    """Show the last N journald log lines for a service (default 50, capped at 200)."""
    s = _svc(service)
    if not s:
        return "invalid service name"
    n = max(1, min(int(lines), 200))
    return _fmt(run_target(f"sudo journalctl -u {s} -n {n} --no-pager"))


@mcp.tool
def disk_usage() -> str:
    """Show filesystem disk usage (df -h)."""
    return _fmt(run_target("df -h"))


@mcp.tool
def memory_usage() -> str:
    """Show memory usage (free -h)."""
    return _fmt(run_target("free -h"))


@mcp.tool
def cpu_load() -> str:
    """Show load average and the top CPU and memory consuming processes."""
    return _fmt(run_target("uptime; echo '---'; ps -eo pcpu,pmem,comm --sort=-pcpu | head -8"))


@mcp.tool
def check_port(port: int) -> str:
    """Check whether a TCP port is listening, for example 80 or 8020 or 5432."""
    p = int(port)
    if not (1 <= p <= 65535):
        return "invalid port"
    return _fmt(run_target(f"sudo ss -tlnp 2>/dev/null | grep ':{p} ' || echo 'port {p} not listening'"))


@mcp.tool
def nginx_test() -> str:
    """Validate the nginx configuration (nginx -t)."""
    return _fmt(run_target("sudo nginx -t 2>&1"))


@mcp.tool
def docker_ps() -> str:
    """List running docker containers and their status."""
    return _fmt(run_target("sudo docker ps --format '{{.Names}}\\t{{.Status}}'"))


if __name__ == "__main__":
    mcp.run(show_banner=False)
