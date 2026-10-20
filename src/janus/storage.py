"""Janus (ElderSync) — SQLite Persistence Layer.

Provides local, zero-dependency persistence for senior profiles, daily routine logs,
and caregiver shift handoff records with sub-10ms query execution.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# Default database location in ./data/janus.db relative to repository root
DEFAULT_DB_PATH = os.environ.get(
    "JANUS_DB_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "data" / "janus.db")
)

# Canonical non-clinical routine categories (Do NOT use 'medication')
VALID_CATEGORIES = {"meal", "hydration", "vitamins", "activity", "wellness"}

# Module-level clock override for testing
_current_time_override: Optional[datetime] = None


def get_current_time(now: Optional[datetime] = None) -> datetime:
    """Return the current UTC datetime, respecting injected parameter or global override."""
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
    if _current_time_override is not None:
        return _current_time_override
    return datetime.now(timezone.utc)


def set_clock_override(now: Optional[datetime]) -> None:
    """Set or clear a global clock override for deterministic time-travel testing."""
    global _current_time_override
    if now is not None and now.tzinfo is None:
        _current_time_override = now.replace(tzinfo=timezone.utc)
    else:
        _current_time_override = now


def format_iso(dt: datetime) -> str:
    """Format a datetime in ISO 8601 UTC string format."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp_to_tz(ts: str | datetime, tz: ZoneInfo) -> datetime:
    """Parse an ISO or SQLite timestamp into a timezone-aware datetime in the target timezone."""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(tz)

    clean_ts = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(clean_ts)
    except Exception:
        dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def validate_category(category: str) -> str:
    """Validate and normalize a routine category against non-clinical boundaries."""
    if not category:
        raise ValueError("Routine category cannot be empty.")
    normalized = category.strip().lower()
    if normalized not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Non-clinical allowed categories are: "
            f"{', '.join(sorted(VALID_CATEGORIES))}."
        )
    return normalized


# Standard non-clinical daily expectations
DEFAULT_DAILY_ROUTINES = [
    {"type": "hydration", "name": "Morning Hydration", "window": "08:00 - 10:00", "urgency": "medium"},
    {"type": "meal", "name": "Breakfast", "window": "08:00 - 10:00", "urgency": "medium"},
    {"type": "vitamins", "name": "Morning Vitamins", "window": "09:00 - 11:00", "urgency": "high"},
    {"type": "activity", "name": "Morning Porch / Garden Walk", "window": "10:00 - 12:00", "urgency": "low"},
    {"type": "meal", "name": "Lunch", "window": "12:00 - 14:00", "urgency": "medium"},
    {"type": "hydration", "name": "Afternoon Hydration", "window": "14:00 - 16:00", "urgency": "high"},
    {"type": "meal", "name": "Dinner", "window": "18:00 - 20:00", "urgency": "medium"},
    {"type": "wellness", "name": "Evening Check-in", "window": "20:00 - 21:30", "urgency": "low"},
]

