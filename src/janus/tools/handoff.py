"""Janus (ElderSync) — Caregiver Handoff Tool Schemas.

Defines Pydantic v2 data models for caregiver shift handoffs and confirmation gates.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ShiftHandoffPayload(BaseModel):
    departing_caregiver: str = Field(..., description="Caregiver ending their shift")
    incoming_caregiver: str = Field(..., description="Caregiver assuming the new shift")
    handoff_notes: str = Field("", description="Operational shift handover notes")
    routine_snapshot: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Snapshot of completed routines")


class RoutineStateVerifyRequest(BaseModel):
    confirm: bool = Field(False, description="Confirmation flag (False = preview proposal; True = atomic commit)")
    transaction_id: Optional[str] = Field(None, description="Transaction ID of a live pending proposal (tx_...)")
    senior_id: Optional[str] = Field(None, description="Target senior profile ID for creating new proposal")
    action_type: Optional[str] = Field("shift_handoff", description="Action type ('shift_handoff', 'routine_log')")
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Payload containing action parameters")


class ProposalPreviewResponse(BaseModel):
    status: str = "PROPOSAL_PREVIEW"
    transaction_id: str
    confirm_required: bool = True
    action_type: str
    senior_id: str
    proposed_payload: Dict[str, Any]
    routine_snapshot: Dict[str, Any]
    database_writes: int = 0
    preview_summary: str
    spoken_prompt: str
    instructions: str


class CommittedStateResponse(BaseModel):
    status: str = "COMMITTED"
    transaction_id: str
    action_type: str
    senior_id: str
    result_id: int
    database_writes: int = 1
    committed_record: Dict[str, Any]
    echo_show_card: Dict[str, Any]
    spoken_response: str


class AlreadyCommittedResponse(BaseModel):
    status: str = "ALREADY_COMMITTED"
    transaction_id: str
    action_type: str
    senior_id: str
    result_id: Optional[int]
    database_writes: int = 0
    message: str


class ProposalErrorResponse(BaseModel):
    status: str = "error"
    error_code: str
    message: str
    database_writes: int = 0
    transaction_id: Optional[str] = None
