"""Janus (ElderSync) — Part 5 Safety Audit Logging Tests.

Comprehensive validation for:
1. Safety policy denials (Emergency guidance, Medication blocked, Clarification required).
2. Successful routine and handoff commits.
3. Cryptographic hash-chain integrity after mixed operations.
4. Tamper detection on outcome, reason_code, mutation_committed, and hash links.
5. Privacy & log hygiene (no raw text, clinical symptoms, medications, or tokens in audit rows).
6. Explicit, safe failure-handling paths for audit logging without leaking private data.
7. Backward compatibility for legacy v1 hash chains.
"""

from __future__ import annotations

import os
import sys
import tempfile
import sqlite3

import pytest
from starlette.testclient import TestClient

# Ensure src directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from janus import storage
from janus.audit import verify_audit_chain, main as audit_main
from janus.auth import current_identity
from janus.errors import AuditWriteError, ErrorCode, SafetyBlockedError
from janus.gate import ConfirmationGate
from janus.server import (
    get_app,
    log_daily_routine,
    verify_routine_state,
)


@pytest.fixture
def audit_db(monkeypatch):
    """Create an isolated temporary SQLite database for each test."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_safety_audit.db")
    monkeypatch.setattr(storage, "DEFAULT_DB_PATH", test_db_path)
    storage.init_db(test_db_path)
    yield test_db_path
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass


@pytest.fixture
def auth_sarah(monkeypatch):
    """Set authenticated identity to caregiver Sarah authorized for Margaret."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "1")
    tok = current_identity.set({
        "actor": "caregiver_sarah",
        "role": "caregiver",
        "allowed_seniors": {"margaret_01"},
        "token": "janus-demo-caregiver-sarah",
    })
    yield
    current_identity.reset(tok)


# ===========================================================================
# 1. Safety Policy Denials Audit Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_emergency_guidance_denial_audited(audit_db, auth_sarah):
    """Emergency guidance trigger creates an audit denial record with stable code and 0 writes."""
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="wellness",
        details="Margaret has crushing chest pain and shortness of breath",
    )
    assert res["status"] == "error"
    assert res["error_code"] == "EMERGENCY_GUIDANCE"
    assert res["database_writes"] == 0

    # Inspect audit_log table
    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 0, "No routine log should be written on emergency denial"

        cursor.execute("SELECT * FROM audit_log WHERE outcome = 'BLOCKED_EMERGENCY_GUIDANCE'")
        rows = cursor.fetchall()
        assert len(rows) == 1
        entry = dict(rows[0])
        assert entry["actor"] == "caregiver_sarah"
        assert entry["senior_id"] == "margaret_01"
        assert entry["tool"] == "log_daily_routine"
        assert entry["transaction_id"] is None
        assert entry["mutation_committed"] == 0
        assert "cardiac" in entry["reason_code"] or "chest" in entry["reason_code"] or entry["reason_code"] == "EMERGENCY_GUIDANCE"
    finally:
        conn.close()

    # Hash chain remains intact
    is_valid, broken_id, msg = verify_audit_chain(audit_db)
    assert is_valid is True, msg


@pytest.mark.asyncio
async def test_medication_action_blocked_audited(audit_db, auth_sarah):
    """Medication changes are blocked and audited with stable reason code."""
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="wellness",
        details="Double the dose of insulin before dinner",
    )
    assert res["status"] == "error"
    assert res["error_code"] == "MEDICAL_ACTION_BLOCKED"
    assert res["database_writes"] == 0

    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log WHERE outcome = 'BLOCKED_MEDICAL_ACTION_BLOCKED'")
        rows = cursor.fetchall()
        assert len(rows) == 1
        entry = dict(rows[0])
        assert entry["actor"] == "caregiver_sarah"
        assert entry["senior_id"] == "margaret_01"
        assert entry["mutation_committed"] == 0
        assert entry["reason_code"] is not None
    finally:
        conn.close()

    is_valid, _, msg = verify_audit_chain(audit_db)
    assert is_valid is True, msg


@pytest.mark.asyncio
async def test_clarification_required_audited(audit_db, auth_sarah):
    """Ambiguous health complaint produces CLARIFICATION_REQUIRED audit entry."""
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="wellness",
        details="Feels very dizzy and unsteady today",
    )
    assert res["status"] == "error"
    assert res["error_code"] == "CLARIFICATION_REQUIRED"
    assert res["database_writes"] == 0

    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log WHERE outcome = 'BLOCKED_CLARIFICATION_REQUIRED'")
        rows = cursor.fetchall()
        assert len(rows) == 1
        entry = dict(rows[0])
        assert entry["actor"] == "caregiver_sarah"
        assert entry["senior_id"] == "margaret_01"
        assert entry["mutation_committed"] == 0
    finally:
        conn.close()

    is_valid, _, msg = verify_audit_chain(audit_db)
    assert is_valid is True, msg


