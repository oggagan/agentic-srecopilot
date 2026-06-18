"""FastAPI entrypoint for the Agentic SRE Copilot."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import incidents
from app.config import settings

app = FastAPI(title="Agentic SRE Copilot", version="0.1.0")

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
