"""Offline evals: inject faults on the sandbox, run the full graph, score reliability.

Run: PYTHONPATH=.:backend uv run python evals/run_offline.py
Writes evals/baseline.json and evals/scorecard.md.
"""
import asyncio
import json
from pathlib import Path

import yaml
from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.types import Command

from app.core.cost import summarize_cost
from app.core.observability import setup_tracing
from app.graph.build import build_graph_default
from mcp_servers.common.ssh import run_sandbox

ROOT = Path(__file__).resolve().parents[1]
SCEN = ROOT / "evals" / "scenarios"


async def run_scenario(s: dict) -> dict:
    run_sandbox("sudo systemctl start demoapp")  # ensure healthy baseline
    for cmd in s.get("inject", []):
        run_sandbox(cmd)

    graph = await build_graph_default()
    cfg = {"configurable": {"thread_id": f"eval-{s['id']}"}}
    with get_usage_metadata_callback() as cb:
        await graph.ainvoke({"trigger": s["trigger"]}, cfg)
        await graph.ainvoke(Command(resume={"approved": True, "approver": "eval"}), cfg)
    values = (await graph.aget_state(cfg)).values
    cost = summarize_cost(cb.usage_metadata)

    for cmd in s.get("reset", []):
        run_sandbox(cmd)
    run_sandbox("sudo systemctl start demoapp")  # leave it healthy

    gt = s["ground_truth"]
    is_control = s.get("negative_control", False)
    pred = values.get("incident_type")
    ver = values.get("verification") or {}
    # control passes if it did NOT cry "service_down"; fault passes on exact type match
    diag_ok = (pred != "service_down") if is_control else (pred == gt.get("incident_type"))
    return {
        "id": s["id"],
        "control": is_control,
        "predicted_type": pred,
        "expected_type": gt.get("incident_type"),
        "diagnosis_correct": diag_ok,
        "recovered": bool(ver.get("recovered")),
        "mttr_seconds": ver.get("mttr_seconds"),
        "usd": cost["usd"],
    }


async def main() -> None:
    setup_tracing()  # eval runs also export traces to Phoenix
    scenarios = [yaml.safe_load(p.read_text()) for p in sorted(SCEN.glob("*.yaml"))]
    results = []
    for s in scenarios:
        print(f"running {s['id']} ...")
        results.append(await run_scenario(s))

    faults = [r for r in results if not r["control"]]
    controls = [r for r in results if r["control"]]
    summary = {
        "scenarios": len(results),
        "diagnosis_accuracy": round(sum(r["diagnosis_correct"] for r in results) / len(results), 3),
        "remediation_success_rate": round(sum(r["recovered"] for r in faults) / max(len(faults), 1), 3),
        "avg_mttr_seconds": round(sum((r["mttr_seconds"] or 0) for r in faults) / max(len(faults), 1), 1),
        "false_positive_rate": round(sum(1 for r in controls if not r["diagnosis_correct"]) / max(len(controls), 1), 3),
        "total_usd": round(sum(r["usd"] for r in results), 5),
    }
    out = {"summary": summary, "results": results}
    (ROOT / "evals" / "baseline.json").write_text(json.dumps(out, indent=2))

    md = [
        "# Reliability Scorecard",
        "",
        f"- Diagnosis accuracy: {summary['diagnosis_accuracy'] * 100:.0f}%",
        f"- Remediation success: {summary['remediation_success_rate'] * 100:.0f}%",
        f"- Avg MTTR: {summary['avg_mttr_seconds']}s",
        f"- False positive rate: {summary['false_positive_rate'] * 100:.0f}%",
        f"- Total cost for the suite: ${summary['total_usd']}",
        "",
        "| scenario | kind | predicted | recovered | MTTR (s) | cost ($) |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        kind = "control" if r["control"] else "fault"
        md.append(
            f"| {r['id']} | {kind} | {r['predicted_type']} | {r['recovered']} | {r['mttr_seconds']} | {r['usd']} |"
        )
    (ROOT / "evals" / "scorecard.md").write_text("\n".join(md) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
