"""JANUS-ARC — SQLite Persistence Layer.

Provides local, zero-dependency persistence for senior profiles, daily routine logs,
and caregiver shift handoff records with sub-10ms query execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional,Tuple
from zoneinfo import ZoneInfo

from janus.errors import AuditWriteError, InvalidCategoryError, SafetyBlockedError
from janus.safety import SafetyOutcome, assess_safety
from janus.auth import AuthError, get_current_identity, check_senior_access, check_role_access

# Default database location in ./data/janus.db relative to repository root
DEFAULT_DB_PATH = os.environ.get(
    "JANUS_DB_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "data" / "janus.db")
)

# Canonical non-clinical routine categories (Do NOT use 'medication')
VALID_CATEGORIES = {"meal", "hydration", "vitamins", "activity", "wellness"}

# Proposal expiration TTL in seconds (5 minutes = 300 seconds)
PROPOSAL_TTL_SECONDS = 300

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
        raise InvalidCategoryError("empty")
    normalized = category.strip().lower()
    if normalized not in VALID_CATEGORIES:
        raise InvalidCategoryError(category)
    return normalized


def compute_audit_hash(prev_hash: str, row_data: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash for audit log chain."""
    canonical = prev_hash + json.dumps(row_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _append_audit_row_in_tx(
    cursor: sqlite3.Cursor,
    ts: str,
    actor: str,
    role: str,
    tool: str,
    senior_id: Optional[str],
    transaction_id: Optional[str],
    outcome: str,
    reason_code: Optional[str] = None,
    mutation_committed: bool = False,
) -> str:
    """Append a cryptographic audit log row within an existing active transaction.

    Returns the computed new_hash.
    """
    cursor.execute("SELECT id, hash FROM audit_log ORDER BY id DESC LIMIT 1")
    last_audit = cursor.fetchone()
    prev_hash = last_audit["hash"] if last_audit else ("0" * 64)
    last_id = last_audit["id"] if last_audit else 0
    audit_id = last_id + 1

    audit_row = {
        "actor": actor,
        "id": audit_id,
        "mutation_committed": bool(mutation_committed),
        "outcome": outcome,
        "reason_code": reason_code,
        "role": role,
        "senior_id": senior_id,
        "tool": tool,
        "transaction_id": transaction_id,
        "ts": ts,
    }
    new_hash = compute_audit_hash(prev_hash, audit_row)
    cursor.execute(
        """
        INSERT INTO audit_log (ts, actor, role, tool, senior_id, transaction_id, outcome, reason_code, mutation_committed, prev_hash, hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ts, actor, role, tool, senior_id, transaction_id, outcome, reason_code, 1 if mutation_committed else 0, prev_hash, new_hash),
    )
    return new_hash


def record_audit_entry(
    actor: str,
    role: str,
    tool: str,
    senior_id: Optional[str],
    transaction_id: Optional[str],
    outcome: str,
    reason_code: Optional[str] = None,
    mutation_committed: bool = False,
    db_path: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Append a cryptographic tamper-evident record to the audit_log table."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            new_hash = _append_audit_row_in_tx(
                cursor=cursor,
                ts=format_iso(get_current_time(now)),
                actor=actor,
                role=role,
                tool=tool,
                senior_id=senior_id,
                transaction_id=transaction_id,
                outcome=outcome,
                reason_code=reason_code,
                mutation_committed=mutation_committed,
            )
            return {"id": cursor.lastrowid, "hash": new_hash}
    except Exception as e:
        if isinstance(e, AuditWriteError):
            raise
        raise AuditWriteError("Cryptographic audit logging failed. Operation cannot proceed without audit integrity.") from None
    finally:
        conn.close()



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
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite database with seniors, routine_logs, shift_handoffs, proposals, routine_schedule, and alerts tables."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
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

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    role TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    senior_id TEXT,
                    transaction_id TEXT,
                    outcome TEXT NOT NULL,
                    reason_code TEXT,
                    mutation_committed BOOLEAN NOT NULL DEFAULT 0,
                    prev_hash TEXT NOT NULL,
                    hash TEXT NOT NULL
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

                CREATE INDEX IF NOT EXISTS idx_audit_time
                ON audit_log (ts);

                CREATE INDEX IF NOT EXISTS idx_audit_outcome
                ON audit_log (outcome);

                CREATE INDEX IF NOT EXISTS idx_audit_tx
                ON audit_log (transaction_id);
                """
            )

            # Migration: check if 'tz' column exists on seniors table
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(seniors)")
            cols = [r["name"] for r in cursor.fetchall()]
            if "tz" not in cols:
                cursor.execute("ALTER TABLE seniors ADD COLUMN tz TEXT NOT NULL DEFAULT 'America/New_York'")

            # Migration: check if 'reason_code' and 'mutation_committed' columns exist on audit_log
            cursor.execute("PRAGMA table_info(audit_log)")
            audit_cols = [r["name"] for r in cursor.fetchall()]
            if "reason_code" not in audit_cols:
                cursor.execute("ALTER TABLE audit_log ADD COLUMN reason_code TEXT")
            if "mutation_committed" not in audit_cols:
                cursor.execute("ALTER TABLE audit_log ADD COLUMN mutation_committed BOOLEAN NOT NULL DEFAULT 0")

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

            # Seed default senior profile for Arthur Davis if empty
            cursor.execute("SELECT id FROM seniors WHERE id = ?", ("arthur_02",))
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT INTO seniors (id, name, age, notes, tz)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "arthur_02",
                        "Arthur Davis",
                        82,
                        "Independent living; prefers afternoon walks and evening routine reminders.",
                        "America/New_York",
                    ),
                )

            # Seed default routine schedule for Arthur Davis
            for slot in DEFAULT_SCHEDULE_SLOTS:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO routine_schedule (
                        senior_id, slot_id, label, category, window_start, window_end, urgency
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "arthur_02",
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


_senior_cache: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
_schedule_slots_cache: Dict[Tuple[str, Optional[str]], List[Dict[str, Any]]] = {}


def clear_caches() -> None:
    """Clear in-memory caches (used in testing and dynamic profile reloads)."""
    _senior_cache.clear()
    _schedule_slots_cache.clear()


def get_senior(senior_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve senior profile by ID."""
    cache_key = (senior_id, db_path)
    if cache_key in _senior_cache:
        return dict(_senior_cache[cache_key])

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, age, notes, tz, created_at FROM seniors WHERE id = ?", (senior_id,))
        row = cursor.fetchone()
        if row:
            res = dict(row)
            _senior_cache[cache_key] = res
            return dict(res)
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
    _senior_cache.pop((senior_id, db_path), None)
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
    cache_key = (senior_id, db_path)
    if cache_key in _schedule_slots_cache:
        return [dict(s) for s in _schedule_slots_cache[cache_key]]

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
        res = [dict(r) for r in rows]
        if res:
            _schedule_slots_cache[cache_key] = res
        return [dict(r) for r in res]
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
    combined_text = f"{value or ''} {notes or ''}".strip()
    safety_res = assess_safety(combined_text, category=routine_type)
    if safety_res.outcome != SafetyOutcome.ROUTINE_ALLOWED:
        record_audit_entry(
            actor=logged_by,
            role="caregiver" if "caregiver" in logged_by else "senior",
            tool="log_routine_event",
            senior_id=senior_id,
            transaction_id=None,
            outcome=f"BLOCKED_{safety_res.outcome.value}",
            reason_code=safety_res.matched_rule or safety_res.outcome.value,
            mutation_committed=False,
            db_path=db_path,
        )
        raise SafetyBlockedError(safety_res.outcome.value, safety_res.guidance, safety_res.matched_rule)

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

    from janus.apl import build_caregiver_summary_card
    next_slot_label = pending_routines[0].get("name") if pending_routines else None
    apl_card, display_card = build_caregiver_summary_card(
        senior_id=senior_id,
        senior_name=senior_name,
        date=date_str,
        completion_percentage=completion_pct,
        completed_count=completed_slots_count,
        total_count=total_slots,
        next_slot=next_slot_label,
    )

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
        "apl": apl_card,
        "display": display_card,
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
    safety_res = assess_safety(handoff_notes, category="wellness")
    if safety_res.outcome != SafetyOutcome.ROUTINE_ALLOWED:
        record_audit_entry(
            actor=departing_caregiver,
            role="caregiver",
            tool="record_shift_handoff",
            senior_id=senior_id,
            transaction_id=None,
            outcome=f"BLOCKED_{safety_res.outcome.value}",
            reason_code=safety_res.matched_rule or safety_res.outcome.value,
            mutation_committed=False,
            db_path=db_path,
        )
        raise SafetyBlockedError(safety_res.outcome.value, safety_res.guidance, safety_res.matched_rule)

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

    identity = get_current_identity()
    if identity and not check_senior_access(identity, senior_id):
        raise AuthError(f"Access to senior '{senior_id}' is forbidden for actor '{identity.get('actor', 'anonymous')}'.")

    # Medical safety policy guard before creating any proposal
    if action_type == "routine_log":
        text_to_check = payload.get("details") or payload.get("notes") or ""
        cat_to_check = payload.get("category") or payload.get("routine_type")
        safety_res = assess_safety(text_to_check, category=cat_to_check)
        if safety_res.outcome != SafetyOutcome.ROUTINE_ALLOWED:
            audit_actor = identity.get("actor", actor) if identity else actor
            audit_role = identity.get("role", "caregiver" if "caregiver" in audit_actor else "senior") if identity else ("caregiver" if "caregiver" in audit_actor else "senior")
            record_audit_entry(
                actor=audit_actor,
                role=audit_role,
                tool="create_proposal",
                senior_id=senior_id,
                transaction_id=None,
                outcome=f"BLOCKED_{safety_res.outcome.value}",
                reason_code=safety_res.matched_rule or safety_res.outcome.value,
                mutation_committed=False,
                db_path=db_path,
                now=now,
            )
            raise SafetyBlockedError(safety_res.outcome.value, safety_res.guidance, safety_res.matched_rule)
    elif action_type == "shift_handoff":
        notes_to_check = payload.get("handoff_notes") or ""
        safety_res = assess_safety(notes_to_check, category="wellness")
        if safety_res.outcome != SafetyOutcome.ROUTINE_ALLOWED:
            audit_actor = identity.get("actor", actor) if identity else actor
            audit_role = identity.get("role", "caregiver") if identity else "caregiver"
            record_audit_entry(
                actor=audit_actor,
                role=audit_role,
                tool="create_proposal",
                senior_id=senior_id,
                transaction_id=None,
                outcome=f"BLOCKED_{safety_res.outcome.value}",
                reason_code=safety_res.matched_rule or safety_res.outcome.value,
                mutation_committed=False,
                db_path=db_path,
                now=now,
            )
            raise SafetyBlockedError(safety_res.outcome.value, safety_res.guidance, safety_res.matched_rule)

    now_dt = get_current_time(now)
    expires_dt = now_dt + timedelta(seconds=PROPOSAL_TTL_SECONDS)

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

            # Step 1: Diagnose proposal status and revalidate safety
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

            senior_id = row["senior_id"]
            action_type = row["action_type"]
            actor = row["actor"]

            identity = get_current_identity()
            if identity:
                if not check_senior_access(identity, senior_id):
                    return {
                        "status": "error",
                        "error_code": "FORBIDDEN",
                        "message": f"Access to senior '{senior_id}' is forbidden for actor '{identity.get('actor', 'anonymous')}'.",
                        "database_writes": 0,
                        "transaction_id": transaction_id,
                    }
                check_action = "confirm_handoff" if action_type == "shift_handoff" else "confirm_routine"
                allowed, reason = check_role_access(identity, check_action, senior_id)
                if not allowed:
                    return {
                        "status": "error",
                        "error_code": "FORBIDDEN",
                        "message": reason,
                        "database_writes": 0,
                        "transaction_id": transaction_id,
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
                _append_audit_row_in_tx(
                    cursor=cursor,
                    ts=now_iso,
                    actor=actor,
                    role="caregiver" if "caregiver" in actor else "senior",
                    tool="verify_routine_state",
                    senior_id=senior_id,
                    transaction_id=transaction_id,
                    outcome="CONFIRMATION_FAILED",
                    reason_code="PROPOSAL_CANCELLED",
                    mutation_committed=False,
                )
                return {
                    "status": "error",
                    "error_code": "PROPOSAL_CANCELLED",
                    "transaction_id": transaction_id,
                    "message": f"Proposal '{transaction_id}' was cancelled.",
                    "database_writes": 0,
                }
            elif status == "blocked":
                _append_audit_row_in_tx(
                    cursor=cursor,
                    ts=now_iso,
                    actor=actor,
                    role="caregiver" if "caregiver" in actor else "senior",
                    tool="verify_routine_state",
                    senior_id=senior_id,
                    transaction_id=transaction_id,
                    outcome="CONFIRMATION_FAILED",
                    reason_code="PROPOSAL_BLOCKED",
                    mutation_committed=False,
                )
                return {
                    "status": "error",
                    "error_code": "PROPOSAL_BLOCKED",
                    "transaction_id": transaction_id,
                    "message": f"Proposal '{transaction_id}' was blocked by medical safety policy.",
                    "database_writes": 0,
                }
            elif status == "pending" and expires_at <= now_iso:
                cursor.execute(
                    "UPDATE proposals SET status = 'expired' WHERE transaction_id = ?",
                    (transaction_id,),
                )
                _append_audit_row_in_tx(
                    cursor=cursor,
                    ts=now_iso,
                    actor=actor,
                    role="caregiver" if "caregiver" in actor else "senior",
                    tool="verify_routine_state",
                    senior_id=senior_id,
                    transaction_id=transaction_id,
                    outcome="CONFIRMATION_FAILED",
                    reason_code="PROPOSAL_EXPIRED",
                    mutation_committed=False,
                )
                return {
                    "status": "error",
                    "error_code": "PROPOSAL_EXPIRED",
                    "transaction_id": transaction_id,
                    "message": f"Proposal '{transaction_id}' has expired.",
                    "database_writes": 0,
                }
            elif status == "expired":
                _append_audit_row_in_tx(
                    cursor=cursor,
                    ts=now_iso,
                    actor=actor,
                    role="caregiver" if "caregiver" in actor else "senior",
                    tool="verify_routine_state",
                    senior_id=senior_id,
                    transaction_id=transaction_id,
                    outcome="CONFIRMATION_FAILED",
                    reason_code="PROPOSAL_EXPIRED",
                    mutation_committed=False,
                )
                return {
                    "status": "error",
                    "error_code": "PROPOSAL_EXPIRED",
                    "transaction_id": transaction_id,
                    "message": f"Proposal '{transaction_id}' has expired.",
                    "database_writes": 0,
                }
            elif status != "pending":
                _append_audit_row_in_tx(
                    cursor=cursor,
                    ts=now_iso,
                    actor=actor,
                    role="caregiver" if "caregiver" in actor else "senior",
                    tool="verify_routine_state",
                    senior_id=senior_id,
                    transaction_id=transaction_id,
                    outcome="CONFIRMATION_FAILED",
                    reason_code=f"PROPOSAL_{status.upper()}",
                    mutation_committed=False,
                )
                return {
                    "status": "error",
                    "error_code": f"PROPOSAL_{status.upper()}",
                    "transaction_id": transaction_id,
                    "message": f"Proposal '{transaction_id}' is in status '{status}'.",
                    "database_writes": 0,
                }

            # Step 2: Revalidate stored proposal details against safety policy before commit
            prop = dict(row)
            payload = json.loads(prop["payload_json"])
            senior_id = prop["senior_id"]
            action_type = prop["action_type"]
            actor = prop["actor"]

            if action_type == "routine_log":
                text_to_check = payload.get("details") or payload.get("notes") or ""
                cat_to_check = payload.get("category") or payload.get("routine_type")
            elif action_type == "shift_handoff":
                text_to_check = payload.get("handoff_notes") or ""
                cat_to_check = "wellness"
            else:
                text_to_check = ""
                cat_to_check = None

            safety_res = assess_safety(text_to_check, category=cat_to_check)
            if safety_res.outcome != SafetyOutcome.ROUTINE_ALLOWED:
                # Mark proposal as blocked so it can never be committed
                cursor.execute(
                    "UPDATE proposals SET status = 'blocked' WHERE transaction_id = ?",
                    (transaction_id,),
                )
                audit_role = "caregiver" if "caregiver" in actor else "senior"
                _append_audit_row_in_tx(
                    cursor=cursor,
                    ts=now_iso,
                    actor=actor,
                    role=audit_role,
                    tool="verify_routine_state",
                    senior_id=senior_id,
                    transaction_id=transaction_id,
                    outcome=f"BLOCKED_{safety_res.outcome.value}",
                    reason_code=safety_res.matched_rule or safety_res.outcome.value,
                    mutation_committed=False,
                )
                return {
                    "status": "error",
                    "error_code": safety_res.outcome.value,
                    "message": safety_res.guidance,
                    "database_writes": 0,
                    "transaction_id": transaction_id,
                }

            # Step 3: Safety revalidation passed! Atomically transition from 'pending' -> 'committed'
            cursor.execute(
                """
                UPDATE proposals
                SET status = 'committed', committed_at = ?
                WHERE transaction_id = ? AND status = 'pending' AND expires_at > ?
                """,
                (now_iso, transaction_id, now_iso),
            )
            if cursor.rowcount == 0:
                return {
                    "status": "error",
                    "error_code": "PROPOSAL_STATE_CONFLICT",
                    "message": "Proposal state transitioned concurrently.",
                    "database_writes": 0,
                }

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

            # Record tamper-evident audit log entry in same transaction
            committing_actor = identity.get("actor") if (identity and identity.get("actor")) else actor
            committing_role = identity.get("role") if (identity and identity.get("role")) else ("caregiver" if "caregiver" in committing_actor else "senior")
            _append_audit_row_in_tx(
                cursor=cursor,
                ts=now_iso,
                actor=committing_actor,
                role=committing_role,
                tool="verify_routine_state",
                senior_id=senior_id,
                transaction_id=transaction_id,
                outcome="COMMITTED",
                reason_code="ROUTINE_COMMITTED",
                mutation_committed=True,
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
    except Exception as e:
        if isinstance(e, AuditWriteError):
            raise
        raise AuditWriteError("Cryptographic audit logging failed during proposal commit.") from None
    finally:
        conn.close()
