"""JANUS-ARC — Schedule, Timezone, and Missed Routine Tests.

Verifies:
1. Breakfast does not clear lunch or dinner (category slot window isolation).
2. Morning water does not clear afternoon hydration slot.
3. Timezone boundary: IST 02:00 belongs to the correct local day, not UTC previous day.
4. Missed routine escalation ladder & deduplication (same slot+day+level is never re-emitted).
5. Unconfirmed proposals are strictly ignored in summary and completion calculations.
6. Caregiver summary filter_status ('all' | 'completed' | 'pending') correctness.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

import pytest

# Ensure src directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from janus import storage  # noqa: E402
from janus.server import (  # noqa: E402
    get_caregiver_summary,
    log_daily_routine,
    verify_routine_state,
)


@pytest.fixture(autouse=True)
def isolated_schedule_db(monkeypatch):
    """Create an isolated temporary SQLite database for each test and reset clock override."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_schedule_janus.db")
    monkeypatch.setattr(storage, "DEFAULT_DB_PATH", test_db_path)
    storage.set_clock_override(None)
    storage.init_db(test_db_path)
    yield test_db_path
    storage.set_clock_override(None)
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Test 1: Breakfast doesn't clear dinner
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_breakfast_does_not_clear_dinner(isolated_schedule_db):
    """Assert that logging Breakfast only completes the Breakfast slot, not Lunch or Dinner."""
    senior_id = "margaret_01"  # Default America/New_York (UTC-4 in EDT)
    target_date = "2026-10-20"

    # 08:30 EDT = 12:30 UTC: Within Breakfast window (08:00 - 10:00, grace 07:30 - 10:30)
    p = await log_daily_routine(
        senior_id=senior_id,
        category="meal",
        details="Oatmeal with berries",
        timestamp="2026-10-20T12:30:00Z",
    )
    commit_res = await verify_routine_state(confirm=True, transaction_id=p["transaction_id"])
    assert commit_res["status"] == "COMMITTED"

    # Check summary at 09:00 EDT (13:00 UTC)
    clock_0900 = datetime(2026, 10, 20, 13, 0, 0, tzinfo=timezone.utc)
    storage.set_clock_override(clock_0900)

    summary = await get_caregiver_summary(senior_id, date=target_date)
    assert summary["status"] == "success"
    assert summary["total_events"] == 1

    slots_by_id = {s["slot_id"]: s for s in summary["slots"]}

    # Breakfast MUST be completed
    assert slots_by_id["breakfast"]["status"] == "completed"
    assert slots_by_id["breakfast"]["completed_at"] == "2026-10-20T12:30:00Z"

    # Lunch and Dinner MUST NOT be completed
    assert slots_by_id["lunch"]["status"] == "upcoming"
    assert slots_by_id["lunch"]["completed_at"] is None
    assert slots_by_id["dinner"]["status"] == "upcoming"
    assert slots_by_id["dinner"]["completed_at"] is None

    # Check summary at 19:00 EDT (23:00 UTC): Dinner window (18:00 - 20:00) is currently DUE
    clock_1900 = datetime(2026, 10, 20, 23, 0, 0, tzinfo=timezone.utc)
    storage.set_clock_override(clock_1900)

    summary_evening = await get_caregiver_summary(senior_id, date=target_date)
    evening_slots = {s["slot_id"]: s for s in summary_evening["slots"]}
    assert evening_slots["breakfast"]["status"] == "completed"
    assert evening_slots["lunch"]["status"] == "overdue"
    assert evening_slots["dinner"]["status"] == "due"


# ---------------------------------------------------------------------------
# Test 2: Morning water doesn't clear afternoon hydration slot
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_morning_water_does_not_clear_afternoon_slot(isolated_schedule_db):
    """Assert that a morning water log does not clear the Afternoon Hydration slot."""
    senior_id = "margaret_01"
    target_date = "2026-10-20"

    # 08:15 EDT = 12:15 UTC: Morning Hydration window (08:00 - 10:00)
    p1 = await log_daily_routine(
        senior_id=senior_id,
        category="hydration",
        details="400ml water",
        timestamp="2026-10-20T12:15:00Z",
    )
    await verify_routine_state(confirm=True, transaction_id=p1["transaction_id"])

    # At 09:00 EDT
    storage.set_clock_override(datetime(2026, 10, 20, 13, 0, 0, tzinfo=timezone.utc))
    summary = await get_caregiver_summary(senior_id, date=target_date)
    slots = {s["slot_id"]: s for s in summary["slots"]}

    assert slots["morning_hydration"]["status"] == "completed"
    assert slots["afternoon_hydration"]["status"] == "upcoming"
    assert slots["afternoon_hydration"]["completed_at"] is None

    # At 15:00 EDT (19:00 UTC): Afternoon Hydration window (14:00 - 16:00) is DUE
    storage.set_clock_override(datetime(2026, 10, 20, 19, 0, 0, tzinfo=timezone.utc))
    summary_pm = await get_caregiver_summary(senior_id, date=target_date)
    slots_pm = {s["slot_id"]: s for s in summary_pm["slots"]}
    assert slots_pm["morning_hydration"]["status"] == "completed"
    assert slots_pm["afternoon_hydration"]["status"] == "due"

    # Now log afternoon hydration at 14:45 EDT = 18:45 UTC
    p2 = await log_daily_routine(
        senior_id=senior_id,
        category="hydration",
        details="300ml lemon water",
        timestamp="2026-10-20T18:45:00Z",
    )
    await verify_routine_state(confirm=True, transaction_id=p2["transaction_id"])

    summary_done = await get_caregiver_summary(senior_id, date=target_date)
    slots_done = {s["slot_id"]: s for s in summary_done["slots"]}
    assert slots_done["morning_hydration"]["status"] == "completed"
    assert slots_done["afternoon_hydration"]["status"] == "completed"
    assert slots_done["afternoon_hydration"]["completed_at"] == "2026-10-20T18:45:00Z"


