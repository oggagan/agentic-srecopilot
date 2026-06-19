"""Deterministic end-to-end graph test with fake model/tools/retrieve (no live infra).

This is the CI eval-regression gate: it exercises the real graph wiring, the bounded
verify-retry, escalation, and the learning loop, without an LLM, DB, or SSH.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.graph.build import Deps, Triage, build_graph_default  # noqa: E402

TRIAGE = Triage(incident_type="service_down", target_service="demoapp", severity="sev1")
DIAG = "Root cause: demoapp was stopped. Confidence: high. Runbook: systemd service is down"


class FakeChat:
    def __init__(self):
        self._struct = False

    def with_structured_output(self, schema, **kw):
        c = FakeChat()
        c._struct = True
        return c

    async def ainvoke(self, messages):
        return TRIAGE if self._struct else AIMessage(content=DIAG)


class FakeTool:
    def __init__(self, fn):
        self.fn = fn

    async def ainvoke(self, args):
        return self.fn(args)


class Fleet:
    """Sandbox stand in. Restart succeeds on the Nth attempt; status reflects state."""
    def __init__(self, success_after):
        self.up = False
        self.restarts = 0
        self.success_after = success_after

    def restart(self, _args):
        self.restarts += 1
        if self.restarts >= self.success_after:
            self.up = True
        return "active" if self.up else "failed"

    def status(self, _args):
        return "Active: active (running)" if self.up else "Active: inactive (dead)"


def _tools(fleet):
    return {
        "service_status": FakeTool(fleet.status),
        "list_failed_services": FakeTool(lambda a: "demoapp.service failed"),
        "disk_usage": FakeTool(lambda a: "/ 50% used"),
        "memory_usage": FakeTool(lambda a: "mem ok"),
        "cpu_load": FakeTool(lambda a: "load 0.1"),
        "tail_log": FakeTool(lambda a: "Stopped demoapp.service"),
        "restart_service": FakeTool(fleet.restart),
    }


async def _run_case(success_after):
    fleet = Fleet(success_after)
    remembered = []
    deps = Deps(
        model=lambda role="chat", **kw: FakeChat(),
        tools=_tools(fleet),
        retrieve=lambda q: [{"title": "systemd service is down", "text": "restart the service"}],
        remember=lambda s: remembered.append(s),
    )
    graph = await build_graph_default(deps=deps)
    cfg = {"configurable": {"thread_id": f"fix-{success_after}"}}
    await graph.ainvoke({"trigger": "demoapp is down"}, cfg)
    await graph.ainvoke(Command(resume={"approved": True, "approver": "test"}), cfg)
    v = (await graph.aget_state(cfg)).values
    return v, remembered


def test_happy_path_recovers_and_remembers():
    v, remembered = asyncio.run(_run_case(success_after=1))
    assert v["verification"]["recovered"] is True
    assert v["retry_count"] == 1
    assert not v.get("escalated")
    assert len(remembered) == 1  # learning loop fired


def test_retry_then_recover():
    v, remembered = asyncio.run(_run_case(success_after=2))
    assert v["verification"]["recovered"] is True
    assert v["retry_count"] == 2
    assert len(remembered) == 1


def test_escalate_when_remediation_keeps_failing():
    v, remembered = asyncio.run(_run_case(success_after=99))
    assert v["verification"]["recovered"] is False
    assert v.get("escalated") is True
    assert v["retry_count"] == 2
    assert len(remembered) == 0  # nothing learned on failure
