"""Runbooks MCP server: semantic + keyword search over the pgvector runbook store.

Standalone tool so any agent can query runbooks. The graph's diagnose node calls the same
hybrid_search in process for speed; this server exposes it over MCP for completeness.
Run: PYTHONPATH=.:backend python -m mcp_servers.runbooks.server
"""
from fastmcp import FastMCP

from app.core.pgvector_store import hybrid_search

mcp = FastMCP("runbooks")


@mcp.tool
def search_runbooks(query: str, k: int = 5) -> str:
    """Search runbooks and past incidents for remediation guidance relevant to the query."""
    results = hybrid_search(query, k)
    if not results:
        return "no matching runbooks"
    return "\n\n".join(f"[{r['title']}] (score {r['score']})\n{r['text']}" for r in results)


if __name__ == "__main__":
    mcp.run(show_banner=False)
