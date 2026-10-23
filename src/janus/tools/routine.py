"""JANUS-ARC — Routine Logging & Summary Tool Schemas.

Defines Pydantic v2 data models for non-clinical daily routine logs, caregiver summaries,
and ambient missed-routine alert notifications.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import Field

from janus.tools.base import JanusBaseModel


VALID_CATEGORIES = {"meal", "hydration", "vitamins", "activity", "wellness"}


class RoutineLogRequest(JanusBaseModel):
    """Input payload for proposing a non-clinical daily living routine."""

    senior_id: str = Field(..., description="Target senior profile identifier (e.g., 'margaret_01')")
    category: Optional[str] = Field(None, description="Routine category: 'meal', 'hydration', 'vitamins', 'activity', 'wellness'")
    details: str = Field("", description="Additional description, quantity, or note (e.g., '500ml water', 'Morning oatmeal')")
    timestamp: Optional[str] = Field(None, description="Optional ISO timestamp override")
    routine_type: Optional[str] = Field(None, description="Alias for category (backward compatibility)")
    notes: Optional[str] = Field(None, description="Alias for details (backward compatibility)")
    logged_by: Optional[str] = Field("senior_voice", description="Actor initiating the log: 'senior_voice', 'caregiver_sarah', etc.")


class RoutineProposalPreview(JanusBaseModel):
    """Read-only preview of a proposed routine log event."""

    senior_id: str
    category: str
    details: str
    timestamp: str
    actor: str
    expires_at: str
    apl: Optional[Dict[str, Any]] = None
    display: Optional[Dict[str, Any]] = None


class RoutineLogProposalResponse(JanusBaseModel):
    """Response returned when a routine log proposal is generated (0 writes)."""

    transaction_id: str
    status: str = "pending_confirmation"
    preview: RoutineProposalPreview
    spoken_prompt: str
    database_writes: int = 0
    echo_show_card: Optional[Dict[str, Any]] = None
    apl: Optional[Dict[str, Any]] = None
    display: Optional[Dict[str, Any]] = None
    senior_id: str
    routine_type: str
    category: str
    notes: str
    logged_by: str


class CaregiverSummaryRequest(JanusBaseModel):
    """Input parameters for querying a senior's daily timeline summary."""

    senior_id: str = Field(..., description="Target senior profile identifier (e.g., 'margaret_01')")
    date: Optional[str] = Field(None, description="Target date in 'YYYY-MM-DD' format (defaults to current date in senior's timezone)")
    filter_status: str = Field("all", description="Filter slots by status: 'all', 'completed', or 'pending'")


class CaregiverSummaryResponse(JanusBaseModel):
    """Aggregated daily timeline and schedule metrics for caregiver handoff."""

    status: str = "success"
    senior_id: str
    senior_name: str
    date: str
    timezone: str
    filter_status: str = "all"
    total_slots: int
    completed_count: int
    pending_count: int
    completion_percentage: Union[int, float] = 0
    last_activity: Optional[str] = None
    total_events: int
    events: List[Dict[str, Any]] = Field(default_factory=list)
    slots: List[Dict[str, Any]] = Field(default_factory=list)
    completed_types: List[str] = Field(default_factory=list)
    pending_routines: List[Dict[str, Any]] = Field(default_factory=list)
    visual_card: Dict[str, Any] = Field(default_factory=dict)
    apl: Optional[Dict[str, Any]] = None
    display: Optional[Dict[str, Any]] = None


class MissedRoutineRequest(JanusBaseModel):
    """Input parameters for scanning or checking missed routine windows."""

    senior_id: str = Field(..., description="Target senior profile identifier (e.g., 'margaret_01')")
    threshold_hours: int = Field(1, description="Minimum hours overdue before escalating alerts (default 1)")
    routine_name: Optional[str] = Field(None, description="Optional specific routine name or category to check")
    scheduled_time: Optional[str] = Field(None, description="Optional expected time window string (e.g. '14:00')")
    urgency_level: str = Field("medium", description="Urgency level ('low', 'medium', 'high')")


class MissedRoutineAlert(JanusBaseModel):
    """Ambient voice and visual alert payload for a missed routine."""

    type: str = "ambient_reminder"
    voice_prompt: str
    echo_show_banner: Dict[str, Any]


class MissedRoutineResponse(JanusBaseModel):
    """Result of routine check or schedule scan with gentle reminder prompts."""

    status: str
    senior_id: str
    senior_name: Optional[str] = None
    routine_name: Optional[str] = None
    scheduled_time: Optional[str] = None
    urgency_level: Optional[str] = None
    is_missed: bool
    alert_payload: MissedRoutineAlert
    apl: Optional[Dict[str, Any]] = None
    display: Optional[Dict[str, Any]] = None
    message: str
    date: Optional[str] = None
    threshold_hours: Optional[int] = None
    overdue_count: Optional[int] = None
    overdue_slots: Optional[List[Dict[str, Any]]] = None
    alerts_count: Optional[int] = None
    alerts_emitted: Optional[List[Dict[str, Any]]] = None


RoutineLogRequest.model_rebuild()
RoutineProposalPreview.model_rebuild()
RoutineLogProposalResponse.model_rebuild()
CaregiverSummaryRequest.model_rebuild()
CaregiverSummaryResponse.model_rebuild()
MissedRoutineRequest.model_rebuild()
MissedRoutineAlert.model_rebuild()
MissedRoutineResponse.model_rebuild()
