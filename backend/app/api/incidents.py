"""Incident API: trigger a run (streams to the approval gate) and resume via approve."""
import json
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.types import Command
from pydantic import BaseModel

from app.core.cost import summarize_cost
from app.graph.build import build_graph

router = APIRouter(prefix="/api")


class TriggerIn(BaseModel):
    trigger: str


class ApproveIn(BaseModel):
    approved: bool
    approver: str = "operator"


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream(graph, payload, config):
    """Stream node updates as SSE; surface the approval interrupt and a cost summary."""
    with get_usage_metadata_callback() as cb:
        async for update in graph.astream(payload, config, stream_mode="updates"):
            if "__interrupt__" in update:
                intr = update["__interrupt__"]
                value = intr[0].value if isinstance(intr, (list, tuple)) else intr
                yield _sse("awaiting_approval", value)
                continue
            for node, data in update.items():
                yield _sse(node, data)
        yield _sse("cost", summarize_cost(cb.usage_metadata))


@router.post("/incidents")
async def create_incident(body: TriggerIn, request: Request) -> StreamingResponse:
    graph = await build_graph(checkpointer=request.app.state.saver)
    incident_id = uuid.uuid4().hex[:12]
    config = {"configurable": {"thread_id": incident_id}}

    async def gen():
        yield _sse("incident", {"incident_id": incident_id})
        async for chunk in _stream(graph, {"trigger": body.trigger}, config):
            yield chunk
        yield _sse("done", {"incident_id": incident_id})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/incidents/{incident_id}/approve")
async def approve(incident_id: str, body: ApproveIn, request: Request) -> StreamingResponse:
    graph = await build_graph(checkpointer=request.app.state.saver)
    config = {"configurable": {"thread_id": incident_id}}
    resume = {"approved": body.approved, "approver": body.approver}

    async def gen():
        async for chunk in _stream(graph, Command(resume=resume), config):
            yield chunk
        yield _sse("done", {"incident_id": incident_id})

    return StreamingResponse(gen(), media_type="text/event-stream")
