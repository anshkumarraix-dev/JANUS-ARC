"""Janus (ElderSync) — SQLite Persistence Layer.

Provides local, zero-dependency persistence for senior profiles, daily routine logs,
and caregiver shift handoff records with sub-10ms query execution.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Default database location in ./data/janus.db relative to repository root
DEFAULT_DB_PATH = os.environ.get(
    "JANUS_DB_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "data" / "janus.db")
)

# Standard non-clinical daily expectations
DEFAULT_DAILY_ROUTINES = [
    {"type": "hydration", "name": "Morning Hydration", "window": "08:00 - 10:00", "urgency": "medium"},
    {"type": "meal", "name": "Breakfast", "window": "08:00 - 10:00", "urgency": "medium"},
    {"type": "vitamins", "name": "Morning Vitamins", "window": "09:00 - 11:00", "urgency": "high"},
    {"type": "walk", "name": "Morning Porch / Garden Walk", "window": "10:00 - 12:00", "urgency": "low"},
    {"type": "meal", "name": "Lunch", "window": "12:00 - 14:00", "urgency": "medium"},
    {"type": "hydration", "name": "Afternoon Hydration", "window": "14:00 - 16:00", "urgency": "high"},
    {"type": "meal", "name": "Dinner", "window": "18:00 - 20:00", "urgency": "medium"},
    {"type": "wellness", "name": "Evening Check-in", "window": "20:00 - 21:30", "urgency": "low"},
]


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return a configured SQLite connection with row factory enabled."""
    target_path = db_path or DEFAULT_DB_PATH
    dir_name = os.path.dirname(target_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    conn = sqlite3.connect(target_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite database with seniors, routine_logs, and shift_handoffs tables."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS seniors (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    age INTEGER,
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS routine_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    senior_id TEXT NOT NULL,
                    routine_type TEXT NOT NULL,
                    value TEXT,
                    logged_by TEXT NOT NULL,
                    notes TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (senior_id) REFERENCES seniors(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS shift_handoffs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    senior_id TEXT NOT NULL,
                    departing_caregiver TEXT NOT NULL,
                    incoming_caregiver TEXT NOT NULL,
                    routine_snapshot TEXT NOT NULL,
                    handoff_notes TEXT NOT NULL,
                    confirmed BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (senior_id) REFERENCES seniors(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_routine_senior_time 
                ON routine_logs (senior_id, timestamp);

                CREATE INDEX IF NOT EXISTS idx_handoff_senior_time 
                ON shift_handoffs (senior_id, created_at);
                """
            )

            # Seed default senior profile for Margaret Vance if empty
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM seniors WHERE id = ?", ("margaret_01",))
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT INTO seniors (id, name, age, notes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        "margaret_01",
                        "Margaret Vance",
                        78,
                        "Mild mobility friction; enjoys morning tea, porch walks, and daily hydration reminders.",
                    ),
                )
    finally:
        conn.close()


def get_senior(senior_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve senior profile by ID."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, age, notes, created_at FROM seniors WHERE id = ?", (senior_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def ensure_senior_exists(senior_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Ensure senior profile exists, creating a default one if necessary."""
    senior = get_senior(senior_id, db_path=db_path)
    if senior:
        return senior

    conn = get_connection(db_path)
    try:
        with conn:
            display_name = senior_id.replace("_", " ").title()
            conn.execute(
                """
                INSERT OR IGNORE INTO seniors (id, name, age, notes)
                VALUES (?, ?, ?, ?)
                """,
                (senior_id, display_name, 75, "Auto-registered household member"),
            )
        return get_senior(senior_id, db_path=db_path) or {
            "id": senior_id,
            "name": display_name,
            "age": 75,
            "notes": "Auto-registered household member",
        }
    finally:
        conn.close()


def log_routine_event(
    senior_id: str,
    routine_type: str,
    logged_by: str,
    notes: str = "",
    value: str = "",
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a new non-clinical routine event into SQLite.

    Returns the inserted event summary with ID and timestamp.
    """
    ensure_senior_exists(senior_id, db_path=db_path)
    ts = timestamp or datetime.now(timezone.utc).isoformat()

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO routine_logs (senior_id, routine_type, value, logged_by, notes, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (senior_id, routine_type.lower(), value, logged_by, notes, ts),
            )
            event_id = cursor.lastrowid

        return {
            "status": "success",
            "event_id": event_id,
            "senior_id": senior_id,
            "routine_type": routine_type.lower(),
            "value": value,
            "logged_by": logged_by,
            "notes": notes,
            "timestamp": ts,
            "message": f"Successfully logged {routine_type} for senior '{senior_id}'.",
        }
    finally:
        conn.close()


def get_daily_summary(
    senior_id: str,
    target_date: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve daily routine timeline, completed actions, and pending steps for a given date."""
    ensure_senior_exists(senior_id, db_path=db_path)
    senior = get_senior(senior_id, db_path=db_path)

    # Use specified date or current UTC date (YYYY-MM-DD)
    date_str = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, routine_type, value, logged_by, notes, timestamp
            FROM routine_logs
            WHERE senior_id = ? AND date(timestamp) = date(?)
            ORDER BY timestamp ASC
            """,
            (senior_id, date_str),
        )
        rows = cursor.fetchall()

        events: List[Dict[str, Any]] = [dict(r) for r in rows]

        # Group completed types and calculate aggregates
        completed_types = set()
        hydration_count = 0
        meals_logged = []
        vitamins_logged = False
        mobility_events = []

        for ev in events:
            rtype = ev["routine_type"].lower()
            completed_types.add(rtype)
            if rtype == "hydration":
                hydration_count += 1
            elif rtype == "meal":
                meals_logged.append(ev.get("value") or ev.get("notes") or "Meal")
            elif rtype == "vitamins":
                vitamins_logged = True
            elif rtype in ("walk", "mobility"):
                mobility_events.append(ev.get("value") or ev.get("notes") or "Walk/Mobility")

        # Determine pending expected routines
        pending_routines = []
        for expected in DEFAULT_DAILY_ROUTINES:
            if expected["type"] not in completed_types:
                pending_routines.append(expected)

        # Build Echo Show glanceable visual card structure
        visual_card = {
            "card_type": "EchoShowTimelineCard",
            "title": f"Daily Routine Summary — {senior['name'] if senior else senior_id}",
            "date": date_str,
            "status_headline": (
                f"{len(events)} activities recorded today"
                if events
                else "No routines logged yet today"
            ),
            "stats": {
                "hydration_entries": hydration_count,
                "meals_count": len(meals_logged),
                "vitamins_completed": vitamins_logged,
                "mobility_entries": len(mobility_events),
                "total_events": len(events),
            },
            "recent_events": events[-5:] if events else [],
            "pending_count": len(pending_routines),
            "pending_routines": pending_routines,
        }

        return {
            "status": "success",
            "senior_id": senior_id,
            "senior_name": senior["name"] if senior else senior_id,
            "date": date_str,
            "total_events": len(events),
            "events": events,
            "completed_types": sorted(list(completed_types)),
            "pending_routines": pending_routines,
            "visual_card": visual_card,
        }
    finally:
        conn.close()


def record_shift_handoff(
    senior_id: str,
    departing_caregiver: str,
    incoming_caregiver: str,
    handoff_notes: str,
    routine_snapshot: Optional[Dict[str, Any]] = None,
    confirmed: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a verified caregiver shift handoff in the SQLite ledger."""
    ensure_senior_exists(senior_id, db_path=db_path)
    snapshot_json = json.dumps(routine_snapshot or {})
    ts = datetime.now(timezone.utc).isoformat()

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO shift_handoffs (
                    senior_id, departing_caregiver, incoming_caregiver,
                    routine_snapshot, handoff_notes, confirmed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    senior_id,
                    departing_caregiver,
                    incoming_caregiver,
                    snapshot_json,
                    handoff_notes,
                    1 if confirmed else 0,
                    ts,
                ),
            )
            handoff_id = cursor.lastrowid

        return {
            "status": "success",
            "handoff_id": handoff_id,
            "senior_id": senior_id,
            "departing_caregiver": departing_caregiver,
            "incoming_caregiver": incoming_caregiver,
            "handoff_notes": handoff_notes,
            "confirmed": confirmed,
            "timestamp": ts,
            "message": f"Caregiver shift handoff to {incoming_caregiver} recorded successfully.",
        }
    finally:
        conn.close()


def get_latest_handoff(
    senior_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent shift handoff for a senior."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, senior_id, departing_caregiver, incoming_caregiver,
                   routine_snapshot, handoff_notes, confirmed, created_at
            FROM shift_handoffs
            WHERE senior_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (senior_id,),
        )
        row = cursor.fetchone()
        if row:
            d = dict(row)
            try:
                d["routine_snapshot"] = json.loads(d["routine_snapshot"])
            except Exception:
                pass
            return d
        return None
    finally:
        conn.close()