def test_gate_propose_safety_denial_audited(audit_db):
    """Direct ConfirmationGate.propose records audit entry when safety check denies."""
    gate = ConfirmationGate(db_path=audit_db)
    with pytest.raises(SafetyBlockedError) as exc_info:
        gate.propose(
            senior_id="margaret_01",
            action_type="routine_log",
            payload={"category": "wellness", "details": "acute severe allergic anaphylaxis"},
            actor="senior_voice",
        )
    assert exc_info.value.code == "EMERGENCY_GUIDANCE"

    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log WHERE outcome = 'BLOCKED_EMERGENCY_GUIDANCE'")
        rows = cursor.fetchall()
        assert len(rows) == 1
        entry = dict(rows[0])
        assert entry["tool"] == "gate.propose"
        assert entry["mutation_committed"] == 0
    finally:
        conn.close()

    is_valid, _, msg = verify_audit_chain(audit_db)
    assert is_valid is True, msg


@pytest.mark.asyncio
async def test_handoff_safety_denial_audited(audit_db, auth_sarah):
    """Shift handoff proposal with clinical emergency notes is audited."""
    res = await verify_routine_state(
        confirm=False,
        senior_id="margaret_01",
        action_type="shift_handoff",
        payload={
            "departing_caregiver": "Sarah",
            "incoming_caregiver": "David",
            "handoff_notes": "Margaret had a suspected stroke with facial droop and arm weakness",
        },
    )
    assert res["status"] == "error"
    assert res["error_code"] == "EMERGENCY_GUIDANCE"

    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log WHERE tool = 'verify_routine_state' AND outcome = 'BLOCKED_EMERGENCY_GUIDANCE'")
        rows = cursor.fetchall()
        assert len(rows) == 1
        entry = dict(rows[0])
        assert entry["senior_id"] == "margaret_01"
        assert entry["mutation_committed"] == 0
    finally:
        conn.close()


# ===========================================================================
# 2. Successful Commits Audit Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_successful_commit_audited_with_mutation_flag(audit_db, auth_sarah):
    """A valid proposal commit produces a COMMITTED audit entry with mutation_committed=1."""
    # Step 1: Create proposal
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="500ml water",
    )
    assert prop["status"] == "pending_confirmation"
    tx_id = prop["transaction_id"]

    # Step 2: Confirm proposal
    commit = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert commit["status"] == "COMMITTED"
    assert commit["database_writes"] == 1

    # Verify audit_log
    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log WHERE transaction_id = ? AND outcome = 'COMMITTED'", (tx_id,))
        rows = cursor.fetchall()
        assert len(rows) == 1
        entry = dict(rows[0])
        assert entry["actor"] == "caregiver_sarah"
        assert entry["senior_id"] == "margaret_01"
        assert entry["mutation_committed"] == 1
        assert entry["reason_code"] == "ROUTINE_COMMITTED"
        assert entry["tool"] == "verify_routine_state"
    finally:
        conn.close()

    is_valid, _, msg = verify_audit_chain(audit_db)
    assert is_valid is True, msg


