# Backend image: FastAPI + LangGraph + MCP servers.
# The HF embedding model and AWS creds are mounted at runtime (not baked in).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    FASTMCP_DISABLE_BANNER=1 \
    PYTHONPATH=/app:/app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv awscli

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY backend/ ./backend/
COPY mcp_servers/ ./mcp_servers/

EXPOSE 8077
CMD ["uv", "run", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8077"]
