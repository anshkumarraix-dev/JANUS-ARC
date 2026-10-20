"""Janus (ElderSync) — Routine Logging Tool Schemas.

Defines Pydantic v2 data models for non-clinical daily routine logs and visual cards.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RoutineLogRequest(BaseModel):
    senior_id: str = Field(..., description="Unique senior profile ID (e.g., 'margaret_01')")
    routine_type: str = Field(..., description="Type of routine: 'hydration', 'meal', 'vitamins', 'walk', 'mobility', 'wellness'")
    logged_by: str = Field("senior_voice", description="Actor who logged the event ('senior_voice', 'caregiver_sarah')")
    notes: str = Field("", description="Additional context, description, or amount (e.g., '500ml water')")


class VisualCardPayload(BaseModel):
    card_type: str = Field("EchoShowCard", description="Type of card layout")
    title: str = Field(..., description="Card headline")
    body: Optional[str] = Field(None, description="Card descriptive text")
    stats: Optional[Dict[str, Any]] = Field(None, description="Key-value metrics")
    time: Optional[str] = Field(None, description="ISO timestamp")


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


class MissedRoutineRequest(BaseModel):
    senior_id: str
    routine_name: str
    scheduled_time: str
    urgency_level: str = "medium"


class MissedRoutineAlert(BaseModel):
    type: str = "ambient_reminder"
    voice_prompt: str
    echo_show_banner: Dict[str, Any]


class MissedRoutineResponse(BaseModel):
    status: str = "FLAGGED"
    senior_id: str
    routine_name: str
    scheduled_time: str
    urgency_level: str
    is_missed: bool
    alert_payload: MissedRoutineAlert
    message: str
