"""Shared state passed between graph nodes."""
from typing import TypedDict


class IncidentState(TypedDict, total=False):
    trigger: str          # the incoming alert text
    incident_type: str    # set by triage
    target_service: str   # set by triage
    severity: str         # set by triage
    evidence: str         # gathered by investigate (MCP tool output)
    runbooks: list        # titles of runbooks retrieved for the diagnosis
    diagnosis: str        # root cause from the reasoner
    proposed_fix: str     # suggested remediation, NOT executed
