"""FastAPI entrypoint for the Agentic SRE Copilot."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.api import incidents
from app.config import settings
from app.core.observability import setup_tracing

setup_tracing()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One durable checkpointer for the whole app, so interrupts survive across requests.
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
        await saver.setup()
        app.state.saver = saver
        yield


app = FastAPI(title="Agentic SRE Copilot", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incidents.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "provider": settings.llm_provider}
