"""Janus (ElderSync) — Routine Logging Tool Schemas.

Defines Pydantic v2 data models for non-clinical daily routine logs and visual cards.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


VALID_CATEGORIES = {"meal", "hydration", "vitamins", "activity", "wellness"}


class RoutineLogRequest(BaseModel):
    senior_id: str = Field(..., description="Unique senior profile ID (e.g., 'margaret_01')")
    category: str = Field(..., description="Routine category: 'meal', 'hydration', 'vitamins', 'activity', 'wellness'")
    details: str = Field("", description="Additional details, description, or quantity (e.g., '500ml water')")
    timestamp: Optional[str] = Field(None, description="Optional ISO timestamp override")


class VisualCardPayload(BaseModel):
    card_type: str = Field("EchoShowCard", description="Type of card layout")
    title: str = Field(..., description="Card headline")
    body: Optional[str] = Field(None, description="Card descriptive text")
    stats: Optional[Dict[str, Any]] = Field(None, description="Key-value metrics")
    time: Optional[str] = Field(None, description="ISO timestamp")


class RoutineProposalPreview(BaseModel):
    senior_id: str
    category: str
    details: str
    timestamp: str
    actor: str
    expires_at: str


class RoutineLogProposalResponse(BaseModel):
    transaction_id: str
    status: str = "pending_confirmation"
    preview: Dict[str, Any]
    spoken_prompt: str
    database_writes: int = 0
    echo_show_card: Optional[Dict[str, Any]] = None


class RoutineLogResponse(BaseModel):
    status: str = "success"
    event_id: int
    senior_id: str
    routine_type: str
    logged_by: str
    notes: str
    timestamp: str
    echo_show_card: Dict[str, Any]
    message: str


class CaregiverSummaryRequest(BaseModel):
    senior_id: str = Field(..., description="Target senior profile ID")
    date: Optional[str] = Field(None, description="Target date in 'YYYY-MM-DD' format")
    filter_status: str = Field("all", description="Filter slots by status: 'all', 'completed', or 'pending'")


class MissedRoutineRequest(BaseModel):
    senior_id: str
    threshold_hours: int = 1
    routine_name: Optional[str] = None
    scheduled_time: Optional[str] = None
    urgency_level: str = "medium"


class MissedRoutineAlert(BaseModel):
    type: str = "ambient_reminder"
    voice_prompt: str
    echo_show_banner: Dict[str, Any]


class MissedRoutineResponse(BaseModel):
    status: str
    senior_id: str
    senior_name: Optional[str] = None
    routine_name: Optional[str] = None
    scheduled_time: Optional[str] = None
    urgency_level: Optional[str] = None
    is_missed: bool
    alert_payload: MissedRoutineAlert
    message: str

