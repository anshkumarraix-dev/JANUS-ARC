"""Janus (ElderSync) — FastMCP v2 Server Entrypoint.

Implements the official Model Context Protocol (MCP spec 2025-11-25) over
Streamable HTTP (0.0.0.0:8000/mcp) with 4 core non-clinical tools, safety confirmation gates,
typed Pydantic v2 schemas, tool annotations, rewritten LLM descriptions, and MCP resources.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any, Dict, Optional, Union

from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from mcp.server.mcpserver import MCPServer as FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from janus import storage
from janus.auth import (
    current_identity,
    extract_bearer_token,
    verify_token,
    check_senior_access,
    check_role_access,
    get_current_identity,
    Role,
)
from janus.errors import (
    ErrorCode,
    InvalidCategoryError,
)
from janus.safety import (
    SafetyOutcome,
    assess_safety,
)
from janus.tools import (
    RoutineLogRequest,
    RoutineProposalPreview,
    RoutineLogProposalResponse,
    CaregiverSummaryRequest,
    CaregiverSummaryResponse,
    MissedRoutineRequest,
    MissedRoutineAlert,
    MissedRoutineResponse,
    ShiftHandoffPayload,
    RoutineStateVerifyRequest,
    ProposalPreviewResponse,
    CommittedStateResponse,
    AlreadyCommittedResponse,
    ProposalErrorResponse,
)
from janus.apl import (
    build_routine_preview_card,
    build_caregiver_summary_card,
    build_handoff_confirm_card,
    build_missed_routine_card,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] janus.server: %(message)s",
)
logger = logging.getLogger("janus.server")


class AuthMiddleware:
    """Starlette middleware enforcing Bearer token authentication on all endpoints except /health and OPTIONS."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Block the CORS preflight carve-out correctly (OPTIONS must pass)
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # /health stays open
        path = scope.get("path", "")
        if path == "/health":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        auth_header = headers.get("authorization")
        token = extract_bearer_token(auth_header)
        is_valid, claims, reason = verify_token(token)

        if not is_valid or not claims:
            # Log rejected attempt to audit_log
            try:
                storage.record_audit_entry(
                    actor="anonymous" if not token else "unauthenticated",
                    role="unknown",
                    tool="auth_middleware",
                    senior_id=None,
                    transaction_id=None,
                    outcome="UNAUTHORIZED",
                )
            except Exception as e:
                logger.warning("Failed to record audit entry for unauthorized request: %s", e)

            # Missing or invalid token -> HTTP 401 JSON
            response = JSONResponse(
                {
                    "error": "UNAUTHORIZED",
                    "message": reason,
                    "database_writes": 0,
                    "status_code": 401,
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        identity = {
            "actor": claims.get("actor", "anonymous"),
            "role": claims.get("role", "caregiver"),
            "allowed_seniors": set(claims.get("allowed_seniors", set())),
            "token": token,
        }

        tok = current_identity.set(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            current_identity.reset(tok)


# Initialize FastMCP Server instance
mcp = FastMCP(
    name="janus",
    instructions="Non-clinical caregiver synchronization and ambient elder daily routine logging server for Alexa+.",
)


# ---------------------------------------------------------------------------
# Tool 1: log_daily_routine
# ---------------------------------------------------------------------------
@mcp.tool(
    name="log_daily_routine",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
)
async def log_daily_routine(
    senior_id: Annotated[str, Field(description="Target senior profile identifier (e.g. 'margaret_01')")],
    category: Annotated[Optional[str], Field(description="Routine category: 'meal', 'hydration', 'vitamins', 'activity', 'wellness'")] = None,
    details: Annotated[str, Field(description="Additional description, quantity, or note (e.g. '500ml water', 'Morning oatmeal')")] = "",
    timestamp: Annotated[Optional[str], Field(description="Optional ISO timestamp override")] = None,
    routine_type: Annotated[Optional[str], Field(description="Alias for category (backward compatibility)")] = None,
    notes: Annotated[Optional[str], Field(description="Alias for details (backward compatibility)")] = None,
    logged_by: Annotated[Optional[str], Field(description="Actor initiating the log: 'senior_voice', 'caregiver_sarah', etc.")] = "senior_voice",
) -> Union[RoutineLogProposalResponse, ProposalErrorResponse]:
    """Propose logging a non-clinical elder daily routine event (meals, hydration, vitamins, activity, wellness).

    WHEN TO CALL:
    - Call when an elder or caregiver reports completing a daily living routine event (e.g. "Margaret drank a glass of water", "I finished breakfast", "Margaret took her morning vitamins", "Walked on the porch").
    - Call to initiate recording of routine wellness activities for timeline tracking.

    WHEN NOT TO CALL:
    - DO NOT call for clinical symptoms, triage, medical diagnosis, blood pressure readings, or acute pain (Janus is strictly non-clinical).
    - DO NOT call for prescription medication changes, adjustments, or titrations.
    - DO NOT call to view historical logs or check if an activity was completed (call `get_caregiver_summary` instead).
    - DO NOT call for caregiver shift changeovers (call `verify_routine_state` with action_type='shift_handoff' instead).

    TWO-STEP CONFIRMATION GATE:
    - Calling this tool creates a READ-ONLY pending proposal with 0 database writes.
    - The LLM host MUST prompt the elder or caregiver with the returned `spoken_prompt` to obtain verbal consent.
    - Once confirmed by the user, the host MUST invoke `verify_routine_state(confirm=True, transaction_id=...)` with the proposal's `transaction_id` to commit the record to permanent storage.
    """
    req = RoutineLogRequest(
        senior_id=senior_id,
        category=category,
        details=details or "",
        timestamp=timestamp,
        routine_type=routine_type,
        notes=notes,
        logged_by=logged_by or "senior_voice",
    )

    # Enforce senior access & role check BEFORE any storage call
    identity = get_current_identity()
    if not check_senior_access(identity, req.senior_id):
        audit_actor = identity.get("actor", "anonymous") if identity else (req.logged_by or "anonymous")
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="log_daily_routine",
            senior_id=req.senior_id,
            transaction_id=None,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=f"Access to senior '{req.senior_id}' is forbidden for actor '{audit_actor}'.",
            database_writes=0,
        )

    allowed, reason = check_role_access(identity, "log_routine", req.senior_id)
    if not allowed:
        audit_actor = identity.get("actor", "anonymous") if identity else (req.logged_by or "anonymous")
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="log_daily_routine",
            senior_id=req.senior_id,
            transaction_id=None,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=reason,
            database_writes=0,
        )

    resolved_details = req.details or req.notes or ""
    resolved_cat = req.category or req.routine_type

    # Medical Safety Policy Assessment (priority check before proposal creation)
    safety_assessment = assess_safety(resolved_details, category=resolved_cat)
    if safety_assessment.outcome != SafetyOutcome.ROUTINE_ALLOWED:
        logger.info(
            "log_daily_routine intercepted by safety policy: outcome=%s, rule=%s, senior_id=%s",
            safety_assessment.outcome.value,
            safety_assessment.matched_rule,
            req.senior_id,
        )
        return ProposalErrorResponse(
            status="error",
            error_code=safety_assessment.outcome.value,
            message=safety_assessment.guidance,
            database_writes=0,
        )

    if not resolved_cat:
        raise InvalidCategoryError("empty")

    validated_cat = storage.validate_category(resolved_cat)
    if identity and identity.get("role") != "admin" and req.logged_by and req.logged_by != "senior_voice":
        if identity.get("actor") and req.logged_by != identity.get("actor"):
            audit_actor = identity.get("actor", "anonymous")
            audit_role = identity.get("role", "unknown")
            storage.record_audit_entry(
                actor=audit_actor,
                role=audit_role,
                tool="log_daily_routine",
                senior_id=req.senior_id,
                transaction_id=None,
                outcome="FORBIDDEN",
            )
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.FORBIDDEN,
                message=f"Authenticated actor '{identity.get('actor')}' cannot log routines on behalf of '{req.logged_by}'.",
                database_writes=0,
            )
    actor = identity["actor"] if (identity and identity.get("actor")) else (req.logged_by or "senior_voice")

    logger.info("log_daily_routine proposal: senior=%s, cat=%s, actor=%s", req.senior_id, validated_cat, actor)

    proposal = storage.create_proposal(
        senior_id=req.senior_id,
        action_type="routine_log",
        payload={
            "category": validated_cat,
            "details": resolved_details,
            "timestamp": req.timestamp,
            "actor": actor,
        },
        actor=actor,
    )

    tx_id = proposal["transaction_id"]
    senior = storage.get_senior(req.senior_id)
    senior_name = senior["name"] if senior else req.senior_id.replace("_", " ").title()

    spoken_prompt = (
        f"I have a pending note to record {validated_cat} ({resolved_details or 'completed'}) for {senior_name}. "
        "Would you like me to confirm and record this?"
    )

    apl_card, display_card = build_routine_preview_card(
        senior_id=req.senior_id,
        senior_name=senior_name,
        category=validated_cat,
        details=resolved_details,
        voice_prompt=spoken_prompt,
        transaction_id=tx_id,
    )

    preview = RoutineProposalPreview(
        senior_id=req.senior_id,
        category=validated_cat,
        details=resolved_details,
        timestamp=req.timestamp or proposal["created_at"],
        actor=actor,
        expires_at=proposal["expires_at"],
        apl=apl_card,
        display=display_card,
    )

    echo_show_card = {
        "card_type": "EchoShowCard",
        "title": f"Proposed: {validated_cat.title()}",
        "subtitle": f"Senior: {senior_name}",
        "body": resolved_details or f"{validated_cat.title()} pending confirmation.",
        "status": "Proposal Preview (0 Writes)",
        "transaction_id": tx_id,
    }

    return RoutineLogProposalResponse(
        transaction_id=tx_id,
        status="pending_confirmation",
        preview=preview,
        spoken_prompt=spoken_prompt,
        database_writes=0,
        echo_show_card=echo_show_card,
        apl=apl_card,
        display=display_card,
        senior_id=req.senior_id,
        routine_type=validated_cat,
        category=validated_cat,
        notes=resolved_details,
        logged_by=actor,
    )


