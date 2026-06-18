# Agentic SRE Copilot

A multi-agent system that watches a production server fleet, diagnoses incidents, proposes a fix,
asks a human to approve, executes it, and verifies recovery. Reliability is measured end to end with
a built in evals harness, so every change is scored for diagnosis accuracy, remediation success, time
to recovery, and cost per incident.

## Why this exists

Output quality and reliability is the top barrier to shipping agents to production. Most teams have
observability but few have evals. This project treats evals and human approved remediation as first
class, not an afterthought.

## How it works

```
alert -> triage -> investigate (parallel) -> diagnose (RAG over runbooks)
      -> plan fix -> [human approval] -> execute -> verify -> report
```

## Stack

- LangGraph for multi agent orchestration
- MCP servers (FastMCP) for the agent tools (metrics, logs, services, AWS, runbooks)
- DeepSeek for the model, behind a provider agnostic client (Claude and Bedrock swappable)
- PostgreSQL with pgvector for RAG over runbooks and past incidents
- FastAPI backend, React dashboard
- Arize Phoenix and Langfuse for tracing, OpenTelemetry based
- Evals harness with fault injection on a disposable sandbox

## Status

Early build. POC first, then MVP, then a production grade product. See commits for progress.