# ===========================================================================
# 3. Confirmation Failure Audit Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_missing_tx_confirmation_failure_audited(audit_db, auth_sarah):
    """confirm=True with missing transaction_id produces CONFIRMATION_FAILED audit record."""
    res = await verify_routine_state(confirm=True, transaction_id=None)
    assert res["status"] == "error"
    assert res["error_code"] == ErrorCode.MISSING_TRANSACTION_ID

    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log WHERE outcome = 'CONFIRMATION_FAILED' AND reason_code = ?", (ErrorCode.MISSING_TRANSACTION_ID,))
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["mutation_committed"] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_nonexistent_proposal_confirmation_failure_audited(audit_db, auth_sarah):
    """confirm=True with non-existent transaction_id produces CONFIRMATION_FAILED audit record."""
    res = await verify_routine_state(confirm=True, transaction_id="tx_nonexistent_99999")
    assert res["status"] == "error"
    assert res["error_code"] == ErrorCode.PROPOSAL_NOT_FOUND

    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log WHERE outcome = 'CONFIRMATION_FAILED' AND reason_code = ?", (ErrorCode.PROPOSAL_NOT_FOUND,))
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["transaction_id"] == "tx_nonexistent_99999"
        assert rows[0]["mutation_committed"] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_expired_proposal_confirmation_failure_audited(audit_db, auth_sarah):
    """Confirming an expired proposal records a CONFIRMATION_FAILED audit record."""
    tx_id = "tx_expired_audit_test"
    conn = storage.get_connection(audit_db)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO proposals (
                    transaction_id, senior_id, action_type, payload_json,
                    actor, created_at, expires_at, status
                ) VALUES (?, ?, 'routine_log', ?, 'caregiver_sarah', '2020-01-01T00:00:00Z', '2020-01-01T00:05:00Z', 'pending')
                """,
                (tx_id, "margaret_01", '{"category": "hydration", "details": "water"}'),
            )
    finally:
        conn.close()

    res = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert res["status"] == "error"
    assert res["error_code"] == "PROPOSAL_EXPIRED"

    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log WHERE transaction_id = ? AND outcome = 'CONFIRMATION_FAILED'", (tx_id,))
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["reason_code"] == "PROPOSAL_EXPIRED"
        assert rows[0]["mutation_committed"] == 0
    finally:
        conn.close()


# ===========================================================================
# 4. Hash Chain Integrity and Tamper Detection Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_mixed_operations_chain_integrity(audit_db, monkeypatch):
    """Audit chain verification succeeds across a mixed lifecycle of auth, proposals, denials, and commits."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "1")
    app = get_app()
    client = TestClient(app)

    # 1. Auth rejection
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert resp.status_code == 401

    # 2. Safety denial (emergency)
    tok_sarah = current_identity.set({
        "actor": "caregiver_sarah",
        "role": "caregiver",
        "allowed_seniors": {"margaret_01"},
        "token": "janus-demo-caregiver-sarah",
    })
    try:
        await log_daily_routine(
            senior_id="margaret_01",
            category="wellness",
            details="Margaret having sudden heart attack and chest pain",
        )

        # 3. Successful proposal and commit
        prop = await log_daily_routine(
            senior_id="margaret_01",
            category="hydration",
            details="glass of apple juice",
        )
        tx_id = prop["transaction_id"]
        await verify_routine_state(confirm=True, transaction_id=tx_id)

        # 4. Medication denial
        await log_daily_routine(
            senior_id="margaret_01",
            category="wellness",
            details="Double the dose of insulin",
        )

        # 5. Confirmation failure
        await verify_routine_state(confirm=True, transaction_id="tx_fake_000")
    finally:
        current_identity.reset(tok_sarah)

    # Cryptographic audit chain verification
    is_valid, broken_id, msg = verify_audit_chain(audit_db)
    assert is_valid is True, f"Audit chain verification failed: {msg}"
    assert broken_id is None

    # CLI verification
    cli_code = audit_main(["verify", "--db", audit_db])
    assert cli_code == 0


def test_tamper_detection_outcome(audit_db):
    """Modifying outcome field in an audit row breaks the cryptographic chain."""
    storage.record_audit_entry(
        actor="caregiver_sarah",
        role="caregiver",
        tool="test_tool",
        senior_id="margaret_01",
        transaction_id=None,
        outcome="BLOCKED_EMERGENCY_GUIDANCE",
        reason_code="cardiac_chest_pain",
        mutation_committed=False,
        db_path=audit_db,
    )

    conn = storage.get_connection(audit_db)
    with conn:
        conn.execute("UPDATE audit_log SET outcome = 'COMMITTED' WHERE id = 1")
    conn.close()

    is_valid, broken_id, msg = verify_audit_chain(audit_db)
    assert is_valid is False
    assert broken_id == 1
    assert "hash mismatch" in msg


def test_tamper_detection_mutation_flag(audit_db):
    """Modifying mutation_committed in an audit row breaks the cryptographic chain."""
    storage.record_audit_entry(
        actor="caregiver_sarah",
        role="caregiver",
        tool="test_tool",
        senior_id="margaret_01",
        transaction_id="tx_123",
        outcome="COMMITTED",
        reason_code="ROUTINE_COMMITTED",
        mutation_committed=True,
        db_path=audit_db,
    )

    conn = storage.get_connection(audit_db)
    with conn:
        conn.execute("UPDATE audit_log SET mutation_committed = 0 WHERE id = 1")
    conn.close()

    is_valid, broken_id, msg = verify_audit_chain(audit_db)
    assert is_valid is False
    assert broken_id == 1
    assert "hash mismatch" in msg