# ---------------------------------------------------------------------------
# Tool 2: get_caregiver_summary
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_caregiver_summary",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
)
async def get_caregiver_summary(
    senior_id: Annotated[str, Field(description="Target senior profile identifier (e.g. 'margaret_01')")],
    date: Annotated[Optional[str], Field(description="Target date in 'YYYY-MM-DD' format (defaults to current local date in senior's timezone)")] = None,
    filter_status: Annotated[str, Field(description="Filter slots by status: 'all', 'completed', or 'pending'")] = "all",
) -> Union[CaregiverSummaryResponse, ProposalErrorResponse]:
    """Retrieve daily routine timeline, slot completion statuses, and visual cards for a senior.

    WHEN TO CALL:
    - Call when a caregiver, family member, or senior asks for today's summary, routine status, or timeline (e.g. "How is Margaret doing today?", "Did Margaret drink water this afternoon?", "What routines are still pending?").
    - Call when rendering or refreshing the Echo Show smart display dashboard with timeline metrics.

    WHEN NOT TO CALL:
    - DO NOT call to log or record a completed routine (call `log_daily_routine` instead).
    - DO NOT call to execute or preview a shift changeover (call `verify_routine_state` instead).
    - DO NOT call for clinical records, medical history, or prescription management.

    CHARACTERISTICS:
    - Read-only tool (`readOnlyHint=True`) that never modifies the database.
    - Aggregates confirmed events against schedule slot windows (+/- 30 min grace) in senior's local timezone.
    """
    req = CaregiverSummaryRequest(
        senior_id=senior_id,
        date=date,
        filter_status=filter_status,
    )

    # Enforce senior access & role check BEFORE any storage call
    identity = get_current_identity()
    if not check_senior_access(identity, req.senior_id):
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="get_caregiver_summary",
            senior_id=req.senior_id,
            transaction_id=None,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=f"Access to senior '{req.senior_id}' is forbidden for actor '{audit_actor}'.",
            database_writes=0,
        )

    allowed, reason = check_role_access(identity, "read_summary", req.senior_id)
    if not allowed:
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="get_caregiver_summary",
            senior_id=req.senior_id,
            transaction_id=None,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=reason,
            database_writes=0,
        )

    logger.info("get_caregiver_summary: senior=%s, date=%s, filter=%s", req.senior_id, req.date, req.filter_status)
    summary = storage.get_daily_summary(senior_id=req.senior_id, target_date=req.date, filter_status=req.filter_status)
    return CaregiverSummaryResponse(**summary)


