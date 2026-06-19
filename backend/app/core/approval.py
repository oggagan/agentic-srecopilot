"""Mint the approval token for the fleet-write server (backend side).

Mirrors mcp_servers/common/approval.py and uses the same secret, so the token the execute
node mints matches what the write server expects.
"""
import hashlib
import hmac

from app.config import settings


def expected_token() -> str:
    return hmac.new(
        settings.sandbox_write_token_secret.encode(), b"approved-remediation", hashlib.sha256
    ).hexdigest()
