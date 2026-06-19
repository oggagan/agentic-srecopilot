"""Deterministic unit tests, no network or DB. This is the automated CI gate."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.core.approval import expected_token as backend_token  # noqa: E402
from app.core.cost import PRICES, summarize_cost  # noqa: E402
from app.core.pgvector_store import chunk_text  # noqa: E402
from mcp_servers.common.approval import expected_token as server_token  # noqa: E402


def test_cost_math():
    usage = {"deepseek-chat": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
    c = summarize_cost(usage)
    assert c["input_tokens"] == 1_000_000
    expected = PRICES["deepseek-chat"]["in"] + PRICES["deepseek-chat"]["out"]
    assert round(c["usd"], 4) == round(expected, 4)


def test_cost_empty():
    assert summarize_cost({})["usd"] == 0.0


def test_chunk_text_nonempty():
    chunks = chunk_text("paragraph one\n\nparagraph two\n\nparagraph three")
    assert len(chunks) >= 1
    assert all(isinstance(c, str) and c for c in chunks)


def test_approval_tokens_match():
    # the backend (which mints) and the write server (which verifies) must agree
    assert backend_token() == server_token()