# ---------------------------------------------------------------------------
# Tool 3: verify_routine_state
# ---------------------------------------------------------------------------
@mcp.tool(
    name="verify_routine_state",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
    ),
)
async def verify_routine_state(
    confirm: Annotated[bool, Field(description="Confirmation flag: False for proposal preview; True for atomic commit")] = False,
    transaction_id: Annotated[Optional[str], Field(description="Transaction ID of a live pending proposal ('tx_...'). Required when confirm=True")] = None,
    senior_id: Annotated[Optional[str], Field(description="Target senior identifier when creating a new proposal")] = None,
    action_type: Annotated[Optional[str], Field(description="Proposal action type ('shift_handoff', 'routine_log')")] = None,
    payload: Annotated[Optional[Dict[str, Any]], Field(description="Action payload when creating a new handoff proposal. Ignored on commit")] = None,
) -> Union[ProposalPreviewResponse, CommittedStateResponse, AlreadyCommittedResponse, ProposalErrorResponse]:
    """Safety confirmation gate for committing pending proposals and previewing caregiver shift handoffs.

    WHEN TO CALL:
    - Call with `confirm=True` and `transaction_id` when the user has confirmed a pending proposal created by `log_daily_routine` or a shift handoff proposal.
    - Call with `confirm=False`, `senior_id`, and `action_type='shift_handoff'` to generate a shift handover proposal preview summarizing completed and pending routines before asking for confirmation.
    - Call with `confirm=False` and `transaction_id` to inspect an existing pending proposal preview without committing.

    WHEN NOT TO CALL:
    - DO NOT call with `confirm=True` without a valid `transaction_id` (unconfirmed payloads are rejected with 0 writes).
    - DO NOT call to record new daily routine events from scratch (call `log_daily_routine` first to create a proposal).
    - DO NOT call for clinical handoffs, hospital discharge summaries, or medical orders.

    TWO-STEP CONFIRMATION & IDEMPOTENCY:
    - `confirm=False`: Read-only preview (0 database writes).
    - `confirm=True`: Atomic commit (1 database write). Replaying `confirm=True` with the same `transaction_id` is idempotent and returns `ALREADY_COMMITTED` with 0 additional writes.
    """
    req = RoutineStateVerifyRequest(
        confirm=confirm,
        transaction_id=transaction_id,
        senior_id=senior_id,
        action_type=action_type,
        payload=payload or {},
    )

    logger.info(
        "verify_routine_state: confirm=%s, tx=%s, senior=%s, action=%s",
        req.confirm,
        req.transaction_id,
        req.senior_id,
        req.action_type,
    )

    # -----------------------------------------------------------------------
    # Case 1: Proposal Preview by Transaction ID (confirm=False + transaction_id)
    # -----------------------------------------------------------------------
    if not req.confirm and req.transaction_id:
        prop = storage.get_proposal(req.transaction_id)
        if not prop:
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.PROPOSAL_NOT_FOUND,
                message=f"Proposal '{req.transaction_id}' was not found.",
                database_writes=0,
                transaction_id=req.transaction_id,
            )

        if prop.get("is_expired"):
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.PROPOSAL_EXPIRED,
                message=f"Proposal '{req.transaction_id}' has expired.",
                database_writes=0,
                transaction_id=req.transaction_id,
            )

        if prop.get("status") == "cancelled":
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.PROPOSAL_CANCELLED,
                message=f"Proposal '{req.transaction_id}' was cancelled.",
                database_writes=0,
                transaction_id=req.transaction_id,
            )

        if prop.get("status") == "blocked":
            return ProposalErrorResponse(
                status="error",
                error_code="PROPOSAL_BLOCKED",
                message=f"Proposal '{req.transaction_id}' was blocked by medical safety policy.",
                database_writes=0,
                transaction_id=req.transaction_id,
            )

        act_type = prop["action_type"]
        s_id = prop["senior_id"]

        identity = get_current_identity()

        # Validate caller-supplied senior_id if present
        if req.senior_id and req.senior_id != s_id:
            audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
            audit_role = identity.get("role", "unknown") if identity else "unknown"
            storage.record_audit_entry(
                actor=audit_actor,
                role=audit_role,
                tool="verify_routine_state",
                senior_id=req.senior_id,
                transaction_id=req.transaction_id,
                outcome="FORBIDDEN",
            )
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.FORBIDDEN,
                message=f"Proposal '{req.transaction_id}' belongs to senior '{s_id}', not '{req.senior_id}'.",
                database_writes=0,
                transaction_id=req.transaction_id,
            )
        if not check_senior_access(identity, s_id):
            audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
            audit_role = identity.get("role", "unknown") if identity else "unknown"
            storage.record_audit_entry(
                actor=audit_actor,
                role=audit_role,
                tool="verify_routine_state",
                senior_id=s_id,
                transaction_id=req.transaction_id,
                outcome="FORBIDDEN",
            )
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.FORBIDDEN,
                message=f"Access to senior '{s_id}' is forbidden for actor '{audit_actor}'.",
                database_writes=0,
                transaction_id=req.transaction_id,
            )

        check_action = "propose_handoff" if act_type == "shift_handoff" else "log_routine"
        allowed, reason = check_role_access(identity, check_action, s_id)
        if not allowed:
            audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
            audit_role = identity.get("role", "unknown") if identity else "unknown"
            storage.record_audit_entry(
                actor=audit_actor,
                role=audit_role,
                tool="verify_routine_state",
                senior_id=s_id,
                transaction_id=req.transaction_id,
                outcome="FORBIDDEN",
            )
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.FORBIDDEN,
                message=reason,
                database_writes=0,
                transaction_id=req.transaction_id,
            )

        prop_payload = prop.get("payload", {})
        actor = prop.get("actor", "caregiver")

        senior = storage.get_senior(s_id)
        senior_name = senior["name"] if senior else s_id.replace("_", " ").title()

        if act_type == "shift_handoff":
            departing = prop_payload.get("departing_caregiver", actor)
            incoming = prop_payload.get("incoming_caregiver", "Next Caregiver")
            snapshot = prop_payload.get("routine_snapshot", {})
            pending_names = snapshot.get("pending_routines", [])
            spoken_prompt = (
                f"Shift handoff proposal from {departing} to {incoming}. "
                f"Pending routines: {len(pending_names)}. Would you like to confirm this handoff?"
            )
            preview_summary = f"Shift handoff proposal: {departing} -> {incoming}."
            apl_card, display_card = build_handoff_confirm_card(
                senior_id=s_id,
                senior_name=senior_name,
                departing=departing,
                incoming=incoming,
                notes=prop_payload.get("handoff_notes", ""),
                is_confirmed=False,
                transaction_id=req.transaction_id,
                spoken_prompt=spoken_prompt,
            )
        else:
            cat = prop_payload.get("category", "wellness")
            det = prop_payload.get("details", "")
            spoken_prompt = f"Pending note to log {cat} ({det}). Would you like to confirm?"
            preview_summary = f"Routine proposal: {cat} ({det})."
            apl_card, display_card = build_routine_preview_card(
                senior_id=s_id,
                senior_name=senior_name,
                category=cat,
                details=det,
                voice_prompt=spoken_prompt,
                transaction_id=req.transaction_id,
            )

        return ProposalPreviewResponse(
            status="PROPOSAL_PREVIEW",
            transaction_id=req.transaction_id,
            confirm_required=True,
            action_type=act_type,
            senior_id=s_id,
            proposed_payload=prop_payload,
            routine_snapshot=prop_payload.get("routine_snapshot"),
            database_writes=0,
            preview_summary=preview_summary,
            spoken_prompt=spoken_prompt,
            expires_at=prop["expires_at"],
            instructions=f"To commit this action, re-invoke verify_routine_state with confirm=True and transaction_id='{req.transaction_id}'.",
            apl=apl_card,
            display=display_card,
        )

    # -----------------------------------------------------------------------
    # Case 2: Create New Proposal Preview (confirm=False + senior_id)
    # -----------------------------------------------------------------------
    if not req.confirm:
        if not req.senior_id:
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.INVALID_ARGUMENTS,
                message="verify_routine_state with confirm=False requires either transaction_id or senior_id.",
                database_writes=0,
            )

        act_type = req.action_type or "shift_handoff"

        # Enforce role & senior access BEFORE any storage call
        identity = get_current_identity()
        if not check_senior_access(identity, req.senior_id):
            audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
            audit_role = identity.get("role", "unknown") if identity else "unknown"
            storage.record_audit_entry(
                actor=audit_actor,
                role=audit_role,
                tool="verify_routine_state",
                senior_id=req.senior_id,
                transaction_id=None,
                outcome="FORBIDDEN",
            )
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.FORBIDDEN,
                message=f"Access to senior '{req.senior_id}' is forbidden for actor '{audit_actor}'.",
                database_writes=0,
            )

        check_action = "propose_handoff" if act_type == "shift_handoff" else "log_routine"
        allowed, reason = check_role_access(identity, check_action, req.senior_id)
        if not allowed:
            audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
            audit_role = identity.get("role", "unknown") if identity else "unknown"
            storage.record_audit_entry(
                actor=audit_actor,
                role=audit_role,
                tool="verify_routine_state",
                senior_id=req.senior_id,
                transaction_id=None,
                outcome="FORBIDDEN",
            )
            return ProposalErrorResponse(
                status="error",
                error_code=ErrorCode.FORBIDDEN,
                message=reason,
                database_writes=0,
            )

        payload_data = req.payload or {}
        summary = storage.get_daily_summary(senior_id=req.senior_id)
        pending_names = [r["name"] for r in summary.get("pending_routines", [])]

        departing = payload_data.get("departing_caregiver", "Current Caregiver")
        incoming = payload_data.get("incoming_caregiver", "Next Caregiver")
        notes = payload_data.get("handoff_notes", "No shift notes provided")
        snapshot = {
            "completed": summary.get("completed_types", []),
            "total_events": summary.get("total_events", 0),
            "pending_count": len(pending_names),
            "pending_routines": pending_names,
        }

        full_payload = dict(payload_data)
        full_payload["routine_snapshot"] = snapshot

        # If shift handoff, validate via ShiftHandoffPayload model
        if act_type == "shift_handoff":
            ShiftHandoffPayload(
                departing_caregiver=departing,
                incoming_caregiver=incoming,
                handoff_notes=notes,
                routine_snapshot=snapshot,
            )

        # Medical Safety Policy Check on handoff notes
        safety_assessment = assess_safety(notes, category="wellness")
        if safety_assessment.outcome != SafetyOutcome.ROUTINE_ALLOWED:
            logger.info(
                "verify_routine_state handoff proposal intercepted by safety policy: outcome=%s, rule=%s, senior_id=%s",
                safety_assessment.outcome.value,
                safety_assessment.matched_rule,
                req.senior_id,
            )
            return ProposalErrorResponse(
                status="error",
                error_code=safety_assessment.outcome.value,
                message=safety_assessment.guidance,
                database_writes=0,
            )

        prop = storage.create_proposal(
            senior_id=req.senior_id,
            action_type=act_type,
            payload=full_payload,
            actor=departing,
        )
        tx_id = prop["transaction_id"]

        senior = storage.get_senior(req.senior_id)
        senior_name = senior["name"] if senior else req.senior_id.replace("_", " ").title()

        spoken_prompt = (
            f"{senior_name} currently has {len(pending_names)} pending routine items "
            f"({', '.join(pending_names) if pending_names else 'all daily routines completed'}). "
            f"Do you confirm handing off care from {departing} to {incoming} with notes: '{notes}'?"
        )

        apl_card, display_card = build_handoff_confirm_card(
            senior_id=req.senior_id,
            senior_name=senior_name,
            departing=departing,
            incoming=incoming,
            notes=notes,
            is_confirmed=False,
            transaction_id=tx_id,
            spoken_prompt=spoken_prompt,
        )

        return ProposalPreviewResponse(
            status="PROPOSAL_PREVIEW",
            transaction_id=tx_id,
            confirm_required=True,
            action_type=act_type,
            senior_id=req.senior_id,
            proposed_payload=full_payload,
            routine_snapshot=snapshot,
            database_writes=0,
            preview_summary=f"Shift handoff proposal: {departing} -> {incoming}. Pending items: {len(pending_names)}.",
            spoken_prompt=spoken_prompt,
            expires_at=prop["expires_at"],
            instructions=f"To commit this action, re-invoke verify_routine_state with confirm=True and transaction_id='{tx_id}'.",
            apl=apl_card,
            display=display_card,
        )

    # -----------------------------------------------------------------------
    # Case 3: Atomic Confirmed Commit (confirm=True)
    # -----------------------------------------------------------------------
    if not req.transaction_id:
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.MISSING_TRANSACTION_ID,
            message="confirm=True REQUIRES a valid transaction_id of a live pending proposal. No unconfirmed payload accepted on commit.",
            database_writes=0,
        )

    prop = storage.get_proposal(req.transaction_id)
    if not prop:
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.PROPOSAL_NOT_FOUND,
            message=f"Proposal '{req.transaction_id}' does not exist.",
            database_writes=0,
            transaction_id=req.transaction_id,
        )

    act_type = prop["action_type"]
    s_id = prop["senior_id"]

    identity = get_current_identity()

    # Validate caller-supplied senior_id if present
    if req.senior_id and req.senior_id != s_id:
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="verify_routine_state",
            senior_id=req.senior_id,
            transaction_id=req.transaction_id,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=f"Proposal '{req.transaction_id}' belongs to senior '{s_id}', not '{req.senior_id}'.",
            database_writes=0,
            transaction_id=req.transaction_id,
        )

    # Validate caller-supplied action_type if present
    if req.action_type and req.action_type != act_type:
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="verify_routine_state",
            senior_id=s_id,
            transaction_id=req.transaction_id,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=f"Proposal '{req.transaction_id}' is for action '{act_type}', not '{req.action_type}'.",
            database_writes=0,
            transaction_id=req.transaction_id,
        )

    # Enforce role & senior access BEFORE storage commit
    if not check_senior_access(identity, s_id):
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="verify_routine_state",
            senior_id=s_id,
            transaction_id=req.transaction_id,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=f"Access to senior '{s_id}' is forbidden for actor '{audit_actor}'.",
            database_writes=0,
            transaction_id=req.transaction_id,
        )

    check_action = "confirm_handoff" if act_type == "shift_handoff" else "confirm_routine"
    allowed, reason = check_role_access(identity, check_action, s_id)
    if not allowed:
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="verify_routine_state",
            senior_id=s_id,
            transaction_id=req.transaction_id,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=reason,
            database_writes=0,
            transaction_id=req.transaction_id,
        )
    commit_res = storage.commit_proposal(transaction_id=req.transaction_id)
    if commit_res["status"] == "error":
        return ProposalErrorResponse(**commit_res)
    if commit_res["status"] == "ALREADY_COMMITTED":
        return AlreadyCommittedResponse(**commit_res)

    # Successfully committed
    committed_rec = commit_res["committed_record"]
    act_type = commit_res["action_type"]
    s_id = commit_res["senior_id"]

    senior = storage.get_senior(s_id)
    senior_name = senior["name"] if senior else s_id.replace("_", " ").title()

    if act_type == "shift_handoff":
        departing = committed_rec.get("departing_caregiver", "Caregiver")
        incoming = committed_rec.get("incoming_caregiver", "Caregiver")
        notes = committed_rec.get("handoff_notes", "")
        spoken_response = f"Caregiver shift handoff from {departing} to {incoming} has been verified and recorded."
        apl_card, display_card = build_handoff_confirm_card(
            senior_id=s_id,
            senior_name=senior_name,
            departing=departing,
            incoming=incoming,
            notes=notes,
            is_confirmed=True,
            transaction_id=req.transaction_id,
            spoken_prompt=spoken_response,
        )
        echo_show_card = {
            "card_type": "EchoShowHandoffCard",
            "title": "Caregiver Shift Handoff Confirmed",
            "departing": departing,
            "incoming": incoming,
            "notes": notes,
            "timestamp": commit_res["timestamp"],
            "icon": "shield-check",
        }
    else:
        rtype = committed_rec.get("routine_type", "Routine")
        spoken_response = f"{rtype.title()} routine has been verified and recorded."
        apl_card, display_card = build_routine_preview_card(
            senior_id=s_id,
            senior_name=senior_name,
            category=rtype,
            details=committed_rec.get("notes", ""),
            voice_prompt="",
            transaction_id=req.transaction_id,
        )
        echo_show_card = {
            "card_type": "EchoShowCard",
            "title": f"Logged: {rtype.title()}",
            "body": committed_rec.get("notes", ""),
            "timestamp": commit_res["timestamp"],
            "icon": "check-circle",
        }

    return CommittedStateResponse(
        status="COMMITTED",
        transaction_id=req.transaction_id,
        action_type=act_type,
        senior_id=s_id,
        result_id=commit_res["result_id"],
        database_writes=1,
        committed_record=committed_rec,
        echo_show_card=echo_show_card,
        apl=apl_card,
        display=display_card,
        spoken_response=spoken_response,
    )