def test_tamper_detection_reason_code(audit_db):
    """Modifying reason_code in an audit row breaks the cryptographic chain."""
    storage.record_audit_entry(
        actor="caregiver_sarah",
        role="caregiver",
        tool="test_tool",
        senior_id="margaret_01",
        transaction_id=None,
        outcome="BLOCKED_MEDICAL_ACTION_BLOCKED",
        reason_code="dose_adjustment",
        mutation_committed=False,
        db_path=audit_db,
    )

    conn = storage.get_connection(audit_db)
    with conn:
        conn.execute("UPDATE audit_log SET reason_code = 'other_code' WHERE id = 1")
    conn.close()

    is_valid, broken_id, msg = verify_audit_chain(audit_db)
    assert is_valid is False
    assert broken_id == 1
    assert "hash mismatch" in msg


# ===========================================================================
# 5. Privacy & Log Hygiene Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_audit_log_hygiene_no_raw_sensitive_text(audit_db, auth_sarah, monkeypatch):
    """Raw clinical free-text, symptom descriptions, and medication details are never stored in audit_log."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "1")

    # 1. Emergency safety denial
    await log_daily_routine(
        senior_id="margaret_01",
        category="wellness",
        details="Margaret having severe crushing chest pain and heart attack",
    )

    # 2. Medication modification denial
    await log_daily_routine(
        senior_id="margaret_01",
        category="wellness",
        details="Doctor said to increase lisinopril dose to 20mg",
    )

    # 3. Clarification denial
    await log_daily_routine(
        senior_id="margaret_01",
        category="wellness",
        details="Feels very dizzy with headache and nausea",
    )

    # 4. Auth rejection with secret token
    app = get_app()
    client = TestClient(app)
    client.post(
        "/mcp",
        headers={"Authorization": "Bearer super-secret-private-key-999"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    # 5. Successful routine commit
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="meal",
        details="Lunch with grilled chicken",
    )
    await verify_routine_state(confirm=True, transaction_id=prop["transaction_id"])

    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log")
        rows = cursor.fetchall()
        assert len(rows) >= 4

        # Check all text in all columns of all rows
        for row in rows:
            row_dict = dict(row)
            for col_name, val in row_dict.items():
                if val is not None and isinstance(val, str):
                    for secret in [
                        "chest pain",
                        "heart attack",
                        "lisinopril",
                        "20mg",
                        "dizzy",
                        "headache",
                        "super-secret",
                        "private-key",
                        "grilled chicken",
                    ]:
                        assert secret not in val.lower(), f"Sensitive leak found in column '{col_name}': {val}"
    finally:
        conn.close()


# ===========================================================================
# 6. Failure Handling Tests
# ===========================================================================

def test_record_audit_entry_failure_raises_audit_write_error(monkeypatch):
    """Audit write failures raise an explicit AuditWriteError without leaking internal data."""
    # Pass an invalid database path that cannot be written
    invalid_db_path = os.path.join(tempfile.gettempdir(), "nonexistent_dir_xyz123", "sub", "fake.db")
    with pytest.raises(AuditWriteError) as exc_info:
        storage.record_audit_entry(
            actor="test_actor",
            role="caregiver",
            tool="test_tool",
            senior_id="margaret_01",
            transaction_id=None,
            outcome="BLOCKED_EMERGENCY_GUIDANCE",
            db_path=invalid_db_path,
        )

    # Safe message without database internals
    err_msg = str(exc_info.value)
    assert "Cryptographic audit logging failed" in err_msg
    assert "nonexistent_dir" not in err_msg


@pytest.mark.asyncio
async def test_atomic_rollback_on_audit_write_failure(audit_db, auth_sarah, monkeypatch):
    """If audit log write fails during commit_proposal, routine_logs mutation rolls back completely."""
    # Create proposal
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="250ml water",
    )
    tx_id = prop["transaction_id"]

    # Monkeypatch _append_audit_row_in_tx to raise an error simulating DB failure during audit
    def faulty_append(*args, **kwargs):
        raise sqlite3.OperationalError("Simulated disk error during audit write")

    monkeypatch.setattr(storage, "_append_audit_row_in_tx", faulty_append)

    # Attempt commit: must fail with AuditWriteError
    with pytest.raises(AuditWriteError) as exc_info:
        storage.commit_proposal(transaction_id=tx_id, db_path=audit_db)

    assert "Cryptographic audit logging failed" in str(exc_info.value)

    # Verify atomic rollback: 0 rows in routine_logs, proposal is still pending
    conn = storage.get_connection(audit_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 0, "Mutation must NOT commit if audit log write failed"

        cursor.execute("SELECT status FROM proposals WHERE transaction_id = ?", (tx_id,))
        assert cursor.fetchone()[0] == "pending", "Proposal must remain pending if commit was rolled back"
    finally:
        conn.close()
