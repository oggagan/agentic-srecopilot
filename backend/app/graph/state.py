"""Shared state passed between graph nodes."""
import operator
from typing import Annotated, TypedDict


class IncidentState(TypedDict, total=False):
    trigger: str          # the incoming alert text
    incident_type: str    # set by triage
    target_service: str   # set by triage
    severity: str         # set by triage
    # parallel investigators each append a finding; the reducer merges them on fan-in
    findings: Annotated[list, operator.add]
    runbooks: list        # titles of runbooks retrieved for the diagnosis
    diagnosis: str        # root cause from the reasoner
    proposed_fix: str     # suggested remediation, NOT executed
    approval: dict        # human decision from the interrupt gate
    execution: dict       # result of executing the approved plan