# ---------------------------------------------------------------------------
# Tool 4: flag_missed_routine
# ---------------------------------------------------------------------------
@mcp.tool(
    name="flag_missed_routine",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
    ),
)
async def flag_missed_routine(
    senior_id: Annotated[str, Field(description="Target senior profile identifier (e.g. 'margaret_01')")],
    threshold_hours: Annotated[int, Field(description="Minimum hours overdue before escalating alerts (default 1)")] = 1,
    routine_name: Annotated[Optional[str], Field(description="Optional specific routine name or category to check")] = None,
    scheduled_time: Annotated[Optional[str], Field(description="Optional expected time window string (e.g. '14:00')")] = None,
    urgency_level: Annotated[str, Field(description="Urgency level ('low', 'medium', 'high')")] = "medium",
) -> Union[MissedRoutineResponse, ProposalErrorResponse]:
    """Scan scheduled routine windows for overdue items and generate gentle, non-alarm ambient reminders.

    WHEN TO CALL:
    - Call during scheduled ambient check-ins or when proactive monitoring detects that an expected routine window has passed (e.g. senior has not logged afternoon water within threshold hours).
    - Call to check if a specific scheduled routine was missed (e.g. `routine_name="Afternoon Hydration"`).
    - Emits gentle conversational reminders and Echo Show banners formatted for non-clinical eldercare.

    WHEN NOT TO CALL:
    - DO NOT call for urgent medical emergencies, falls, or acute symptoms (escalate immediately to emergency services).
    - DO NOT call to fetch general daily summaries or completed activity counts (call `get_caregiver_summary` instead).
    - DO NOT call to record routine completions (call `log_daily_routine` instead).

    CHARACTERISTICS:
    - Writes deduplicated alerts to the database (`readOnlyHint=False`, `idempotentHint=True`). Identical slot alerts on the same day and level are never re-emitted.
    """
    req = MissedRoutineRequest(
        senior_id=senior_id,
        threshold_hours=threshold_hours,
        routine_name=routine_name,
        scheduled_time=scheduled_time,
        urgency_level=urgency_level,
    )

    # Enforce senior access & role check BEFORE any storage call
    identity = get_current_identity()
    if not check_senior_access(identity, req.senior_id):
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="flag_missed_routine",
            senior_id=req.senior_id,
            transaction_id=None,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=f"Access to senior '{req.senior_id}' is forbidden for actor '{audit_actor}'.",
            database_writes=0,
        )

    allowed, reason = check_role_access(identity, "flag_missed", req.senior_id)
    if not allowed:
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="flag_missed_routine",
            senior_id=req.senior_id,
            transaction_id=None,
            outcome="FORBIDDEN",
        )
        return ProposalErrorResponse(
            status="error",
            error_code=ErrorCode.FORBIDDEN,
            message=reason,
            database_writes=0,
        )

    logger.info(
        "flag_missed_routine: senior=%s, threshold=%s, routine=%s, time=%s, urgency=%s",
        req.senior_id,
        req.threshold_hours,
        req.routine_name,
        req.scheduled_time,
        req.urgency_level,
    )

    senior = storage.get_senior(req.senior_id)
    senior_name = senior["name"] if senior else req.senior_id.replace("_", " ").title()
    first_name = senior_name.split()[0]

    # If routine_name is specified, perform targeted single-routine verification
    if req.routine_name:
        summary = storage.get_daily_summary(senior_id=req.senior_id)
        slots = summary.get("slots", [])

        matching_slot = None
        for s in slots:
            if s["label"].lower() == req.routine_name.lower() or s["slot_id"].lower() == req.routine_name.lower():
                matching_slot = s
                break

        if matching_slot:
            is_missed = (matching_slot["status"] != "completed")
            display_time = req.scheduled_time or f"{matching_slot['window_start']} - {matching_slot['window_end']}"
            slot_label = matching_slot["label"]
        elif req.routine_name.lower() in storage.VALID_CATEGORIES:
            is_missed = req.routine_name.lower() not in summary.get("completed_types", [])
            display_time = req.scheduled_time or "today"
            slot_label = req.routine_name.title()
        else:
            is_missed = req.routine_name.lower() not in summary.get("completed_types", [])
            display_time = req.scheduled_time or "scheduled time"
            slot_label = req.routine_name

        voice_prompt = (
            f"Hi {first_name}, whenever you're ready, it might be a good time for your {slot_label.lower()}."
            if is_missed
            else f"{slot_label} has already been logged for today."
        )

        alert_payload = MissedRoutineAlert(
            type="ambient_reminder",
            voice_prompt=voice_prompt,
            echo_show_banner={
                "title": f"Routine Check-in: {slot_label}",
                "urgency": req.urgency_level,
                "scheduled_time": display_time,
                "senior_name": senior_name,
                "is_missed": is_missed,
                "action_button": f"Log {slot_label} Now",
            },
        )

        apl_card, display_card = build_missed_routine_card(
            senior_id=req.senior_id,
            senior_name=senior_name,
            routine_name=slot_label,
            display_time=display_time,
            urgency_level=req.urgency_level or "medium",
            voice_prompt=voice_prompt,
            is_missed=is_missed,
        )

        return MissedRoutineResponse(
            status="FLAGGED" if is_missed else "ALREADY_LOGGED",
            senior_id=req.senior_id,
            senior_name=senior_name,
            routine_name=req.routine_name,
            scheduled_time=display_time,
            urgency_level=req.urgency_level,
            is_missed=is_missed,
            alert_payload=alert_payload,
            apl=apl_card,
            display=display_card,
            message=(
                f"Passive reminder generated for {slot_label} (Urgency: {req.urgency_level})."
                if is_missed
                else f"{slot_label} was already verified as completed today."
            ),
        )

    # Multi-slot scan mode using scan_missed_routines
    scan_result = storage.scan_missed_routines(
        senior_id=req.senior_id,
        threshold_hours=req.threshold_hours,
    )

    top_alert = scan_result["alerts_emitted"][0] if scan_result["alerts_emitted"] else None
    if top_alert:
        alert_payload = MissedRoutineAlert(
            type="ambient_reminder",
            voice_prompt=top_alert["message"],
            echo_show_banner={
                "title": f"Routine Check-in: {top_alert['label']}",
                "urgency": "medium",
                "scheduled_time": top_alert["channel"],
                "senior_name": senior_name,
                "is_missed": True,
                "action_button": f"Log {top_alert['label']} Now",
            },
        )
    else:
        alert_payload = MissedRoutineAlert(
            type="ambient_reminder",
            voice_prompt=f"All scheduled routines are up to date for {first_name}.",
            echo_show_banner={
                "title": "All Routines Current",
                "urgency": "low",
                "scheduled_time": "Now",
                "senior_name": senior_name,
                "is_missed": False,
                "action_button": "View Timeline",
            },
        )

    apl_card, display_card = build_missed_routine_card(
        senior_id=req.senior_id,
        senior_name=senior_name,
        routine_name=top_alert["label"] if top_alert else "Daily Routines",
        display_time=top_alert["channel"] if top_alert else "Today",
        urgency_level="medium" if top_alert else "low",
        voice_prompt=alert_payload.voice_prompt,
        is_missed=bool(top_alert),
    )

    return MissedRoutineResponse(
        status=scan_result["status"],
        senior_id=req.senior_id,
        senior_name=senior_name,
        is_missed=bool(scan_result["alerts_emitted"] or scan_result["overdue_slots"]),
        alert_payload=alert_payload,
        apl=apl_card,
        display=display_card,
        message=scan_result["message"],
        date=scan_result["date"],
        threshold_hours=scan_result["threshold_hours"],
        overdue_count=scan_result["overdue_count"],
        overdue_slots=scan_result["overdue_slots"],
        alerts_count=scan_result["alerts_count"],
        alerts_emitted=scan_result["alerts_emitted"],
    )


