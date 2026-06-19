"""The POC incident graph: triage -> investigate -> diagnose -> propose.

Linear and read only. investigate calls the fleet-readonly MCP server over stdio via the
official langchain-mcp-adapters bridge. No writes, no remediation is executed.
"""
import os
import sys
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.core.approval import expected_token
from app.core.llm_client import get_chat_model
from app.core.pgvector_store import hybrid_search
from app.graph.state import IncidentState

# repo root = build.py -> graph -> app -> backend -> root
ROOT = Path(__file__).resolve().parents[3]


def _text(out) -> str:
    """Coerce an MCP tool result (string or list of content blocks) to plain text."""
    if isinstance(out, str):
        return out
    if isinstance(out, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in out)
    return str(out)


def _mcp_client() -> MultiServerMCPClient:
    """Spawn the fleet-readonly MCP server as a stdio subprocess."""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return MultiServerMCPClient(
        {
            "fleet": {
                "command": sys.executable,
                "args": ["-m", "mcp_servers.fleet_readonly.server"],
                "transport": "stdio",
                "cwd": str(ROOT),
                "env": env,
            },
            "fleet_write": {
                "command": sys.executable,
                "args": ["-m", "mcp_servers.fleet_write.server"],
                "transport": "stdio",
                "cwd": str(ROOT),
                "env": env,
            },
        }
    )


class Triage(BaseModel):
    incident_type: str = Field(
        description="service_down, high_cpu, high_memory, disk_full, error_spike, network, or unknown"
    )
    target_service: str = Field(description="affected service name, or 'unknown'")
    severity: str = Field(description="sev1, sev2, or sev3")


async def build_graph(checkpointer=None):
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
            "started_at": time.time(),
        }

    async def _run_tools(calls: list[tuple[str, dict]]) -> str:
        chunks = []
        for name, args in calls:
            tool = by_name.get(name)
            if tool is None:
                continue
            out = await tool.ainvoke(args)
            chunks.append(f"### {name}({args})\n{_text(out)}")
        return "\n\n".join(chunks)

    # Three investigators that fan out from triage and run concurrently.
    async def investigate_services(state: IncidentState) -> dict:
        svc = state.get("target_service", "unknown")
        calls: list[tuple[str, dict]] = [("list_failed_services", {})]
        if svc and svc != "unknown":
            calls.insert(0, ("service_status", {"service": svc}))
        return {"findings": [{"source": "services", "summary": await _run_tools(calls)}]}

    async def investigate_metrics(state: IncidentState) -> dict:
        summary = await _run_tools([("disk_usage", {}), ("memory_usage", {}), ("cpu_load", {})])
        return {"findings": [{"source": "metrics", "summary": summary}]}

    async def investigate_logs(state: IncidentState) -> dict:
        svc = state.get("target_service", "unknown")
        if not svc or svc == "unknown":
            return {"findings": [{"source": "logs", "summary": "(no target service identified)"}]}
        summary = await _run_tools([("tail_log", {"service": svc, "lines": 30})])
        return {"findings": [{"source": "logs", "summary": summary}]}

    async def diagnose(state: IncidentState) -> dict:
        # RAG: retrieve relevant runbooks to ground the diagnosis.
        query = f"{state['trigger']} {state.get('incident_type', '')} {state.get('target_service', '')}"
        try:
            books = hybrid_search(query)
        except Exception:
            books = []
        rb_text = "\n\n".join(f"[{b['title']}]\n{b['text']}" for b in books) or "(no runbooks found)"
        evidence = "\n\n".join(
            f"## {f['source']}\n{f['summary']}" for f in state.get("findings", [])
        ) or "(no evidence gathered)"
        model = get_chat_model("reasoner")
        r = await model.ainvoke(
            [
                SystemMessage(
                    content="You are an SRE. From the alert, evidence, and retrieved runbooks, state the single "
                    "most likely root cause and a confidence of low, medium, or high. Add a 'Runbook:' line "
                    "naming the runbook you relied on, if any. Be concise."
                ),
                HumanMessage(
                    content=f"ALERT:\n{state['trigger']}\n\nEVIDENCE:\n{evidence}\n\nRUNBOOKS:\n{rb_text}"
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

    async def gate(state: IncidentState) -> dict:
        # Pause and persist; a human approves out of band, then the graph resumes here.
        decision = interrupt(
            {
                "incident_type": state.get("incident_type"),
                "target_service": state.get("target_service"),
                "diagnosis": state.get("diagnosis"),
                "proposed_fix": state.get("proposed_fix"),
            }
        )
        return {"approval": decision if isinstance(decision, dict) else {"approved": bool(decision)}}

    async def execute(state: IncidentState) -> dict:
        # Real remediation, SANDBOX ONLY, via the token gated fleet-write server.
        appr = state.get("approval") or {}
        if not appr.get("approved"):
            return {"execution": {"status": "rejected", "approver": appr.get("approver")}}
        svc = state.get("target_service") or ""
        if not svc or svc == "unknown":
            return {"execution": {"status": "skipped", "reason": "no target service to remediate"}}
        tool = by_name.get("restart_service")
        if tool is None:
            return {"execution": {"status": "error", "reason": "fleet-write unavailable"}}
        out = _text(await tool.ainvoke({"service": svc, "approval_token": expected_token()}))
        return {
            "execution": {"status": "executed", "action": f"restart_service({svc})", "result": out}
        }

    async def verify(state: IncidentState) -> dict:
        svc = state.get("target_service") or ""
        recovered, detail = False, ""
        tool = by_name.get("service_status")
        if svc and svc != "unknown" and tool is not None:
            detail = _text(await tool.ainvoke({"service": svc}))
            recovered = "Active: active" in detail or "active (running)" in detail
        mttr = round(time.time() - state["started_at"], 1) if state.get("started_at") else None
        return {"verification": {"recovered": recovered, "mttr_seconds": mttr, "detail": detail[:300]}}

    def after_gate(state: IncidentState) -> str:
        return "execute" if (state.get("approval") or {}).get("approved") else END

    g = StateGraph(IncidentState)
    g.add_node("triage", triage)
    g.add_node("investigate_services", investigate_services)
    g.add_node("investigate_metrics", investigate_metrics)
    g.add_node("investigate_logs", investigate_logs)
    g.add_node("diagnose", diagnose)
    g.add_node("propose", propose)
    g.add_edge(START, "triage")
    # fan out: triage -> all investigators in parallel
    for n in ("investigate_services", "investigate_metrics", "investigate_logs"):
        g.add_edge("triage", n)
        g.add_edge(n, "diagnose")  # fan in: diagnose waits for all three
    g.add_node("gate", gate)
    g.add_node("execute", execute)
    g.add_node("verify", verify)
    g.add_edge("diagnose", "propose")
    g.add_edge("propose", "gate")
    g.add_conditional_edges("gate", after_gate, {"execute": "execute", END: END})
    g.add_edge("execute", "verify")
    g.add_edge("verify", END)
    return g.compile(checkpointer=checkpointer)


async def build_graph_default():
    """Build with an in memory checkpointer, for CLI use without Postgres."""
    from langgraph.checkpoint.memory import MemorySaver

    return await build_graph(checkpointer=MemorySaver())


async def run(trigger: str, thread_id: str = "cli") -> dict:
    """CLI helper: run until the approval gate and return the state snapshot (no execution)."""
    graph = await build_graph_default()
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke({"trigger": trigger}, config)
    snapshot = await graph.aget_state(config)
    return dict(snapshot.values)
