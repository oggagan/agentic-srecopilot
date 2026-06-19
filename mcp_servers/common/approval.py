"""Approval token shared between the execute node and the fleet-write MCP server.

The write tools refuse to act without a valid token. The token is an HMAC over a fixed
message with a secret the LLM never sees, so the model cannot forge a write; only the
execute node (which runs after the human approval gate) can mint it.
"""
import hashlib
import hmac
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def expected_token() -> str:
    secret = os.getenv("SANDBOX_WRITE_TOKEN_SECRET", "dev-write-secret")
    return hmac.new(secret.encode(), b"approved-remediation", hashlib.sha256).hexdigest()


def check_token(token: str) -> bool:
    return hmac.compare_digest(token or "", expected_token())
