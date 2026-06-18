"""The POC incident graph: triage -> investigate -> diagnose -> propose.

Linear and read only. investigate calls the fleet-readonly MCP server over stdio via the
official langchain-mcp-adapters bridge. No writes, no remediation is executed.
"""
import os
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.core.llm_client import get_chat_model
from app.core.pgvector_store import hybrid_search
from app.graph.state import IncidentState

# repo root = build.py -> graph -> app -> backend -> root
ROOT = Path(__file__).resolve().parents[3]


def _mcp_client() -> MultiServerMCPClient:
    """Spawn the fleet-readonly MCP server as a stdio subprocess."""
    return MultiServerMCPClient(
        {
            "fleet": {
                "command": sys.executable,
                "args": ["-m", "mcp_servers.fleet_readonly.server"],
                "transport": "stdio",
                "cwd": str(ROOT),
                "env": {**os.environ, "PYTHONPATH": str(ROOT)},
            }
        }
    )


class Triage(BaseModel):
    incident_type: str = Field(
        description="service_down, high_cpu, high_memory, disk_full, error_spike, network, or unknown"
    )
    target_service: str = Field(description="affected service name, or 'unknown'")
    severity: str = Field(description="sev1, sev2, or sev3")


async def build_graph():
    tools = await _mcp_client().get_tools()
    by_name = {t.name: t for t in tools}

    async def triage(state: IncidentState) -> dict:
        # DeepSeek does not support the json_schema response format, so use tool calling.
        model = get_chat_model("chat").with_structured_output(Triage, method="function_calling")
        r = await model.ainvoke(
            [
                SystemMessage(
                    content="You are an SRE triage assistant. Classify the incident from the alert. Use 'unknown' when unsure."
                ),
                HumanMessage(content=state["trigger"]),
            ]
        )
        return {
            "incident_type": r.incident_type,
            "target_service": r.target_service,
            "severity": r.severity,
        }

    async def investigate(state: IncidentState) -> dict:
        calls = [("list_failed_services", {}), ("disk_usage", {}), ("memory_usage", {})]
        svc = state.get("target_service", "unknown")
        if svc and svc != "unknown":
            calls.insert(0, ("service_status", {"service": svc}))
            calls.append(("tail_log", {"service": svc, "lines": 30}))
        chunks = []
        for name, args in calls:
            tool = by_name.get(name)
            if tool is None:
                continue
            out = await tool.ainvoke(args)
            chunks.append(f"### {name}({args})\n{out}")
        return {"evidence": "\n\n".join(chunks)}

    async def diagnose(state: IncidentState) -> dict:
        # RAG: retrieve relevant runbooks to ground the diagnosis.
        query = f"{state['trigger']} {state.get('incident_type', '')} {state.get('target_service', '')}"
        try:
            books = hybrid_search(query)
        except Exception:
            books = []
        rb_text = "\n\n".join(f"[{b['title']}]\n{b['text']}" for b in books) or "(no runbooks found)"
        model = get_chat_model("reasoner")
        r = await model.ainvoke(
            [
                SystemMessage(
                    content="You are an SRE. From the alert, evidence, and retrieved runbooks, state the single "
                    "most likely root cause and a confidence of low, medium, or high. Add a 'Runbook:' line "
                    "naming the runbook you relied on, if any. Be concise."
                ),
                HumanMessage(
                    content=f"ALERT:\n{state['trigger']}\n\nEVIDENCE:\n{state['evidence']}\n\nRUNBOOKS:\n{rb_text}"
                ),
            ]
        )
        return {"diagnosis": r.content, "runbooks": list(dict.fromkeys(b["title"] for b in books))}

    async def propose(state: IncidentState) -> dict:
        model = get_chat_model("chat")
        r = await model.ainvoke(
            [
                SystemMessage(
                    content="Propose remediation steps for the diagnosed issue. Do NOT execute anything. For each step give the command and tag it risk=read|write|destructive and reversible=yes|no. Keep it short."
                ),
                HumanMessage(content=f"DIAGNOSIS:\n{state['diagnosis']}"),
            ]
        )
        return {"proposed_fix": r.content}

    g = StateGraph(IncidentState)
    g.add_node("triage", triage)
    g.add_node("investigate", investigate)
    g.add_node("diagnose", diagnose)
    g.add_node("propose", propose)
    g.add_edge(START, "triage")
    g.add_edge("triage", "investigate")
    g.add_edge("investigate", "diagnose")
    g.add_edge("diagnose", "propose")
    g.add_edge("propose", END)
    return g.compile()


async def run(trigger: str) -> dict:
    graph = await build_graph()
    return await graph.ainvoke({"trigger": trigger})
