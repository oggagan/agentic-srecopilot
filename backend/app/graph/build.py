"""The incident graph: triage -> investigate (parallel) -> diagnose (RAG) -> propose
-> human approval gate -> execute -> verify -> (retry | escalate | report).

I/O is injected via Deps so the graph runs against real MCP/LLM/pgvector in production and
against fakes in tests (the deterministic CI gate). No node touches a global directly.
"""
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.core.approval import expected_token
from app.graph.state import IncidentState

# repo root = build.py -> graph -> app -> backend -> root
ROOT = Path(__file__).resolve().parents[3]
MAX_ATTEMPTS = 2


def _text(out) -> str:
    """Coerce an MCP tool result (string or list of content blocks) to plain text."""
    if isinstance(out, str):
        return out
    if isinstance(out, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in out)
    return str(out)


class Triage(BaseModel):
    incident_type: str = Field(
        description="service_down, high_cpu, high_memory, disk_full, error_spike, network, or unknown"
    )
    target_service: str = Field(description="affected service name, or 'unknown'")
    severity: str = Field(description="sev1, sev2, or sev3")


@dataclass
class Deps:
    """Injectable I/O boundary so the graph is testable without live infra."""
    model: Callable[..., Any]        # (role, **kw) -> chat model
    tools: dict                      # tool name -> object with .ainvoke(args)
    retrieve: Callable[[str], list]  # (query) -> list of {title, text, ...}
    remember: Callable[[dict], None] # (final state) -> persist resolved incident


def _mcp_client() -> MultiServerMCPClient:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    spec = {
        "fleet": ["-m", "mcp_servers.fleet_readonly.server"],
        "fleet_write": ["-m", "mcp_servers.fleet_write.server"],
    }
    return MultiServerMCPClient(
        {
            name: {"command": sys.executable, "args": args, "transport": "stdio", "cwd": str(ROOT), "env": env}
            for name, args in spec.items()
        }
    )


async def _real_deps() -> Deps:
    from app.core.llm_client import get_chat_model
    from app.core.pgvector_store import hybrid_search, upsert_runbook

    tools = await _mcp_client().get_tools()
    by_name = {t.name: t for t in tools}

    def retrieve(query: str) -> list:
        try:
            return hybrid_search(query)
        except Exception:
            return []

    def remember(state: dict) -> None:
        svc = state.get("target_service")
        ver = state.get("verification") or {}
        if not svc or svc == "unknown":
            return
        title = f"Past incident: {state.get('incident_type')} on {svc}"
        content = (
            f"Alert: {state.get('trigger')}\n"
            f"Diagnosis: {state.get('diagnosis')}\n"
            f"Remediation: {(state.get('execution') or {}).get('action')}\n"
            f"Outcome: recovered in {ver.get('mttr_seconds')}s"
        )
        try:
            upsert_runbook(title=title, content=content, service=svc, source="incident")
        except Exception:
            pass

    return Deps(model=get_chat_model, tools=by_name, retrieve=retrieve, remember=remember)


