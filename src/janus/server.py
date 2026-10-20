"""Janus (ElderSync) — FastMCP v2 Server Entrypoint.

Implements the official Model Context Protocol (MCP spec 2025-11-25) over
Streamable HTTP (0.0.0.0:8000/mcp) with 4 core non-clinical tools and safety confirmation gates.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from mcp.server.mcpserver import MCPServer as FastMCP

from janus import storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] janus.server: %(message)s",
)
logger = logging.getLogger("janus.server")

# Initialize FastMCP Server instance
mcp = FastMCP(
    name="janus",
    instructions="Non-clinical caregiver synchronization and ambient elder daily routine logging server for Alexa+.",
)


# ---------------------------------------------------------------------------
# Tool 1: log_daily_routine
# ---------------------------------------------------------------------------
@mcp.tool()
async def log_daily_routine(
    senior_id: str,
    category: Optional[str] = None,
    details: str = "",
    timestamp: Optional[str] = None,
    routine_type: Optional[str] = None,
    notes: Optional[str] = None,
    logged_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Log non-clinical daily living events such as meals, hydration, vitamins, activity, or wellness.

    Validates input, creates a PENDING proposal, and writes NOTHING to routine_logs.
    Confirmation via verify_routine_state(confirm=True, transaction_id=...) is required to commit.

    Args:
        senior_id: Target senior identifier (e.g. 'margaret_01').
        category: Routine category: 'meal', 'hydration', 'vitamins', 'activity', 'wellness'.
        details: Additional description or quantity (e.g. '500ml water', 'Morning oatmeal').
        timestamp: Optional timestamp override.
        routine_type: Alias for category (backward compatibility).
        notes: Alias for details (backward compatibility).
        logged_by: Identifier of initiator ('senior_voice', 'caregiver_sarah', 'caregiver_david').

    Returns:
        Structured result containing transaction_id, status='pending_confirmation', preview, and spoken_prompt.
    """
    resolved_cat = category or routine_type
    if not resolved_cat:
        raise ValueError("Field 'category' is required.")

    validated_cat = storage.validate_category(resolved_cat)
    resolved_details = details or notes or ""
    actor = logged_by or "senior_voice"

    logger.info("log_daily_routine proposal: senior=%s, cat=%s, actor=%s", senior_id, validated_cat, actor)

    proposal = storage.create_proposal(
        senior_id=senior_id,
        action_type="routine_log",
        payload={
            "category": validated_cat,
            "details": resolved_details,
            "timestamp": timestamp,
            "actor": actor,
        },
        actor=actor,
    )

    tx_id = proposal["transaction_id"]
    senior = storage.get_senior(senior_id)
    senior_name = senior["name"] if senior else senior_id.replace("_", " ").title()

    spoken_prompt = (
        f"I have a pending note to record {validated_cat} ({resolved_details or 'completed'}) for {senior_name}. "
        "Would you like me to confirm and record this?"
    )

    preview = {
        "senior_id": senior_id,
        "category": validated_cat,
        "details": resolved_details,
        "timestamp": timestamp or proposal["created_at"],
        "actor": actor,
        "expires_at": proposal["expires_at"],
    }

    echo_show_card = {
        "card_type": "EchoShowCard",
        "title": f"Proposed: {validated_cat.title()}",
        "subtitle": f"Senior: {senior_name}",
        "body": resolved_details or f"{validated_cat.title()} pending confirmation.",
        "status": "Proposal Preview (0 Writes)",
        "transaction_id": tx_id,
    }

    return {
        "transaction_id": tx_id,
        "status": "pending_confirmation",
        "preview": preview,
        "spoken_prompt": spoken_prompt,
        "database_writes": 0,
        "echo_show_card": echo_show_card,
        "senior_id": senior_id,
        "routine_type": validated_cat,
        "category": validated_cat,
        "notes": resolved_details,
        "logged_by": actor,
    }


# ---------------------------------------------------------------------------
# Tool 2: get_caregiver_summary
# ---------------------------------------------------------------------------
@mcp.tool()
async def get_caregiver_summary(
    senior_id: str,
    date: Optional[str] = None,
    filter_status: str = "all",
) -> Dict[str, Any]:
    """Returns completed routines and pending steps formatted for Echo Show timeline cards.

    Args:
        senior_id: Target senior identifier (e.g. 'margaret_01').
        date: Target date in 'YYYY-MM-DD' format (defaults to current local date).
        filter_status: Filter slots by status: 'all', 'completed', or 'pending'.

    Returns:
        Aggregated summary including slot-level statuses, completion %, last_activity, and visual card payload.
    """
    logger.info("get_caregiver_summary: senior=%s, date=%s, filter=%s", senior_id, date, filter_status)
    summary = storage.get_daily_summary(senior_id=senior_id, target_date=date, filter_status=filter_status)
    return summary


