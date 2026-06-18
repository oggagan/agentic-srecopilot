"""Incident API: trigger a run and stream each node's result as SSE."""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.graph.build import build_graph

router = APIRouter(prefix="/api")


class TriggerIn(BaseModel):
    trigger: str


@router.post("/incidents")
async def create_incident(body: TriggerIn) -> StreamingResponse:
    async def gen():
        graph = await build_graph()
        async for update in graph.astream({"trigger": body.trigger}, stream_mode="updates"):
            for node, data in update.items():
                yield f"event: {node}\ndata: {json.dumps(data)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