# Canonical slot schedule template seeded per senior
DEFAULT_SCHEDULE_SLOTS = [
    {
        "slot_id": "morning_hydration",
        "label": "Morning Hydration",
        "category": "hydration",
        "window_start": "08:00",
        "window_end": "10:00",
        "urgency": "medium",
    },
    {
        "slot_id": "breakfast",
        "label": "Breakfast",
        "category": "meal",
        "window_start": "08:00",
        "window_end": "10:00",
        "urgency": "medium",
    },
    {
        "slot_id": "morning_vitamins",
        "label": "Morning Vitamins",
        "category": "vitamins",
        "window_start": "09:00",
        "window_end": "11:00",
        "urgency": "high",
    },
    {
        "slot_id": "morning_walk",
        "label": "Morning Porch / Garden Walk",
        "category": "activity",
        "window_start": "10:00",
        "window_end": "12:00",
        "urgency": "low",
    },
    {
        "slot_id": "lunch",
        "label": "Lunch",
        "category": "meal",
        "window_start": "12:00",
        "window_end": "14:00",
        "urgency": "medium",
    },
    {
        "slot_id": "afternoon_hydration",
        "label": "Afternoon Hydration",
        "category": "hydration",
        "window_start": "14:00",
        "window_end": "16:00",
        "urgency": "high",
    },
    {
        "slot_id": "dinner",
        "label": "Dinner",
        "category": "meal",
        "window_start": "18:00",
        "window_end": "20:00",
        "urgency": "medium",
    },
    {
        "slot_id": "evening_checkin",
        "label": "Evening Check-in",
        "category": "wellness",
        "window_start": "20:00",
        "window_end": "21:30",
        "urgency": "low",
    },
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
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite database with seniors, routine_logs, shift_handoffs, proposals, routine_schedule, and alerts tables."""
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
                    tz TEXT NOT NULL DEFAULT 'America/New_York',
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

                CREATE TABLE IF NOT EXISTS proposals (
                    transaction_id TEXT PRIMARY KEY,
                    senior_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    committed_at DATETIME,
                    result_id INTEGER,
                    FOREIGN KEY (senior_id) REFERENCES seniors(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS routine_schedule (
                    senior_id TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    category TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    urgency TEXT NOT NULL DEFAULT 'medium',
                    PRIMARY KEY (senior_id, slot_id),
                    FOREIGN KEY (senior_id) REFERENCES seniors(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    senior_id TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (senior_id, slot_id, date, level),
                    FOREIGN KEY (senior_id) REFERENCES seniors(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_routine_senior_time
                ON routine_logs (senior_id, timestamp);

                CREATE INDEX IF NOT EXISTS idx_handoff_senior_time
                ON shift_handoffs (senior_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_proposals_status_expires
                ON proposals (status, expires_at);

                CREATE INDEX IF NOT EXISTS idx_schedule_senior
                ON routine_schedule (senior_id);

                CREATE INDEX IF NOT EXISTS idx_alerts_lookup
                ON alerts (senior_id, slot_id, date, level);
                """
            )

            # Migration: check if 'tz' column exists on seniors table
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(seniors)")
            cols = [r["name"] for r in cursor.fetchall()]
            if "tz" not in cols:
                cursor.execute("ALTER TABLE seniors ADD COLUMN tz TEXT NOT NULL DEFAULT 'America/New_York'")

            # Seed default senior profile for Margaret Vance if empty
            cursor.execute("SELECT id FROM seniors WHERE id = ?", ("margaret_01",))
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT INTO seniors (id, name, age, notes, tz)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "margaret_01",
                        "Margaret Vance",
                        78,
                        "Mild mobility friction; enjoys morning tea, porch walks, and daily hydration reminders.",
                        "America/New_York",
                    ),
                )
            
            # Seed default routine schedule for Margaret Vance
            for slot in DEFAULT_SCHEDULE_SLOTS:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO routine_schedule (
                        senior_id, slot_id, label, category, window_start, window_end, urgency
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "margaret_01",
                        slot["slot_id"],
                        slot["label"],
                        slot["category"],
                        slot["window_start"],
                        slot["window_end"],
                        slot["urgency"],
                    ),
                )
    finally:
        conn.close()


