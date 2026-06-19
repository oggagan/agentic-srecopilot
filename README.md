# Agentic SRE Copilot

A multi-agent system that watches a server fleet, diagnoses incidents, proposes a fix, waits for a
human to approve, executes the remediation, and verifies recovery. Reliability is measured end to end
by a built in evals harness, so every change is scored, not guessed.

## Reliability scorecard

Measured by `evals/run_offline.py` against fault injection on a disposable sandbox EC2:

| Metric | Result |
|---|---|
| Diagnosis accuracy | 100% |
| Remediation success rate | 100% |
| Average MTTR | 23.2s |
| False positive rate | 0% |
| Cost per incident | ~$0.002 |

(Small scenario set today; the harness and scoring are the point and scale with more scenarios.)

## Why this exists

Output quality and reliability is the number one barrier to shipping agents to production. Most teams
have observability but few have evals. This project treats evals and human approved remediation as
first class, and the agent never writes to production: it diagnoses prod read only and remediates only
on a disposable sandbox.

## How it works

```
alert
  -> triage (classify type, severity, target)
  -> investigate: services | metrics | logs   (3 agents in parallel, fan in)
  -> diagnose (reasoner + RAG over runbooks, with citations)
  -> propose fix (each step risk tagged)
  -> [human approval gate]   durable interrupt, state persisted to Postgres
  -> execute (token gated, sandbox only)
  -> verify (re-check health, compute MTTR)
```

## Architecture

- LangGraph orchestrator (fan out / fan in, conditional routing, interrupt + Postgres checkpointer)
- MCP tools via FastMCP: `fleet-readonly` (safe diagnostics), `fleet-write` (token gated, sandbox only), `runbooks`
- Provider agnostic LLM client; DeepSeek today, Claude or Bedrock by config
- RAG over PostgreSQL + pgvector with hybrid dense and keyword retrieval (RRF), local bge-small embeddings
- FastAPI backend with SSE streaming; React (Vite) dashboard
- Observability with OpenTelemetry + OpenInference to Phoenix and Langfuse
- Cost meter with per run token and USD accounting

## Safety model

- Read and write live in separate MCP servers. The write server refuses without a valid approval
  token (an HMAC the model never sees) and only ever connects to the sandbox.
- Production is read only. The closed remediation loop runs against the disposable sandbox.
- Every state change requires explicit human approval at the interrupt gate.

## Run it locally

```bash
# 1. infra (Postgres + pgvector, Phoenix, Langfuse)
docker compose up -d

# 2. python env (uv) and the runbook corpus
uv sync
PYTHONPATH=.:backend uv run python -m app.ingest

# 3. backend API (SSE) on :8077
PYTHONPATH=.:backend uv run uvicorn app.main:app --app-dir backend --port 8077

# 4. dashboard on :5173 (proxies /api to the backend)
cd frontend && npm install && npm run dev

# 5. evals (fault injection on the sandbox -> scorecard)
PYTHONPATH=.:backend uv run python evals/run_offline.py
```

Copy `.env.example` to `.env` and fill in the keys (DeepSeek, sandbox instance id and PEM path).

## Tests / CI

`pytest` unit tests run on every push via `.github/workflows/ci.yml` (deterministic, no live infra).
The full eval suite runs against the sandbox and writes `evals/scorecard.md` and `evals/baseline.json`.

## Status

POC, then MVP. Built: parallel multi-agent diagnosis, RAG with citations, durable human approval,
real sandbox remediation with verification, dashboard, evals, observability, cost control.
