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
    routine_type: str,
    logged_by: str,
    notes: str = "",
) -> Dict[str, Any]:
    """Log non-clinical daily living events such as meals, hydration, vitamins, or walking habits.

    Args:
        senior_id: Target senior identifier (e.g. 'margaret_01').
        routine_type: Type of routine ('hydration', 'meal', 'vitamins', 'walk', 'mobility', 'wellness').
        logged_by: Identifier of initiator ('senior_voice', 'caregiver_sarah', 'caregiver_david').
        notes: Additional description or quantity (e.g. '500ml water', 'Finished morning oatmeal').

    Returns:
        Structured result containing event ID, timestamp, and Echo Show visual card payload.
    """
    logger.info("log_daily_routine: senior=%s, type=%s, by=%s", senior_id, routine_type, logged_by)

    event = storage.log_routine_event(
        senior_id=senior_id,
        routine_type=routine_type,
        logged_by=logged_by,
        notes=notes,
        value=notes,
    )

    echo_show_card = {
        "card_type": "EchoShowCard",
        "title": f"Logged: {routine_type.title()}",
        "subtitle": f"Senior: {senior_id.replace('_', ' ').title()}",
        "body": notes or f"{routine_type.title()} event successfully recorded.",
        "logged_by": logged_by,
        "timestamp": event["timestamp"],
        "icon": "check-circle",
    }

    return {
        "status": "success",
        "event_id": event["event_id"],
        "senior_id": senior_id,
        "routine_type": routine_type.lower(),
        "logged_by": logged_by,
        "notes": notes,
        "timestamp": event["timestamp"],
        "echo_show_card": echo_show_card,
        "message": f"Successfully logged {routine_type} for senior '{senior_id}'.",
    }


