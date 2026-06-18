"""Incident API: trigger a run and stream each node's result as SSE."""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.callbacks import get_usage_metadata_callback
from pydantic import BaseModel

from app.core.cost import summarize_cost
from app.graph.build import build_graph

router = APIRouter(prefix="/api")


class TriggerIn(BaseModel):
    trigger: str


@router.post("/incidents")
async def create_incident(body: TriggerIn) -> StreamingResponse:
    async def gen():
        graph = await build_graph()
        with get_usage_metadata_callback() as cb:
            async for update in graph.astream(
                {"trigger": body.trigger}, stream_mode="updates"
            ):
                for node, data in update.items():
                    yield f"event: {node}\ndata: {json.dumps(data)}\n\n"
            cost = summarize_cost(cb.usage_metadata)
        yield f"event: cost\ndata: {json.dumps(cost)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
