"""Janus (ElderSync) — Caregiver Handoff & Confirmation Gate Schemas.

Defines Pydantic v2 data models for caregiver shift handoffs, safety confirmation gate
previews, atomic commits, and idempotent replay responses.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import Field

from janus.tools.base import JanusBaseModel


class ShiftHandoffPayload(JanusBaseModel):
    """Payload for creating a caregiver shift handover proposal."""

    departing_caregiver: str = Field(..., description="Caregiver ending their shift")
    incoming_caregiver: str = Field(..., description="Caregiver assuming the new shift")
    handoff_notes: str = Field("", description="Operational shift handover notes")
    routine_snapshot: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Snapshot of completed and pending routines")


class RoutineStateVerifyRequest(JanusBaseModel):
    """Input parameters for verify_routine_state confirmation gate."""

    confirm: bool = Field(False, description="Confirmation flag (False = preview proposal; True = atomic commit)")
    transaction_id: Optional[str] = Field(None, description="Transaction ID of a live pending proposal (tx_...). Required when confirm=True")
    senior_id: Optional[str] = Field(None, description="Target senior profile ID for creating a new proposal")
    action_type: Optional[str] = Field("shift_handoff", description="Action type ('shift_handoff', 'routine_log')")
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Payload containing action parameters when creating a proposal")


class ProposalPreviewResponse(JanusBaseModel):
    """Returned when a state-changing proposal is previewed with confirm=False (0 database writes)."""

    status: str = "PROPOSAL_PREVIEW"
    transaction_id: str
    confirm_required: bool = True
    action_type: str
    senior_id: str
    proposed_payload: Dict[str, Any]
    routine_snapshot: Optional[Dict[str, Any]] = None
    database_writes: int = 0
    preview_summary: str
    spoken_prompt: str
    expires_at: Optional[str] = None
    instructions: str
    apl: Optional[Dict[str, Any]] = None
    display: Optional[Dict[str, Any]] = None


class CommittedStateResponse(JanusBaseModel):
    """Returned when a proposal is confirmed and committed to storage (1 database write)."""

    status: str = "COMMITTED"
    transaction_id: str
    action_type: str
    senior_id: str
    result_id: int
    database_writes: int = 1
    committed_record: Dict[str, Any]
    echo_show_card: Dict[str, Any]
    spoken_response: str
    apl: Optional[Dict[str, Any]] = None
    display: Optional[Dict[str, Any]] = None


class AlreadyCommittedResponse(JanusBaseModel):
    """Returned when a proposal was already confirmed, ensuring idempotent re-execution (0 writes)."""

    status: str = "ALREADY_COMMITTED"
    transaction_id: str
    action_type: str
    senior_id: str
    result_id: Optional[int] = None
    database_writes: int = 0
    message: str
    apl: Optional[Dict[str, Any]] = None
    display: Optional[Dict[str, Any]] = None


class ProposalErrorResponse(JanusBaseModel):
    """Returned when proposal verification encounters an error with a stable code."""

    status: str = "error"
    error_code: str
    message: str
    database_writes: int = 0
    transaction_id: Optional[str] = None


ShiftHandoffPayload.model_rebuild()
RoutineStateVerifyRequest.model_rebuild()
ProposalPreviewResponse.model_rebuild()
CommittedStateResponse.model_rebuild()
AlreadyCommittedResponse.model_rebuild()
ProposalErrorResponse.model_rebuild()