# ---------------------------------------------------------------------------
# Tool 2: get_caregiver_summary
# ---------------------------------------------------------------------------
@mcp.tool()
async def get_caregiver_summary(
    senior_id: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns completed routines and pending steps formatted for Echo Show timeline cards.

    Args:
        senior_id: Target senior identifier (e.g. 'margaret_01').
        date: Target date in 'YYYY-MM-DD' format (defaults to current date).

    Returns:
        Aggregated summary including event count, pending expected routines, and visual card payload.
    """
    logger.info("get_caregiver_summary: senior=%s, date=%s", senior_id, date)
    summary = storage.get_daily_summary(senior_id=senior_id, target_date=date)
    return summary


# ---------------------------------------------------------------------------
# Tool 3: verify_routine_state
# ---------------------------------------------------------------------------
@mcp.tool()
async def verify_routine_state(
    senior_id: str,
    action_type: str,
    payload: Dict[str, Any],
    confirm: bool = False,
) -> Dict[str, Any]:
    """Enforces safety confirmation gates for state changes or shift handoffs.

    Returns 'PROPOSAL_PREVIEW' when confirm=False (0 database writes).
    Commits state transaction to SQLite when confirm=True.

    Args:
        senior_id: Target senior identifier (e.g. 'margaret_01').
        action_type: Action type ('shift_handoff', 'schedule_override', 'routine_update').
        payload: Action payload containing relevant fields (e.g. departing_caregiver, incoming_caregiver, handoff_notes).
        confirm: Confirmation flag. Set to False for preview; set to True following verbal/touch consent.

    Returns:
        Proposal preview with pending checklist when unconfirmed, or committed record confirmation.
    """
    logger.info(
        "verify_routine_state: senior=%s, action=%s, confirm=%s",
        senior_id,
        action_type,
        confirm,
    )

    summary = storage.get_daily_summary(senior_id=senior_id)

    # -----------------------------------------------------------------------
    # Step 1: Read-Only Proposal Preview (Safety Gate)
    # -----------------------------------------------------------------------
    if not confirm:
        pending_names = [r["name"] for r in summary.get("pending_routines", [])]
        departing = payload.get("departing_caregiver", "Current Caregiver")
        incoming = payload.get("incoming_caregiver", "Next Caregiver")
        notes = payload.get("handoff_notes", "No shift notes provided")

        spoken_prompt = (
            f"Margaret Vance currently has {len(pending_names)} pending routine items "
            f"({', '.join(pending_names) if pending_names else 'all daily routines completed'}). "
            f"Do you confirm handing off care from {departing} to {incoming} with notes: '{notes}'?"
        )

        return {
            "status": "PROPOSAL_PREVIEW",
            "confirm_required": True,
            "action_type": action_type,
            "senior_id": senior_id,
            "proposed_payload": payload,
            "routine_snapshot": {
                "completed": summary.get("completed_types", []),
                "total_events": summary.get("total_events", 0),
                "pending_count": len(pending_names),
                "pending_routines": pending_names,
            },
            "database_writes": 0,
            "preview_summary": (
                f"Shift handoff proposal: {departing} -> {incoming}. "
                f"Pending items: {len(pending_names)}."
            ),
            "spoken_prompt": spoken_prompt,
            "instructions": "To commit this action to the ledger, re-invoke verify_routine_state with confirm=True.",
        }

    # -----------------------------------------------------------------------
    # Step 2: Confirmed Database Transaction Execution
    # -----------------------------------------------------------------------
    departing = payload.get("departing_caregiver", "Caregiver")
    incoming = payload.get("incoming_caregiver", "Caregiver")
    notes = payload.get("handoff_notes", "Caregiver shift handoff completed.")
    snapshot = {
        "completed": summary.get("completed_types", []),
        "total_events": summary.get("total_events", 0),
        "pending_routines": [r["name"] for r in summary.get("pending_routines", [])],
    }

    handoff = storage.record_shift_handoff(
        senior_id=senior_id,
        departing_caregiver=departing,
        incoming_caregiver=incoming,
        handoff_notes=notes,
        routine_snapshot=snapshot,
        confirmed=True,
    )

    echo_show_card = {
        "card_type": "EchoShowHandoffCard",
        "title": "Caregiver Shift Handoff Confirmed",
        "departing": departing,
        "incoming": incoming,
        "notes": notes,
        "timestamp": handoff["timestamp"],
        "icon": "shield-check",
    }

    return {
        "status": "COMMITTED",
        "action_type": action_type,
        "senior_id": senior_id,
        "database_writes": 1,
        "committed_record": handoff,
        "echo_show_card": echo_show_card,
        "spoken_response": f"Caregiver shift handoff from {departing} to {incoming} has been verified and recorded.",
    }


# ---------------------------------------------------------------------------
# Tool 4: flag_missed_routine
# ---------------------------------------------------------------------------
@mcp.tool()
async def flag_missed_routine(
    senior_id: str,
    routine_name: str,
    scheduled_time: str,
    urgency_level: str = "medium",
) -> Dict[str, Any]:
    """Triggers passive notifications for missed non-clinical routine check-ins.

    Args:
        senior_id: Target senior identifier (e.g. 'margaret_01').
        routine_name: Name or type of routine expected (e.g. 'Afternoon Hydration', 'Morning Vitamins').
        scheduled_time: Expected time window string (e.g. '14:00' or '2:00 PM').
        urgency_level: Urgency level ('low', 'medium', 'high').

    Returns:
        Alert payload formatted for Alexa+ ambient gentle voice prompts and smart display banners.
    """
    logger.info(
        "flag_missed_routine: senior=%s, routine=%s, time=%s, urgency=%s",
        senior_id,
        routine_name,
        scheduled_time,
        urgency_level,
    )

    summary = storage.get_daily_summary(senior_id=senior_id)
    completed_types = summary.get("completed_types", [])

    # Check if a matching event was recorded
    target_lower = routine_name.lower()
    is_missed = True
    for ctype in completed_types:
        if ctype in target_lower or target_lower in ctype:
            is_missed = False
            break

    senior = storage.get_senior(senior_id)
    senior_name = senior["name"] if senior else senior_id.replace("_", " ").title()

    voice_prompt = (
        f"Hi {senior_name.split()[0]}, it's past {scheduled_time} and your {routine_name} "
        f"has not been logged yet. Would you like me to record that for you now?"
        if is_missed
        else f"{routine_name} has already been logged for today."
    )

    alert_payload = {
        "type": "ambient_reminder",
        "voice_prompt": voice_prompt,
        "echo_show_banner": {
            "title": f"Routine Check-in: {routine_name}",
            "urgency": urgency_level,
            "scheduled_time": scheduled_time,
            "senior_name": senior_name,
            "is_missed": is_missed,
            "action_button": f"Log {routine_name} Now",
        },
    }

    return {
        "status": "FLAGGED" if is_missed else "ALREADY_LOGGED",
        "senior_id": senior_id,
        "routine_name": routine_name,
        "scheduled_time": scheduled_time,
        "urgency_level": urgency_level,
        "is_missed": is_missed,
        "alert_payload": alert_payload,
        "message": (
            f"Passive reminder generated for {routine_name} (Urgency: {urgency_level})."
            if is_missed
            else f"{routine_name} was already verified as completed today."
        ),
    }


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