# ---------------------------------------------------------------------------
# MCP Resource: janus://senior/{id}/today
# ---------------------------------------------------------------------------
@mcp.resource("janus://senior/{id}/today", mime_type="application/json")
def get_senior_today_resource(id: str) -> str:
    """Read-only summary resource providing today's non-clinical routine timeline and metrics."""
    logger.info("Reading resource janus://senior/%s/today", id)
    identity = get_current_identity()
    if not check_senior_access(identity, id):
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="get_senior_today_resource",
            senior_id=id,
            transaction_id=None,
            outcome="FORBIDDEN",
        )
        return json.dumps({
            "status": "error",
            "error_code": ErrorCode.FORBIDDEN,
            "message": f"Access to senior '{id}' is forbidden for actor '{audit_actor}'.",
            "database_writes": 0,
        })

    allowed, reason = check_role_access(identity, "read_resource", id)
    if not allowed:
        audit_actor = identity.get("actor", "anonymous") if identity else "anonymous"
        audit_role = identity.get("role", "unknown") if identity else "unknown"
        storage.record_audit_entry(
            actor=audit_actor,
            role=audit_role,
            tool="get_senior_today_resource",
            senior_id=id,
            transaction_id=None,
            outcome="FORBIDDEN",
        )
        return json.dumps({
            "status": "error",
            "error_code": ErrorCode.FORBIDDEN,
            "message": reason,
            "database_writes": 0,
        })
    summary = storage.get_daily_summary(senior_id=id)
    return json.dumps(summary, indent=2)