def get_senior(senior_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve senior profile by ID."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, age, notes, tz, created_at FROM seniors WHERE id = ?", (senior_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def get_senior_timezone(senior_id: str, db_path: Optional[str] = None) -> ZoneInfo:
    """Return the ZoneInfo timezone for a senior, defaulting to America/New_York."""
    senior = get_senior(senior_id, db_path=db_path)
    if senior and senior.get("tz"):
        try:
            return ZoneInfo(senior["tz"])
        except Exception:
            pass
    return ZoneInfo("America/New_York")


def set_senior_timezone(senior_id: str, tz_name: str, db_path: Optional[str] = None) -> None:
    """Update senior's IANA timezone."""
    ensure_senior_exists(senior_id, db_path=db_path)
    # Validate IANA timezone
    ZoneInfo(tz_name)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("UPDATE seniors SET tz = ? WHERE id = ?", (tz_name, senior_id))
    finally:
        conn.close()


def seed_default_schedule(senior_id: str, db_path: Optional[str] = None) -> None:
    """Seed default routine schedule slots for a senior if not already present."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            for slot in DEFAULT_SCHEDULE_SLOTS:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO routine_schedule (
                        senior_id, slot_id, label, category, window_start, window_end, urgency
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        senior_id,
                        slot["slot_id"],
                        slot["label"],
                        slot["category"],
                        slot["window_start"],
                        slot["window_end"],
                        slot["urgency"],
                    ),
                )
    finally:
        conn.close()


def get_schedule_slots(senior_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve schedule slots for a senior from routine_schedule."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT senior_id, slot_id, label, category, window_start, window_end, urgency
            FROM routine_schedule
            WHERE senior_id = ?
            ORDER BY window_start ASC
            """,
            (senior_id,),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def ensure_senior_exists(
    senior_id: str,
    name: Optional[str] = None,
    tz: str = "America/New_York",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure senior profile exists, creating a default one and seeding schedule if necessary."""
    senior = get_senior(senior_id, db_path=db_path)
    if senior:
        # Ensure default schedule exists
        if not get_schedule_slots(senior_id, db_path=db_path):
            seed_default_schedule(senior_id, db_path=db_path)
        return senior

    conn = get_connection(db_path)
    try:
        with conn:
            display_name = name or senior_id.replace("_", " ").title()
            conn.execute(
                """
                INSERT OR IGNORE INTO seniors (id, name, age, notes, tz)
                VALUES (?, ?, ?, ?, ?)
                """,
                (senior_id, display_name, 75, "Auto-registered household member", tz),
            )
        seed_default_schedule(senior_id, db_path=db_path)
        return get_senior(senior_id, db_path=db_path) or {
            "id": senior_id,
            "name": display_name,
            "age": 75,
            "notes": "Auto-registered household member",
            "tz": tz,
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
    filter_status: str = "all",
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve daily routine timeline, slot-level statuses, completion %, and last activity in senior's local time."""
    ensure_senior_exists(senior_id, db_path=db_path)
    senior = get_senior(senior_id, db_path=db_path)
    senior_tz = get_senior_timezone(senior_id, db_path=db_path)
    senior_name = senior["name"] if senior else senior_id.replace("_", " ").title()

    now_utc = get_current_time(now)
    now_local = now_utc.astimezone(senior_tz)

    if target_date:
        date_str = target_date
        target_date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        target_date_obj = now_local.date()
        date_str = target_date_obj.isoformat()

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, routine_type, value, logged_by, notes, timestamp
            FROM routine_logs
            WHERE senior_id = ?
            ORDER BY timestamp ASC
            """,
            (senior_id,),
        )
        rows = cursor.fetchall()
        all_logs = [dict(r) for r in rows]
    finally:
        conn.close()

    # Filter logs strictly to those occurring on target_date in senior's local timezone
    events_today = []
    for ev in all_logs:
        ev_local_dt = parse_timestamp_to_tz(ev["timestamp"], senior_tz)
        if ev_local_dt.date() == target_date_obj:
            ev_copy = dict(ev)
            ev_copy["local_timestamp"] = ev_local_dt.isoformat()
            events_today.append(ev_copy)

    # Get schedule slots for senior
    slots = get_schedule_slots(senior_id, db_path=db_path)
    if not slots:
        seed_default_schedule(senior_id, db_path=db_path)
        slots = get_schedule_slots(senior_id, db_path=db_path)

    # Aggregate metrics across today's confirmed events
    completed_types = set()
    hydration_count = 0
    meals_logged = []
    vitamins_logged = False
    mobility_events = []

    for ev in events_today:
        rtype = ev["routine_type"].lower()
        completed_types.add(rtype)
        if rtype == "hydration":
            hydration_count += 1
        elif rtype == "meal":
            meals_logged.append(ev.get("value") or ev.get("notes") or "Meal")
        elif rtype == "vitamins":
            vitamins_logged = True
        elif rtype in ("activity", "walk", "mobility"):
            mobility_events.append(ev.get("value") or ev.get("notes") or "Activity")

    # Evaluate each slot window (+/- 30 min grace) against confirmed events
    evaluated_slots = []
    completed_slots_count = 0

    for slot in slots:
        start_h, start_m = map(int, slot["window_start"].split(":"))
        end_h, end_m = map(int, slot["window_end"].split(":"))
        start_dt = datetime(target_date_obj.year, target_date_obj.month, target_date_obj.day, start_h, start_m, tzinfo=senior_tz)
        end_dt = datetime(target_date_obj.year, target_date_obj.month, target_date_obj.day, end_h, end_m, tzinfo=senior_tz)
        grace_start = start_dt - timedelta(minutes=30)
        grace_end = end_dt + timedelta(minutes=30)

        # A slot is COMPLETED only if a confirmed event of that category falls inside [grace_start, grace_end]
        matching_event = None
        for ev in events_today:
            if ev["routine_type"].lower() == slot["category"].lower():
                ev_local_dt = parse_timestamp_to_tz(ev["timestamp"], senior_tz)
                if grace_start <= ev_local_dt <= grace_end:
                    matching_event = ev
                    break

        if matching_event:
            status = "completed"
            completed_slots_count += 1
            completed_at = matching_event["timestamp"]
            event_id = matching_event["id"]
        else:
            completed_at = None
            event_id = None
            if now_local < start_dt:
                status = "upcoming"
            elif now_local <= grace_end:
                status = "due"
            else:
                status = "overdue"

        evaluated_slots.append({
            "slot_id": slot["slot_id"],
            "label": slot["label"],
            "category": slot["category"],
            "window_start": slot["window_start"],
            "window_end": slot["window_end"],
            "urgency": slot["urgency"],
            "status": status,
            "completed_at": completed_at,
            "event_id": event_id,
        })

    total_slots = len(evaluated_slots)
    completion_pct = round((completed_slots_count / total_slots) * 100, 1) if total_slots > 0 else 0.0
    last_activity = events_today[-1]["timestamp"] if events_today else None

    # Filter slots if requested
    if filter_status == "completed":
        filtered_slots = [s for s in evaluated_slots if s["status"] == "completed"]
    elif filter_status == "pending":
        filtered_slots = [s for s in evaluated_slots if s["status"] != "completed"]
    else:
        filtered_slots = evaluated_slots

    pending_routines = [
        {
            "slot_id": s["slot_id"],
            "type": s["category"],
            "name": s["label"],
            "window": f"{s['window_start']} - {s['window_end']}",
            "urgency": s["urgency"],
            "status": s["status"],
        }
        for s in evaluated_slots
        if s["status"] != "completed"
    ]

    visual_card = {
        "card_type": "EchoShowTimelineCard",
        "title": f"Daily Routine Summary — {senior_name}",
        "date": date_str,
        "status_headline": (
            f"{len(events_today)} activities recorded today ({completion_pct}% completed)"
            if events_today
            else "No routines logged yet today"
        ),
        "stats": {
            "hydration_entries": hydration_count,
            "meals_count": len(meals_logged),
            "vitamins_completed": vitamins_logged,
            "mobility_entries": len(mobility_events),
            "total_events": len(events_today),
            "completion_percentage": completion_pct,
        },
        "recent_events": events_today[-5:] if events_today else [],
        "pending_count": len(pending_routines),
        "pending_routines": pending_routines,
        "last_activity": last_activity,
    }

    return {
        "status": "success",
        "senior_id": senior_id,
        "senior_name": senior_name,
        "date": date_str,
        "timezone": str(senior_tz),
        "filter_status": filter_status,
        "total_slots": total_slots,
        "completed_count": completed_slots_count,
        "pending_count": total_slots - completed_slots_count,
        "completion_percentage": completion_pct,
        "last_activity": last_activity,
        "total_events": len(events_today),
        "events": events_today,
        "slots": filtered_slots,
        "completed_types": sorted(list(completed_types)),
        "pending_routines": pending_routines,
        "visual_card": visual_card,
    }


def scan_missed_routines(
    senior_id: str,
    threshold_hours: int = 1,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Scan overdue slots older than threshold_hours and emit deduplicated escalation alerts.

    Escalation ladder:
      - Level 0: Gentle voice prompt (overdue >= threshold_hours)
      - Level 1: Display banner (overdue >= threshold_hours + step)
      - Level 2: Caregiver timeline alert (overdue >= threshold_hours + 2*step)

    Persists in `alerts` table with dedupe (UNIQUE on senior_id, slot_id, date, level).
    Uses strictly non-alarm, gentle wording.
    """
    ensure_senior_exists(senior_id, db_path=db_path)
    senior = get_senior(senior_id, db_path=db_path)
    senior_tz = get_senior_timezone(senior_id, db_path=db_path)
    senior_name = senior["name"] if senior else senior_id.replace("_", " ").title()
    first_name = senior_name.split()[0]

    now_utc = get_current_time(now)
    now_local = now_utc.astimezone(senior_tz)
    today_str = now_local.date().isoformat()

    summary = get_daily_summary(senior_id=senior_id, target_date=today_str, now=now, db_path=db_path)
    slots = summary.get("slots", [])

    overdue_slots = []
    emitted_alerts = []

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        for slot in slots:
            if slot["status"] != "overdue":
                continue

            end_h, end_m = map(int, slot["window_end"].split(":"))
            end_dt = datetime(now_local.year, now_local.month, now_local.day, end_h, end_m, tzinfo=senior_tz)
            grace_end = end_dt + timedelta(minutes=30)
            overdue_seconds = (now_local - grace_end).total_seconds()
            overdue_hours = overdue_seconds / 3600.0

            if overdue_hours < threshold_hours:
                continue

            overdue_slots.append({
                "slot_id": slot["slot_id"],
                "label": slot["label"],
                "overdue_hours": round(overdue_hours, 2),
            })

            # Check existing alerts for (senior_id, slot_id, today_str)
            cursor.execute(
                """
                SELECT level FROM alerts
                WHERE senior_id = ? AND slot_id = ? AND date = ?
                """,
                (senior_id, slot["slot_id"], today_str),
            )
            existing_levels = {r["level"] for r in cursor.fetchall()}

            # Determine escalation level from elapsed overdue duration
            step = max(1, threshold_hours)
            if overdue_hours < threshold_hours + step:
                target_level = 0
            elif overdue_hours < threshold_hours + 2 * step:
                target_level = 1
            else:
                target_level = 2

            # Dedupe: same slot+day+level is never re-emitted
            if target_level in existing_levels:
                continue

            # Non-alarm gentle messaging per level
            slot_label = slot["label"]
            if target_level == 0:
                channel = "gentle_voice_prompt"
                message = f"Hi {first_name}, whenever you're ready, it might be a good time for your {slot_label.lower()}."
            elif target_level == 1:
                channel = "display_banner"
                message = f"Gentle reminder: {slot_label} window has passed. Tap when complete."
            else:
                channel = "caregiver_timeline"
                message = f"{senior_name} has not logged {slot_label.lower()} today. Consider checking in when convenient."

            ts_iso = format_iso(now_utc)
            try:
                cursor.execute(
                    """
                    INSERT INTO alerts (senior_id, slot_id, date, level, channel, message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (senior_id, slot["slot_id"], today_str, target_level, channel, message, ts_iso),
                )
                conn.commit()
                emitted_alerts.append({
                    "alert_id": cursor.lastrowid,
                    "senior_id": senior_id,
                    "slot_id": slot["slot_id"],
                    "label": slot_label,
                    "date": today_str,
                    "level": target_level,
                    "channel": channel,
                    "message": message,
                    "overdue_hours": round(overdue_hours, 2),
                    "created_at": ts_iso,
                })
            except sqlite3.IntegrityError:
                # Deduplication catch (unique constraint)
                pass
    finally:
        conn.close()

    status = "FLAGGED" if emitted_alerts else ("DEDUPLICATED" if overdue_slots else "NO_OVERDUE")
    return {
        "status": status,
        "senior_id": senior_id,
        "senior_name": senior_name,
        "date": today_str,
        "threshold_hours": threshold_hours,
        "overdue_count": len(overdue_slots),
        "overdue_slots": overdue_slots,
        "alerts_count": len(emitted_alerts),
        "alerts_emitted": emitted_alerts,
        "message": (
            f"Emitted {len(emitted_alerts)} routine alert(s) for {senior_name}."
            if emitted_alerts
            else (
                f"All overdue routine alerts already emitted for {senior_name} (deduplicated)."
                if overdue_slots
                else f"No routines overdue past {threshold_hours}h for {senior_name}."
            )
        ),
    }


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


# ---------------------------------------------------------------------------
# Two-Step Proposal Gate Functions (Strict Single-Writer Pattern)
# ---------------------------------------------------------------------------

def create_proposal(
    senior_id: str,
    action_type: str,
    payload: Dict[str, Any],
    actor: str = "senior_voice",
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new pending proposal in the proposals table.

    Writes NOTHING to routine_logs or shift_handoffs tables.
    """
    ensure_senior_exists(senior_id, db_path=db_path)
    now_dt = get_current_time(now)
    expires_dt = now_dt + timedelta(minutes=5)

    created_at = format_iso(now_dt)
    expires_at = format_iso(expires_dt)
    tx_id = "tx_" + uuid.uuid4().hex

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO proposals (
                    transaction_id, senior_id, action_type, payload_json,
                    actor, created_at, expires_at, status, committed_at, result_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL)
                """,
                (tx_id, senior_id, action_type, json.dumps(payload), actor, created_at, expires_at),
            )
        return {
            "transaction_id": tx_id,
            "senior_id": senior_id,
            "action_type": action_type,
            "payload": payload,
            "actor": actor,
            "created_at": created_at,
            "expires_at": expires_at,
            "status": "pending",
        }
    finally:
        conn.close()


def get_proposal(
    transaction_id: str,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve proposal by transaction_id. Does NOT change state (0 database writes)."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT transaction_id, senior_id, action_type, payload_json,
                   actor, created_at, expires_at, status, committed_at, result_id
            FROM proposals
            WHERE transaction_id = ?
            """,
            (transaction_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["payload"] = json.loads(d["payload_json"])
        except Exception:
            d["payload"] = {}

        now_dt = get_current_time(now)
        current_iso = format_iso(now_dt)
        if d["status"] == "pending" and d["expires_at"] <= current_iso:
            d["is_expired"] = True
        else:
            d["is_expired"] = False
        return d
    finally:
        conn.close()


def cancel_proposal(
    transaction_id: str,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Cancel a live pending proposal."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE proposals
                SET status = 'cancelled'
                WHERE transaction_id = ? AND status = 'pending'
                """,
                (transaction_id,),
            )
            if cursor.rowcount > 0:
                return {
                    "status": "success",
                    "transaction_id": transaction_id,
                    "message": "Proposal cancelled.",
                    "database_writes": 1,
                }
            cursor.execute("SELECT status FROM proposals WHERE transaction_id = ?", (transaction_id,))
            row = cursor.fetchone()
            if not row:
                return {
                    "status": "error",
                    "error_code": "PROPOSAL_NOT_FOUND",
                    "message": f"Proposal '{transaction_id}' does not exist.",
                    "database_writes": 0,
                }
            return {
                "status": "error",
                "error_code": f"PROPOSAL_{row['status'].upper()}",
                "message": f"Proposal is already {row['status']}.",
                "database_writes": 0,
            }
    finally:
        conn.close()


def commit_proposal(
    transaction_id: str,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomically commit a live pending proposal and write the record to the target ledger.

    This is the ONLY code path in the system that writes confirmed records to
    routine_logs and shift_handoffs.
    """
    now_dt = get_current_time(now)
    now_iso = format_iso(now_dt)

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()

            # Step 1: Atomic state transition from 'pending' -> 'committed'
            cursor.execute(
                """
                UPDATE proposals
                SET status = 'committed', committed_at = ?
                WHERE transaction_id = ? AND status = 'pending' AND expires_at > ?
                """,
                (now_iso, transaction_id, now_iso),
            )

            if cursor.rowcount == 0:
                # Did not transition: diagnose status
                cursor.execute(
                    """
                    SELECT transaction_id, senior_id, action_type, payload_json,
                           actor, created_at, expires_at, status, committed_at, result_id
                    FROM proposals
                    WHERE transaction_id = ?
                    """,
                    (transaction_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return {
                        "status": "error",
                        "error_code": "PROPOSAL_NOT_FOUND",
                        "message": f"Proposal '{transaction_id}' does not exist.",
                        "database_writes": 0,
                    }

                status = row["status"]
                expires_at = row["expires_at"]

                if status == "committed":
                    return {
                        "status": "ALREADY_COMMITTED",
                        "transaction_id": transaction_id,
                        "action_type": row["action_type"],
                        "senior_id": row["senior_id"],
                        "result_id": row["result_id"],
                        "database_writes": 0,
                        "message": f"Proposal '{transaction_id}' has already been committed.",
                    }
                elif status == "cancelled":
                    return {
                        "status": "error",
                        "error_code": "PROPOSAL_CANCELLED",
                        "transaction_id": transaction_id,
                        "message": f"Proposal '{transaction_id}' was cancelled.",
                        "database_writes": 0,
                    }
                elif status == "pending" and expires_at <= now_iso:
                    cursor.execute(
                        "UPDATE proposals SET status = 'expired' WHERE transaction_id = ?",
                        (transaction_id,),
                    )
                    return {
                        "status": "error",
                        "error_code": "PROPOSAL_EXPIRED",
                        "transaction_id": transaction_id,
                        "message": f"Proposal '{transaction_id}' has expired.",
                        "database_writes": 0,
                    }
                elif status == "expired":
                    return {
                        "status": "error",
                        "error_code": "PROPOSAL_EXPIRED",
                        "transaction_id": transaction_id,
                        "message": f"Proposal '{transaction_id}' has expired.",
                        "database_writes": 0,
                    }
                else:
                    return {
                        "status": "error",
                        "error_code": f"PROPOSAL_{status.upper()}",
                        "transaction_id": transaction_id,
                        "message": f"Proposal '{transaction_id}' is in status '{status}'.",
                        "database_writes": 0,
                    }

            # Step 2: Successfully transitioned: insert into target table in same transaction
            cursor.execute(
                """
                SELECT transaction_id, senior_id, action_type, payload_json, actor
                FROM proposals
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            )
            prop = dict(cursor.fetchone())
            payload = json.loads(prop["payload_json"])
            senior_id = prop["senior_id"]
            action_type = prop["action_type"]
            actor = prop["actor"]

            result_id = None
            committed_record: Dict[str, Any] = {}

            if action_type == "routine_log":
                category = payload.get("category", "wellness")
                details = payload.get("details", "")
                ts = payload.get("timestamp") or now_iso
                cursor.execute(
                    """
                    INSERT INTO routine_logs (senior_id, routine_type, value, logged_by, notes, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (senior_id, category, details, actor, details, ts),
                )
                result_id = cursor.lastrowid
                committed_record = {
                    "event_id": result_id,
                    "senior_id": senior_id,
                    "routine_type": category,
                    "value": details,
                    "logged_by": actor,
                    "notes": details,
                    "timestamp": ts,
                }
            elif action_type == "shift_handoff":
                departing = payload.get("departing_caregiver", "Caregiver")
                incoming = payload.get("incoming_caregiver", "Caregiver")
                notes = payload.get("handoff_notes", "Caregiver shift handoff completed.")
                snapshot_json = json.dumps(payload.get("routine_snapshot", {}))
                cursor.execute(
                    """
                    INSERT INTO shift_handoffs (
                        senior_id, departing_caregiver, incoming_caregiver,
                        routine_snapshot, handoff_notes, confirmed, created_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (senior_id, departing, incoming, snapshot_json, notes, now_iso),
                )
                result_id = cursor.lastrowid
                committed_record = {
                    "handoff_id": result_id,
                    "senior_id": senior_id,
                    "departing_caregiver": departing,
                    "incoming_caregiver": incoming,
                    "handoff_notes": notes,
                    "confirmed": True,
                    "timestamp": now_iso,
                }
            else:
                raise ValueError(f"Unknown proposal action_type: {action_type}")

            cursor.execute(
                "UPDATE proposals SET result_id = ? WHERE transaction_id = ?",
                (result_id, transaction_id),
            )

        return {
            "status": "COMMITTED",
            "transaction_id": transaction_id,
            "action_type": action_type,
            "senior_id": senior_id,
            "result_id": result_id,
            "database_writes": 1,
            "committed_record": committed_record,
            "timestamp": now_iso,
        }
    finally:
        conn.close()