# ---------------------------------------------------------------------------
# Tool 3: verify_routine_state
# ---------------------------------------------------------------------------
@mcp.tool()
async def verify_routine_state(
    confirm: bool = False,
    transaction_id: Optional[str] = None,
    senior_id: Optional[str] = None,
    action_type: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Enforces safety confirmation gates for state changes and shift handoffs.

    - confirm=False + (senior_id, action_type='shift_handoff', payload) -> creates a handoff proposal and returns preview + transaction_id.
    - confirm=False + transaction_id -> returns preview of that proposal, 0 writes.
    - confirm=True -> REQUIRES transaction_id of a live pending proposal. No payload accepted on commit.
      Unknown/expired/cancelled -> structured error, 0 writes.
      Atomic & Idempotent: a second confirm=True returns status 'ALREADY_COMMITTED' with result_id and 0 writes.

    Args:
        confirm: Confirmation flag. False for proposal preview; True for atomic commit.
        transaction_id: ID of a pending proposal ('tx_...'). Required when confirm=True.
        senior_id: Target senior identifier when creating a new proposal.
        action_type: Proposal action type ('shift_handoff', 'routine_log').
        payload: Action payload when creating a new handoff proposal. Ignored on commit.

    Returns:
        Structured preview dictionary (confirm=False) or committed record confirmation (confirm=True).
    """
    logger.info(
        "verify_routine_state: confirm=%s, tx=%s, senior=%s, action=%s",
        confirm,
        transaction_id,
        senior_id,
        action_type,
    )

    # -----------------------------------------------------------------------
    # Case 1: Proposal Preview by Transaction ID (confirm=False + transaction_id)
    # -----------------------------------------------------------------------
    if not confirm and transaction_id:
        prop = storage.get_proposal(transaction_id)
        if not prop:
            return {
                "status": "error",
                "error_code": "PROPOSAL_NOT_FOUND",
                "message": f"Proposal '{transaction_id}' was not found.",
                "database_writes": 0,
            }

        act_type = prop["action_type"]
        s_id = prop["senior_id"]
        prop_payload = prop.get("payload", {})
        actor = prop.get("actor", "caregiver")

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
        else:
            cat = prop_payload.get("category", "wellness")
            det = prop_payload.get("details", "")
            spoken_prompt = f"Pending note to log {cat} ({det}). Would you like to confirm?"
            preview_summary = f"Routine proposal: {cat} ({det})."

        return {
            "status": "PROPOSAL_PREVIEW",
            "transaction_id": transaction_id,
            "confirm_required": True,
            "action_type": act_type,
            "senior_id": s_id,
            "proposed_payload": prop_payload,
            "database_writes": 0,
            "preview_summary": preview_summary,
            "spoken_prompt": spoken_prompt,
            "expires_at": prop["expires_at"],
            "instructions": f"To commit this action, re-invoke verify_routine_state with confirm=True and transaction_id='{transaction_id}'.",
        }

    # -----------------------------------------------------------------------
    # Case 2: Create New Proposal Preview (confirm=False + senior_id)
    # -----------------------------------------------------------------------
    if not confirm:
        if not senior_id:
            return {
                "status": "error",
                "error_code": "INVALID_ARGUMENTS",
                "message": "verify_routine_state with confirm=False requires either transaction_id or senior_id.",
                "database_writes": 0,
            }

        act_type = action_type or "shift_handoff"
        payload_data = payload or {}
        summary = storage.get_daily_summary(senior_id=senior_id)
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

        prop = storage.create_proposal(
            senior_id=senior_id,
            action_type=act_type,
            payload=full_payload,
            actor=departing,
        )
        tx_id = prop["transaction_id"]

        senior = storage.get_senior(senior_id)
        senior_name = senior["name"] if senior else senior_id.replace("_", " ").title()

        spoken_prompt = (
            f"{senior_name} currently has {len(pending_names)} pending routine items "
            f"({', '.join(pending_names) if pending_names else 'all daily routines completed'}). "
            f"Do you confirm handing off care from {departing} to {incoming} with notes: '{notes}'?"
        )

        return {
            "status": "PROPOSAL_PREVIEW",
            "transaction_id": tx_id,
            "confirm_required": True,
            "action_type": act_type,
            "senior_id": senior_id,
            "proposed_payload": full_payload,
            "routine_snapshot": snapshot,
            "database_writes": 0,
            "preview_summary": f"Shift handoff proposal: {departing} -> {incoming}. Pending items: {len(pending_names)}.",
            "spoken_prompt": spoken_prompt,
            "expires_at": prop["expires_at"],
            "instructions": f"To commit this action, re-invoke verify_routine_state with confirm=True and transaction_id='{tx_id}'.",
        }

    # -----------------------------------------------------------------------
    # Case 3: Atomic Confirmed Commit (confirm=True)
    # -----------------------------------------------------------------------
    if not transaction_id:
        return {
            "status": "error",
            "error_code": "MISSING_TRANSACTION_ID",
            "message": "confirm=True REQUIRES a valid transaction_id of a live pending proposal. No unconfirmed payload accepted on commit.",
            "database_writes": 0,
        }

    commit_res = storage.commit_proposal(transaction_id=transaction_id)
    if commit_res["status"] == "error":
        return commit_res
    if commit_res["status"] == "ALREADY_COMMITTED":
        return commit_res

    # Successfully committed
    committed_rec = commit_res["committed_record"]
    act_type = commit_res["action_type"]
    s_id = commit_res["senior_id"]

    if act_type == "shift_handoff":
        departing = committed_rec.get("departing_caregiver", "Caregiver")
        incoming = committed_rec.get("incoming_caregiver", "Caregiver")
        notes = committed_rec.get("handoff_notes", "")
        echo_show_card = {
            "card_type": "EchoShowHandoffCard",
            "title": "Caregiver Shift Handoff Confirmed",
            "departing": departing,
            "incoming": incoming,
            "notes": notes,
            "timestamp": commit_res["timestamp"],
            "icon": "shield-check",
        }
        spoken_response = f"Caregiver shift handoff from {departing} to {incoming} has been verified and recorded."
    else:
        rtype = committed_rec.get("routine_type", "Routine")
        echo_show_card = {
            "card_type": "EchoShowCard",
            "title": f"Logged: {rtype.title()}",
            "body": committed_rec.get("notes", ""),
            "timestamp": commit_res["timestamp"],
            "icon": "check-circle",
        }
        spoken_response = f"{rtype.title()} routine has been verified and recorded."

    return {
        "status": "COMMITTED",
        "transaction_id": transaction_id,
        "action_type": act_type,
        "senior_id": s_id,
        "result_id": commit_res["result_id"],
        "database_writes": 1,
        "committed_record": committed_rec,
        "echo_show_card": echo_show_card,
        "spoken_response": spoken_response,
    }


# ---------------------------------------------------------------------------
# Tool 4: flag_missed_routine
# ---------------------------------------------------------------------------
@mcp.tool()
async def flag_missed_routine(
    senior_id: str,
    threshold_hours: int = 1,
    routine_name: Optional[str] = None,
    scheduled_time: Optional[str] = None,
    urgency_level: str = "medium",
) -> Dict[str, Any]:
    """Scans overdue slots older than threshold_hours and emits deduplicated escalation alerts.

    Escalation ladder:
      - Level 0: Gentle voice prompt (overdue >= threshold_hours)
      - Level 1: Display banner (overdue >= threshold_hours + step)
      - Level 2: Caregiver timeline alert (overdue >= threshold_hours + 2*step)

    Persists in alerts with dedupe (same slot+day+level is never re-emitted).
    Uses strictly non-alarm, gentle wording.

    Args:
        senior_id: Target senior identifier (e.g. 'margaret_01').
        threshold_hours: Minimum hours overdue before escalating alerts (default 1).
        routine_name: Optional specific routine name or category to check.
        scheduled_time: Optional expected time window string (e.g. '14:00').
        urgency_level: Urgency level ('low', 'medium', 'high').

    Returns:
        Escalation alert payload formatted for gentle ambient prompts and display banners.
    """
    logger.info(
        "flag_missed_routine: senior=%s, threshold=%s, routine=%s, time=%s, urgency=%s",
        senior_id,
        threshold_hours,
        routine_name,
        scheduled_time,
        urgency_level,
    )

    senior = storage.get_senior(senior_id)
    senior_name = senior["name"] if senior else senior_id.replace("_", " ").title()
    first_name = senior_name.split()[0]

    # If routine_name is specified, perform targeted single-routine verification
    if routine_name:
        summary = storage.get_daily_summary(senior_id=senior_id)
        slots = summary.get("slots", [])

        # Check if routine_name matches a specific slot by label or slot_id
        matching_slot = None
        for s in slots:
            if s["label"].lower() == routine_name.lower() or s["slot_id"].lower() == routine_name.lower():
                matching_slot = s
                break

        if matching_slot:
            is_missed = (matching_slot["status"] != "completed")
            display_time = scheduled_time or f"{matching_slot['window_start']} - {matching_slot['window_end']}"
            slot_label = matching_slot["label"]
        elif routine_name.lower() in storage.VALID_CATEGORIES:
            is_missed = routine_name.lower() not in summary.get("completed_types", [])
            display_time = scheduled_time or "today"
            slot_label = routine_name.title()
        else:
            is_missed = routine_name.lower() not in summary.get("completed_types", [])
            display_time = scheduled_time or "scheduled time"
            slot_label = routine_name

        voice_prompt = (
            f"Hi {first_name}, whenever you're ready, it might be a good time for your {slot_label.lower()}."
            if is_missed
            else f"{slot_label} has already been logged for today."
        )

        alert_payload = {
            "type": "ambient_reminder",
            "voice_prompt": voice_prompt,
            "echo_show_banner": {
                "title": f"Routine Check-in: {slot_label}",
                "urgency": urgency_level,
                "scheduled_time": display_time,
                "senior_name": senior_name,
                "is_missed": is_missed,
                "action_button": f"Log {slot_label} Now",
            },
        }

        return {
            "status": "FLAGGED" if is_missed else "ALREADY_LOGGED",
            "senior_id": senior_id,
            "senior_name": senior_name,
            "routine_name": routine_name,
            "scheduled_time": display_time,
            "urgency_level": urgency_level,
            "is_missed": is_missed,
            "alert_payload": alert_payload,
            "message": (
                f"Passive reminder generated for {slot_label} (Urgency: {urgency_level})."
                if is_missed
                else f"{slot_label} was already verified as completed today."
            ),
        }

    # Multi-slot scan mode using scan_missed_routines
    scan_result = storage.scan_missed_routines(
        senior_id=senior_id,
        threshold_hours=threshold_hours,
    )

    top_alert = scan_result["alerts_emitted"][0] if scan_result["alerts_emitted"] else None
    if top_alert:
        alert_payload = {
            "type": "ambient_reminder",
            "voice_prompt": top_alert["message"],
            "echo_show_banner": {
                "title": f"Routine Check-in: {top_alert['label']}",
                "urgency": "medium",
                "scheduled_time": top_alert["channel"],
                "senior_name": senior_name,
                "is_missed": True,
                "action_button": f"Log {top_alert['label']} Now",
            },
        }
    else:
        alert_payload = {
            "type": "ambient_reminder",
            "voice_prompt": f"All scheduled routines are up to date for {first_name}.",
            "echo_show_banner": {
                "title": "All Routines Current",
                "urgency": "low",
                "scheduled_time": "Now",
                "senior_name": senior_name,
                "is_missed": False,
                "action_button": "View Timeline",
            },
        }

    res = dict(scan_result)
    res["alert_payload"] = alert_payload
    res["is_missed"] = bool(scan_result["alerts_emitted"] or scan_result["overdue_slots"])
    return res


# ---------------------------------------------------------------------------
# ASGI Application Factory & CORS Setup
# ---------------------------------------------------------------------------
def get_app(host: str = "0.0.0.0") -> Starlette:
    """Construct Starlette app mounting FastMCP v2 Streamable HTTP on /mcp with CORS."""
    # Ensure database is initialized
    storage.init_db()

    # Get streamable http app with stateless JSON-RPC response mode
    app = mcp.streamable_http_app(
        host=host,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    # Add CORS middleware to support browser simulators and local tools
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "MCP-Protocol-Version"],
    )

    return app


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Launch the FastMCP server with uvicorn."""
    import uvicorn

    logger.info("Starting Janus FastMCP v2 server on http://%s:%d/mcp ...", host, port)
    app = get_app(host=host)
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except OSError as e:
        if "10048" in str(e) or "address already in use" in str(e).lower():
            logger.error(
                "Port %d is already in use by another process. "
                "Please terminate the running process or start on a different port via JANUS_PORT environment variable.",
                port,
            )
        else:
            raise


def main() -> None:
    """Console script entrypoint for janus-server and python -m janus.server."""
    host_env = os.environ.get("JANUS_HOST", "0.0.0.0")
    port_env = int(os.environ.get("JANUS_PORT", "8000"))
    run_server(host=host_env, port=port_env)


if __name__ == "__main__":
    main()