# ---------------------------------------------------------------------------
# ASGI Application Factory & CORS Setup
# ---------------------------------------------------------------------------
def get_app(host: str = "0.0.0.0") -> Starlette:
    """Construct Starlette app mounting FastMCP v2 Streamable HTTP on /mcp with CORS and Auth."""
    # Ensure database is initialized
    storage.init_db()

    # Get streamable http app with stateless JSON-RPC response mode
    app = mcp.streamable_http_app(
        host=host,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    # Add AuthMiddleware first so it runs inside CORSMiddleware
    app.add_middleware(AuthMiddleware)

    # Add CORS middleware to support browser simulators and local tools
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "MCP-Protocol-Version"],
    )

    # Health check endpoint for container probes and reviewers
    async def health_endpoint(request: Any) -> JSONResponse:
        return JSONResponse({
            "status": "healthy",
            "service": "janus-mcp",
            "version": "0.1.0",
            "protocol": "2025-11-25",
        })

    app.add_route("/health", health_endpoint, methods=["GET"])

    demo_mode = os.environ.get("JANUS_DEMO_MODE", "0").strip() in ("1", "true", "True")
    admin_token = os.environ.get("JANUS_ADMIN_TOKEN")
    if not demo_mode and not admin_token:
        logger.warning(
            "SECURITY CONFIGURATION NOTICE: Neither JANUS_DEMO_MODE=1 nor JANUS_ADMIN_TOKEN is configured. "
            "All authenticated requests will be rejected with HTTP 401 until valid credentials are provided."
        )
    elif demo_mode:
        logger.info("JANUS_DEMO_MODE=1 active. Demo tokens (margaret_01, arthur_02) are enabled.")
    if admin_token:
        logger.info("JANUS_ADMIN_TOKEN loaded from environment.")

    return app