# ---------------------------------------------------------------------------
# Test 3: Timezone boundary (IST 02:00 belongs to the correct local day)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_timezone_boundary_ist(isolated_schedule_db):
    """Assert that an event at UTC 2026-10-20T20:30:00Z belongs to local day 2026-10-21 in IST (02:00 AM)."""
    senior_id = "senior_ist"
    storage.ensure_senior_exists(
        senior_id=senior_id,
        name="Aarav Patel",
        tz="Asia/Kolkata",
        db_path=isolated_schedule_db,
    )

    # UTC timestamp: 2026-10-20T20:30:00Z
    # In Asia/Kolkata (+05:30): 2026-10-21 02:00:00+05:30 (next local day)
    p = await log_daily_routine(
        senior_id=senior_id,
        category="wellness",
        details="Nighttime rest check-in",
        timestamp="2026-10-20T20:30:00Z",
    )
    await verify_routine_state(confirm=True, transaction_id=p["transaction_id"])

    # Query local day 2026-10-21 (in IST) -> Event MUST be present
    summary_21 = await get_caregiver_summary(senior_id, date="2026-10-21")
    assert summary_21["total_events"] == 1
    assert summary_21["events"][0]["timestamp"] == "2026-10-20T20:30:00Z"
    assert summary_21["last_activity"] == "2026-10-20T20:30:00Z"

    # Query local day 2026-10-20 (in IST) -> Event MUST NOT be present
    summary_20 = await get_caregiver_summary(senior_id, date="2026-10-20")
    assert summary_20["total_events"] == 0
    assert summary_20["last_activity"] is None


