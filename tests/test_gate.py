"""Janus (ElderSync) — Two-Step Confirmation Gate Tests.

Verifies the strict single-writer proposal gate invariants:
1. No-preview commit rejected (unknown or missing transaction_id).
2. Expired proposal rejected after 5 minutes.
3. Replay is idempotent (row count stays 1 on subsequent confirm=True).
4. confirm=False never writes (row count across all domain tables remains 0).
5. Invalid category rejected (rejects 'medication' and non-standard categories).
6. Concurrent double-confirm via threads yields exactly one record.
"""

from __future__ import annotations

import concurrent.futures
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Ensure src directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from janus import storage  # noqa: E402
from janus.server import log_daily_routine, verify_routine_state  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_gate_db(monkeypatch):
    """Create an isolated temporary SQLite database for each test and reset clock override."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_gate_janus.db")
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


def get_table_count(db_path: str, table_name: str) -> int:
    """Helper to query exact row count of a table."""
    conn = storage.get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return int(cursor.fetchone()[0])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test 1: No-preview commit rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_preview_commit_rejected(isolated_gate_db):
    """Assert that confirm=True without a valid live proposal is strictly rejected."""
    # Subcase A: Missing transaction_id
    res_missing = await verify_routine_state(confirm=True, transaction_id=None)
    assert res_missing["status"] == "error"
    assert res_missing["error_code"] == "MISSING_TRANSACTION_ID"
    assert res_missing["database_writes"] == 0

    # Subcase B: Unknown/unseen transaction_id
    res_unknown = await verify_routine_state(confirm=True, transaction_id="tx_nonexistent_12345")
    assert res_unknown["status"] == "error"
    assert res_unknown["error_code"] == "PROPOSAL_NOT_FOUND"
    assert res_unknown["database_writes"] == 0

    # Assert row counts across all domain tables remain strictly 0
    assert get_table_count(isolated_gate_db, "routine_logs") == 0
    assert get_table_count(isolated_gate_db, "shift_handoffs") == 0


# ---------------------------------------------------------------------------
# Test 2: Expired proposal rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_expired_rejected(isolated_gate_db):
    """Assert that confirming an expired proposal (>5 min window) is rejected with zero writes."""
    t0 = datetime(2026, 10, 20, 9, 0, 0, tzinfo=timezone.utc)
    storage.set_clock_override(t0)

    # Create proposal at t0
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="500ml water",
    )
    tx_id = prop["transaction_id"]
    assert prop["status"] == "pending_confirmation"

    # Fast-forward clock by 5 minutes and 1 second (past 5 min expiration)
    storage.set_clock_override(t0 + timedelta(minutes=5, seconds=1))

    # Attempt commit
    commit_res = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert commit_res["status"] == "error"
    assert commit_res["error_code"] == "PROPOSAL_EXPIRED"
    assert commit_res["database_writes"] == 0

    # Assert zero writes committed to routine_logs
    assert get_table_count(isolated_gate_db, "routine_logs") == 0


# ---------------------------------------------------------------------------
# Test 3: Replay is idempotent
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_replay_is_idempotent(isolated_gate_db):
    """Assert that a second confirm=True returns ALREADY_COMMITTED and writes nothing."""
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="meal",
        details="Finished lunchtime soup",
    )
    tx_id = prop["transaction_id"]

    # First commit
    res1 = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert res1["status"] == "COMMITTED"
    assert res1["database_writes"] == 1
    result_id = res1["result_id"]
    assert result_id is not None
    assert get_table_count(isolated_gate_db, "routine_logs") == 1

    # Second commit (idempotent replay)
    res2 = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert res2["status"] == "ALREADY_COMMITTED"
    assert res2["database_writes"] == 0
    assert res2["result_id"] == result_id

    # Row count stays exactly 1
    assert get_table_count(isolated_gate_db, "routine_logs") == 1


# ---------------------------------------------------------------------------
# Test 4: confirm=False never writes
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_confirm_false_never_writes(isolated_gate_db):
    """Assert that confirm=False never writes to domain tables and never alters proposal state."""
    assert get_table_count(isolated_gate_db, "routine_logs") == 0
    assert get_table_count(isolated_gate_db, "shift_handoffs") == 0

    # 1. log_daily_routine proposal creation
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="vitamins",
        details="Morning vitamin pack",
    )
    tx_id = prop["transaction_id"]
    assert get_table_count(isolated_gate_db, "routine_logs") == 0
    assert get_table_count(isolated_gate_db, "shift_handoffs") == 0

    # 2. verify_routine_state proposal preview for shift_handoff
    preview_handoff = await verify_routine_state(
        confirm=False,
        senior_id="margaret_01",
        action_type="shift_handoff",
        payload={
            "departing_caregiver": "David",
            "incoming_caregiver": "Sarah",
            "handoff_notes": "Morning vitals stable",
        },
    )
    assert preview_handoff["status"] == "PROPOSAL_PREVIEW"
    assert preview_handoff["database_writes"] == 0
    assert get_table_count(isolated_gate_db, "routine_logs") == 0
    assert get_table_count(isolated_gate_db, "shift_handoffs") == 0

    # 3. verify_routine_state proposal preview by transaction_id
    preview_by_id = await verify_routine_state(confirm=False, transaction_id=tx_id)
    assert preview_by_id["status"] == "PROPOSAL_PREVIEW"
    assert preview_by_id["database_writes"] == 0
    assert get_table_count(isolated_gate_db, "routine_logs") == 0
    assert get_table_count(isolated_gate_db, "shift_handoffs") == 0

    # Assert proposal status remains 'pending'
    saved_prop = storage.get_proposal(tx_id, db_path=isolated_gate_db)
    assert saved_prop is not None
    assert saved_prop["status"] == "pending"


# ---------------------------------------------------------------------------
# Test 5: Invalid category rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_category_rejected(isolated_gate_db):
    """Assert non-clinical boundary: rejects 'medication' and unapproved categories."""
    # Rejects 'medication' (non-clinical positioning constraint)
    with pytest.raises(ValueError, match="Invalid category 'medication'"):
        await log_daily_routine(
            senior_id="margaret_01",
            category="medication",
            details="Blood pressure pills",
        )

    # Rejects random unknown category
    with pytest.raises(ValueError, match="Invalid category 'cardio_extreme'"):
        await log_daily_routine(
            senior_id="margaret_01",
            category="cardio_extreme",
            details="Heavy gym workout",
        )

    # Assert 0 proposals and 0 logs created from invalid inputs
    assert get_table_count(isolated_gate_db, "proposals") == 0
    assert get_table_count(isolated_gate_db, "routine_logs") == 0

    # Valid categories must all succeed
    valid_categories = ["meal", "hydration", "vitamins", "activity", "wellness"]
    for cat in valid_categories:
        res = await log_daily_routine(
            senior_id="margaret_01",
            category=cat,
            details=f"Test {cat}",
        )
        assert res["status"] == "pending_confirmation"
        assert res["preview"]["category"] == cat

    assert get_table_count(isolated_gate_db, "proposals") == len(valid_categories)
    assert get_table_count(isolated_gate_db, "routine_logs") == 0


# ---------------------------------------------------------------------------
# Test 6: Concurrent double-confirm via threads yields exactly one record
# ---------------------------------------------------------------------------
def test_concurrent_double_confirm_yields_one_record(isolated_gate_db):
    """Assert that concurrent calls from multiple threads to commit the same proposal yield exactly one record."""
    prop = storage.create_proposal(
        senior_id="margaret_01",
        action_type="routine_log",
        payload={
            "category": "activity",
            "details": "Morning Porch Walk",
            "timestamp": "2026-10-20T10:30:00Z",
            "actor": "senior_voice",
        },
        actor="senior_voice",
        db_path=isolated_gate_db,
    )
    tx_id = prop["transaction_id"]

    results = []

    def worker_commit():
        return storage.commit_proposal(transaction_id=tx_id, db_path=isolated_gate_db)

    # Launch 6 concurrent threads attempting to commit the same transaction ID
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker_commit) for _ in range(6)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # One thread MUST be COMMITTED; all other 5 threads MUST be ALREADY_COMMITTED
    committed_results = [r for r in results if r["status"] == "COMMITTED"]
    already_committed_results = [r for r in results if r["status"] == "ALREADY_COMMITTED"]

    assert len(committed_results) == 1, f"Expected exactly 1 COMMITTED, got {len(committed_results)}"
    assert len(already_committed_results) == 5, f"Expected 5 ALREADY_COMMITTED, got {len(already_committed_results)}"

    # All results must reference the identical result_id
    committed_id = committed_results[0]["result_id"]
    assert committed_id is not None
    for r in already_committed_results:
        assert r["result_id"] == committed_id

    # The SQLite table routine_logs MUST have exactly 1 record
    conn = storage.get_connection(isolated_gate_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, senior_id, routine_type, value FROM routine_logs")
        rows = cursor.fetchall()
        assert len(rows) == 1, f"Expected exactly 1 row in routine_logs, got {len(rows)}"
        assert rows[0]["id"] == committed_id
        assert rows[0]["routine_type"] == "activity"
        assert rows[0]["value"] == "Morning Porch Walk"
    finally:
        conn.close()
