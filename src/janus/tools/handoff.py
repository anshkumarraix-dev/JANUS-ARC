"""Janus (ElderSync) — Caregiver Handoff Tool Schemas.

Defines Pydantic v2 data models for caregiver shift handoffs and confirmation gates.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ShiftHandoffPayload(BaseModel):
    departing_caregiver: str = Field(..., description="Caregiver ending their shift")
    incoming_caregiver: str = Field(..., description="Caregiver assuming the new shift")
    handoff_notes: str = Field("", description="Operational shift handover notes")
    routine_snapshot: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Snapshot of completed routines")


class RoutineStateVerifyRequest(BaseModel):
    senior_id: str = Field(..., description="Target senior profile ID")
    action_type: str = Field("shift_handoff", description="Action type ('shift_handoff', 'schedule_override')")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Payload containing action parameters")
    confirm: bool = Field(False, description="Confirmation flag (False = preview proposal; True = commit)")


class ProposalPreviewResponse(BaseModel):
    status: str = "PROPOSAL_PREVIEW"
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
    action_type: str
    senior_id: str
    database_writes: int = 1
    committed_record: Dict[str, Any]
    echo_show_card: Dict[str, Any]
    spoken_response: str