# ---------------------------------------------------------------------------
# Test 4: Alert deduplication & escalation ladder
# ---------------------------------------------------------------------------
def test_alert_dedupe(isolated_schedule_db):
    """Assert escalation ladder and deduplication: same slot+day+level is never re-emitted."""
    senior_id = "margaret_01"  # America/New_York (UTC-4)
    # Breakfast window: 08:00 - 10:00 EDT. Grace end: 10:30 EDT = 14:30 UTC.

    # Time T1: 11:45 EDT (15:45 UTC) -> Overdue duration: 1h 15m (>= threshold_hours=1)
    t1 = datetime(2026, 10, 20, 15, 45, 0, tzinfo=timezone.utc)
    res_t1 = storage.scan_missed_routines(senior_id, threshold_hours=1, now=t1, db_path=isolated_schedule_db)
    assert res_t1["status"] == "FLAGGED"
    assert res_t1["alerts_count"] >= 1

    # Find the breakfast alert
    breakfast_alerts = [a for a in res_t1["alerts_emitted"] if a["slot_id"] == "breakfast"]
    assert len(breakfast_alerts) == 1
    a0 = breakfast_alerts[0]
    assert a0["level"] == 0
    assert a0["channel"] == "gentle_voice_prompt"
    # Never alarm-style wording
    assert "alarm" not in a0["message"].lower()
    assert "emergency" not in a0["message"].lower()
    assert "critical" not in a0["message"].lower()

    # Call again at same time T1 -> DEDUPLICATED!
    res_t1_repeat = storage.scan_missed_routines(senior_id, threshold_hours=1, now=t1, db_path=isolated_schedule_db)
    assert res_t1_repeat["alerts_count"] == 0
    assert res_t1_repeat["status"] in ("DEDUPLICATED", "NO_OVERDUE")

    # Time T2: 12:45 EDT (16:45 UTC) -> Overdue duration: 2h 15m (>= threshold_hours + step)
    t2 = datetime(2026, 10, 20, 16, 45, 0, tzinfo=timezone.utc)
    res_t2 = storage.scan_missed_routines(senior_id, threshold_hours=1, now=t2, db_path=isolated_schedule_db)
    b_t2 = [a for a in res_t2["alerts_emitted"] if a["slot_id"] == "breakfast"]
    assert len(b_t2) == 1
    a1 = b_t2[0]
    assert a1["level"] == 1
    assert a1["channel"] == "display_banner"

    # Repeat at T2 -> DEDUPLICATED!
    res_t2_repeat = storage.scan_missed_routines(senior_id, threshold_hours=1, now=t2, db_path=isolated_schedule_db)
    assert len([a for a in res_t2_repeat["alerts_emitted"] if a["slot_id"] == "breakfast"]) == 0

    # Time T3: 13:45 EDT (17:45 UTC) -> Overdue duration: 3h 15m (>= threshold_hours + 2*step)
    t3 = datetime(2026, 10, 20, 17, 45, 0, tzinfo=timezone.utc)
    res_t3 = storage.scan_missed_routines(senior_id, threshold_hours=1, now=t3, db_path=isolated_schedule_db)
    b_t3 = [a for a in res_t3["alerts_emitted"] if a["slot_id"] == "breakfast"]
    assert len(b_t3) == 1
    a2 = b_t3[0]
    assert a2["level"] == 2
    assert a2["channel"] == "caregiver_timeline"

    # Repeat at T3 -> DEDUPLICATED!
    res_t3_repeat = storage.scan_missed_routines(senior_id, threshold_hours=1, now=t3, db_path=isolated_schedule_db)
    assert len([a for a in res_t3_repeat["alerts_emitted"] if a["slot_id"] == "breakfast"]) == 0

    # Verify total alerts in database for breakfast slot on 2026-10-20 is exactly 3 (levels 0, 1, 2)
    conn = storage.get_connection(isolated_schedule_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT level, channel, message FROM alerts WHERE senior_id = ? AND slot_id = ?", (senior_id, "breakfast"))
        rows = cursor.fetchall()
        assert len(rows) == 3
        levels = {r["level"] for r in rows}
        assert levels == {0, 1, 2}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test 5: Unconfirmed events ignored
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unconfirmed_events_ignored(isolated_schedule_db):
    """Assert that unconfirmed proposals in the proposals table are strictly ignored by get_caregiver_summary."""
    senior_id = "margaret_01"
    target_date = "2026-10-20"

    # Create unconfirmed proposals for breakfast and hydration
    p1 = await log_daily_routine(
        senior_id=senior_id,
        category="meal",
        details="Unconfirmed breakfast proposal",
        timestamp="2026-10-20T12:30:00Z",
    )
    assert p1["status"] == "pending_confirmation"

    p2 = await log_daily_routine(
        senior_id=senior_id,
        category="hydration",
        details="Unconfirmed hydration proposal",
        timestamp="2026-10-20T12:45:00Z",
    )
    assert p2["status"] == "pending_confirmation"

    # Neither proposal is confirmed via verify_routine_state
    summary = await get_caregiver_summary(senior_id, date=target_date)

    assert summary["total_events"] == 0
    assert summary["completed_count"] == 0
    assert summary["completion_percentage"] == 0.0
    assert summary["last_activity"] is None
    assert summary["completed_types"] == []

    # All slots remain non-completed
    for slot in summary["slots"]:
        assert slot["status"] != "completed"
        assert slot["completed_at"] is None


# ---------------------------------------------------------------------------
# Test 6: Caregiver summary filter_status ('all' | 'completed' | 'pending')
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_caregiver_summary_filter_status(isolated_schedule_db):
    """Assert that get_caregiver_summary correctly filters slots by status."""
    senior_id = "margaret_01"
    target_date = "2026-10-20"

    # Confirm Breakfast
    p = await log_daily_routine(
        senior_id=senior_id,
        category="meal",
        details="Morning oatmeal",
        timestamp="2026-10-20T12:30:00Z",
    )
    await verify_routine_state(confirm=True, transaction_id=p["transaction_id"])

    # Filter: 'completed'
    summary_completed = await get_caregiver_summary(senior_id, date=target_date, filter_status="completed")
    assert summary_completed["completed_count"] == 1
    assert len(summary_completed["slots"]) == 1
    assert summary_completed["slots"][0]["slot_id"] == "breakfast"
    assert summary_completed["slots"][0]["status"] == "completed"

    # Filter: 'pending'
    summary_pending = await get_caregiver_summary(senior_id, date=target_date, filter_status="pending")
    assert summary_pending["pending_count"] == summary_pending["total_slots"] - 1
    assert len(summary_pending["slots"]) == summary_pending["total_slots"] - 1
    for s in summary_pending["slots"]:
        assert s["status"] != "completed"

    # Filter: 'all'
    summary_all = await get_caregiver_summary(senior_id, date=target_date, filter_status="all")
    assert len(summary_all["slots"]) == summary_all["total_slots"]