def run_server(host: str = "0.0.0.0", port: int = 8000, log_level: Optional[str] = None) -> None:
    """Launch the FastMCP server with uvicorn."""
    import uvicorn

    # If port is default 8000, allow PORT env var to override
    effective_port = port
    if port == 8000 and "PORT" in os.environ:
        try:
            effective_port = int(os.environ["PORT"])
        except ValueError:
            effective_port = port

    level = log_level or os.environ.get("JANUS_LOG_LEVEL", "info")
    logger.info("Starting Janus FastMCP v2 server on http://%s:%d/mcp ...", host, effective_port)
    app = get_app(host=host)
    try:
        uvicorn.run(app, host=host, port=effective_port, log_level=level)
    except OSError as e:
        if "10048" in str(e) or "address already in use" in str(e).lower():
            logger.error(
                "Port %d is already in use by another process. "
                "Please terminate the running process or start on a different port via JANUS_PORT or PORT environment variable.",
                effective_port,
            )
        else:
            raise


def main() -> None:
    """Console script entrypoint for janus-server and python -m janus.server."""
    host_env = os.environ.get("JANUS_HOST", "0.0.0.0")
    port_env = int(os.environ.get("PORT") or os.environ.get("JANUS_PORT") or "8000")
    level_env = os.environ.get("JANUS_LOG_LEVEL", "info")
    run_server(host=host_env, port=port_env, log_level=level_env)



if __name__ == "__main__":
    main()