async def build_graph(checkpointer=None, deps: Deps | None = None):
    if deps is None:
        deps = await _real_deps()
    by_name = deps.tools

    async def _run_tools(calls: list[tuple[str, dict]]) -> str:
        chunks = []
        for name, args in calls:
            tool = by_name.get(name)
            if tool is None:
                continue
            chunks.append(f"### {name}({args})\n{_text(await tool.ainvoke(args))}")
        return "\n\n".join(chunks)

    async def triage(state: IncidentState) -> dict:
        # DeepSeek does not support the json_schema response format, so use tool calling.
        model = deps.model("chat").with_structured_output(Triage, method="function_calling")
        r = await model.ainvoke(
            [
                SystemMessage(content="You are an SRE triage assistant. Classify the incident from the alert. Use 'unknown' when unsure."),
                HumanMessage(content=state["trigger"]),
            ]
        )
        return {
            "incident_type": r.incident_type,
            "target_service": r.target_service,
            "severity": r.severity,
            "started_at": time.time(),
        }

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
        query = f"{state['trigger']} {state.get('incident_type', '')} {state.get('target_service', '')}"
        books = deps.retrieve(query)
        rb_text = "\n\n".join(f"[{b['title']}]\n{b['text']}" for b in books) or "(no runbooks found)"
        evidence = "\n\n".join(f"## {f['source']}\n{f['summary']}" for f in state.get("findings", [])) or "(no evidence)"
        model = deps.model("reasoner")
        r = await model.ainvoke(
            [
                SystemMessage(content="You are an SRE. From the alert, evidence, and retrieved runbooks, state the single most likely root cause and a confidence of low, medium, or high. Add a 'Runbook:' line naming the runbook you relied on, if any. Be concise."),
                HumanMessage(content=f"ALERT:\n{state['trigger']}\n\nEVIDENCE:\n{evidence}\n\nRUNBOOKS:\n{rb_text}"),
            ]
        )
        return {"diagnosis": r.content, "runbooks": list(dict.fromkeys(b["title"] for b in books))}

    async def propose(state: IncidentState) -> dict:
        model = deps.model("chat")
        r = await model.ainvoke(
            [
                SystemMessage(content="Propose remediation steps for the diagnosed issue. Do NOT execute anything. For each step give the command and tag it risk=read|write|destructive and reversible=yes|no. Keep it short."),
                HumanMessage(content=f"DIAGNOSIS:\n{state['diagnosis']}"),
            ]
        )
        return {"proposed_fix": r.content}

    async def gate(state: IncidentState) -> dict:
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
        appr = state.get("approval") or {}
        attempts = state.get("retry_count", 0) + 1
        if not appr.get("approved"):
            return {"execution": {"status": "rejected", "approver": appr.get("approver")}, "retry_count": attempts}
        svc = state.get("target_service") or ""
        if not svc or svc == "unknown":
            return {"execution": {"status": "skipped", "reason": "no target service"}, "retry_count": attempts}
        tool = by_name.get("restart_service")
        if tool is None:
            return {"execution": {"status": "error", "reason": "fleet-write unavailable"}, "retry_count": attempts}
        out = _text(await tool.ainvoke({"service": svc, "approval_token": expected_token()}))
        return {"execution": {"status": "executed", "action": f"restart_service({svc})", "result": out, "attempt": attempts}, "retry_count": attempts}

    async def verify(state: IncidentState) -> dict:
        svc = state.get("target_service") or ""
        recovered, detail = False, ""
        tool = by_name.get("service_status")
        if svc and svc != "unknown" and tool is not None:
            detail = _text(await tool.ainvoke({"service": svc}))
            recovered = "Active: active" in detail or "active (running)" in detail
        mttr = round(time.time() - state["started_at"], 1) if state.get("started_at") else None
        return {"verification": {"recovered": recovered, "mttr_seconds": mttr, "detail": detail[:300]}}

    async def report(state: IncidentState) -> dict:
        deps.remember(dict(state))  # learning loop: resolved incident becomes retrievable memory
        return {}

    async def escalate(state: IncidentState) -> dict:
        return {"escalated": True}

    def after_gate(state: IncidentState) -> str:
        return "execute" if (state.get("approval") or {}).get("approved") else END

    def after_verify(state: IncidentState) -> str:
        if (state.get("verification") or {}).get("recovered"):
            return "report"
        if state.get("retry_count", 0) < MAX_ATTEMPTS:
            return "execute"
        return "escalate"

    g = StateGraph(IncidentState)
    for name, fn in [
        ("triage", triage), ("investigate_services", investigate_services),
        ("investigate_metrics", investigate_metrics), ("investigate_logs", investigate_logs),
        ("diagnose", diagnose), ("propose", propose), ("gate", gate),
        ("execute", execute), ("verify", verify), ("report", report), ("escalate", escalate),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "triage")
    for n in ("investigate_services", "investigate_metrics", "investigate_logs"):
        g.add_edge("triage", n)
        g.add_edge(n, "diagnose")
    g.add_edge("diagnose", "propose")
    g.add_edge("propose", "gate")
    g.add_conditional_edges("gate", after_gate, {"execute": "execute", END: END})
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", after_verify, {"execute": "execute", "report": "report", "escalate": "escalate"})
    g.add_edge("report", END)
    g.add_edge("escalate", END)
    return g.compile(checkpointer=checkpointer)


async def build_graph_default(deps: Deps | None = None):
    """Build with an in memory checkpointer, for CLI/eval use without Postgres."""
    from langgraph.checkpoint.memory import MemorySaver

    return await build_graph(checkpointer=MemorySaver(), deps=deps)


async def run(trigger: str, thread_id: str = "cli") -> dict:
    """CLI helper: run until the approval gate and return the state snapshot (no execution)."""
    graph = await build_graph_default()
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke({"trigger": trigger}, config)
    return dict((await graph.aget_state(config)).values)
