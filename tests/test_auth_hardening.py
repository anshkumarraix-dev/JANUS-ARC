"""Janus (ElderSync) — Part 4 Authorization and Confirmation Hardening Tests.

Regression and contract tests for:
1. Missing and invalid credentials (HTTP ASGI middleware and direct context).
2. Insufficient role permissions (senior vs caregiver restrictions).
3. Cross-senior access attempts (isolation on reads and writes).
4. Confirmation using another user's transaction ID.
5. Missing and expired transaction IDs.
6. Cancelled and already-committed proposals.
7. Duplicate confirmation and replay protection.
8. Concurrent confirmation attempts and race condition protection.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

# Ensure src directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from janus import storage
from janus.auth import (
    Role,
    current_identity,
    extract_bearer_token,
    get_token_registry,
    set_current_identity,
)
from janus.errors import ErrorCode
from janus.server import (
    flag_missed_routine,
    get_app,
    get_caregiver_summary,
    get_senior_today_resource,
    log_daily_routine,
    verify_routine_state,
)


@pytest.fixture
def auth_db(monkeypatch):
    """Create an isolated temporary SQLite database for each test."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_auth_hardening.db")
    monkeypatch.setattr(storage, "DEFAULT_DB_PATH", test_db_path)
    storage.init_db(test_db_path)
    yield test_db_path
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass


# ===========================================================================
# 1. Missing and Invalid Credentials Tests
# ===========================================================================

def test_missing_authorization_header_rejected_by_asgi(auth_db, monkeypatch):
    """HTTP requests lacking an Authorization header are rejected with HTTP 401."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "1")
    app = get_app()
    client = TestClient(app)

    # Post to /mcp without Authorization header
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"] == "UNAUTHORIZED"
    assert data["database_writes"] == 0
    assert "Missing authorization token" in data["message"]

    # Verify audit log records the rejected attempt
    conn = storage.get_connection(auth_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT outcome, tool FROM audit_log WHERE outcome = 'UNAUTHORIZED'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "UNAUTHORIZED"
    finally:
        conn.close()


def test_invalid_bearer_token_rejected_by_asgi(auth_db, monkeypatch):
    """HTTP requests with an invalid bearer token are rejected with HTTP 401."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "1")
    app = get_app()
    client = TestClient(app)

    resp = client.post(
        "/mcp",
        headers={"Authorization": "Bearer totally-invalid-token-12345"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"] == "UNAUTHORIZED"
    assert data["database_writes"] == 0


def test_malformed_authorization_headers_rejected(auth_db, monkeypatch):
    """Non-Bearer schemes or empty tokens are rejected."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "1")
    app = get_app()
    client = TestClient(app)

    # Basic auth
    resp1 = client.post("/mcp", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp1.status_code == 401

    # Empty Bearer
    resp2 = client.post("/mcp", headers={"Authorization": "Bearer "})
    assert resp2.status_code == 401


def test_demo_tokens_rejected_when_demo_mode_disabled(auth_db, monkeypatch):
    """When JANUS_DEMO_MODE is not 1, demo tokens are strictly invalid."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "0")
    app = get_app()
    client = TestClient(app)

    resp = client.post(
        "/mcp",
        headers={"Authorization": "Bearer janus-demo-caregiver-sarah"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "UNAUTHORIZED"


def test_demo_mode_env_quoted_and_truthy_variations(monkeypatch):
    """JANUS_DEMO_MODE safely handles quotes, case variations, and truthy values."""
    for val in ('"1"', "'1'", "1", "true", "True", "TRUE", "yes", "on"):
        monkeypatch.setenv("JANUS_DEMO_MODE", val)
        reg = get_token_registry()
        assert "janus-demo-senior-margaret" in reg
        assert "janus-demo-caregiver-sarah" in reg

    for val in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("JANUS_DEMO_MODE", val)
        reg = get_token_registry()
        assert "janus-demo-senior-margaret" not in reg


def test_bearer_token_nested_and_quoted_extraction():
    """extract_bearer_token strips accidental repeated Bearer prefix and surrounding quotes."""
    assert extract_bearer_token("Bearer Bearer janus-demo-senior-margaret") == "janus-demo-senior-margaret"
    assert extract_bearer_token('Bearer "janus-demo-senior-margaret"') == "janus-demo-senior-margaret"
    assert extract_bearer_token("Bearer 'janus-demo-caregiver-sarah'") == "janus-demo-caregiver-sarah"
    assert extract_bearer_token("Bearer   janus-demo-senior-margaret  ") == "janus-demo-senior-margaret"
    assert extract_bearer_token("Bearer ") is None
    assert extract_bearer_token('Bearer ""') is None
    assert extract_bearer_token("Bearer ''") is None
    assert extract_bearer_token(None) is None


def test_asgi_auth_middleware_nested_bearer_and_quoted_token_succeeds(auth_db, monkeypatch):
    """Requests with duplicate Bearer prefix or quoted tokens succeed on ASGI endpoint."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "1")
    app = get_app()
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        # Nested Bearer prefix
        resp1 = client.post(
            "/mcp",
            headers={"Authorization": "Bearer Bearer janus-demo-senior-margaret"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert resp1.status_code == 200

        # Quoted token
        resp2 = client.post(
            "/mcp",
            headers={"Authorization": 'Bearer "janus-demo-senior-margaret"'},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert resp2.status_code == 200


def test_asgi_auth_middleware_401_returns_message_and_detail(auth_db, monkeypatch):
    """HTTP 401 response provides both message and detail fields for client compatibility."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "1")
    app = get_app()
    client = TestClient(app)

    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "UNAUTHORIZED"
    assert "detail" in body
    assert "message" in body
    assert body["detail"] == body["message"]


@pytest.mark.asyncio
async def test_direct_tool_call_without_identity_rejected(auth_db):
    """Direct asynchronous tool calls with no authenticated context are rejected."""
    tok = current_identity.set(None)
    try:
        res = await log_daily_routine(
            senior_id="margaret_01",
            category="hydration",
            details="250ml water",
        )
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0

        # Invariant: 0 proposals or routine records
        conn = storage.get_connection(auth_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM proposals")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT COUNT(*) FROM routine_logs")
            assert cursor.fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        current_identity.reset(tok)


# ===========================================================================
# 2. Insufficient Role Permissions Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_senior_forbidden_from_caregiver_summary(auth_db):
    """A user with role 'senior' cannot read caregiver summaries."""
    tok = set_current_identity({
        "actor": "senior_margaret",
        "role": Role.SENIOR.value,
        "allowed_seniors": {"margaret_01"},
    })
    try:
        res = await get_caregiver_summary(senior_id="margaret_01")
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0
        assert "Caregiver role is required" in res["message"]
    finally:
        current_identity.reset(tok)


@pytest.mark.asyncio
async def test_senior_forbidden_from_proposing_shift_handoff(auth_db):
    """A user with role 'senior' cannot propose a caregiver shift handoff."""
    tok = set_current_identity({
        "actor": "senior_margaret",
        "role": Role.SENIOR.value,
        "allowed_seniors": {"margaret_01"},
    })
    try:
        res = await verify_routine_state(
            confirm=False,
            senior_id="margaret_01",
            action_type="shift_handoff",
            payload={
                "departing_caregiver": "senior_margaret",
                "incoming_caregiver": "caregiver_sarah",
                "handoff_notes": "Shift change notes",
            },
        )
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0
        assert "Caregiver role is required" in res["message"]
    finally:
        current_identity.reset(tok)


@pytest.mark.asyncio
async def test_senior_forbidden_from_confirming_shift_handoff(auth_db):
    """A user with role 'senior' cannot confirm a caregiver shift handoff."""
    # First, caregiver creates a handoff proposal
    cg_tok = set_current_identity({
        "actor": "caregiver_sarah",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"margaret_01"},
    })
    prop = await verify_routine_state(
        confirm=False,
        senior_id="margaret_01",
        action_type="shift_handoff",
        payload={
            "departing_caregiver": "caregiver_sarah",
            "incoming_caregiver": "caregiver_david",
            "handoff_notes": "All morning medications and meals completed normally.",
        },
    )
    tx_id = prop["transaction_id"]
    current_identity.reset(cg_tok)

    # Now, senior attempts to confirm the handoff
    senior_tok = set_current_identity({
        "actor": "senior_margaret",
        "role": Role.SENIOR.value,
        "allowed_seniors": {"margaret_01"},
    })
    try:
        commit_res = await verify_routine_state(confirm=True, transaction_id=tx_id)
        assert commit_res["status"] == "error"
        assert commit_res["error_code"] == ErrorCode.FORBIDDEN
        assert commit_res["database_writes"] == 0
        assert "Caregiver role is required" in commit_res["message"]

        # Ensure handoff was not committed to shift_handoffs table
        conn = storage.get_connection(auth_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM shift_handoffs")
            assert cursor.fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        current_identity.reset(senior_tok)


@pytest.mark.asyncio
async def test_caller_supplied_actor_impersonation_rejected(auth_db):
    """A non-admin caller cannot claim to be another actor via logged_by parameter."""
    tok = set_current_identity({
        "actor": "caregiver_sarah",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"margaret_01"},
    })
    try:
        # Sarah attempts to log as admin
        res = await log_daily_routine(
            senior_id="margaret_01",
            category="hydration",
            details="1 glass water",
            logged_by="admin",
        )
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert "cannot log routines on behalf of" in res["message"]
        assert res["database_writes"] == 0
    finally:
        current_identity.reset(tok)


# ===========================================================================
# 3. Cross-Senior Access Attempts Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_caregiver_david_cannot_log_for_margaret(auth_db):
    """Caregiver David (assigned to arthur_02) cannot log routines for margaret_01."""
    tok = set_current_identity({
        "actor": "caregiver_david",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"arthur_02"},
    })
    try:
        res = await log_daily_routine(
            senior_id="margaret_01",
            category="meal",
            details="Lunch soup",
        )
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0
        assert "Access to senior 'margaret_01' is forbidden" in res["message"]

        # Invariant: zero records in proposals or routine_logs
        conn = storage.get_connection(auth_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM routine_logs WHERE senior_id = 'margaret_01'")
            assert cursor.fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        current_identity.reset(tok)


@pytest.mark.asyncio
async def test_caregiver_david_cannot_read_summary_for_margaret(auth_db):
    """Caregiver David cannot inspect Margaret's daily summary."""
    tok = set_current_identity({
        "actor": "caregiver_david",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"arthur_02"},
    })
    try:
        res = await get_caregiver_summary(senior_id="margaret_01")
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0
    finally:
        current_identity.reset(tok)


@pytest.mark.asyncio
async def test_caregiver_sarah_cannot_flag_missed_routine_for_arthur(auth_db):
    """Caregiver Sarah (assigned to margaret_01) cannot flag missed routine for arthur_02."""
    tok = set_current_identity({
        "actor": "caregiver_sarah",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"margaret_01"},
    })
    try:
        res = await flag_missed_routine(
            senior_id="arthur_02",
            routine_name="morning_vitamins",
            scheduled_time="09:00",
        )
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0
    finally:
        current_identity.reset(tok)


def test_senior_margaret_cannot_read_arthur_resource(auth_db):
    """Senior Margaret cannot read the today resource for Arthur."""
    tok = set_current_identity({
        "actor": "senior_margaret",
        "role": Role.SENIOR.value,
        "allowed_seniors": {"margaret_01"},
    })
    try:
        res_str = get_senior_today_resource(id="arthur_02")
        import json
        res = json.loads(res_str)
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0
    finally:
        current_identity.reset(tok)


# ===========================================================================
# 4. Confirmation Using Another User's Transaction ID Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_cannot_confirm_other_seniors_transaction_id(auth_db):
    """Caregiver David cannot confirm a proposal created for Margaret Vance."""
    # 1. Sarah creates a proposal for Margaret
    sarah_tok = set_current_identity({
        "actor": "caregiver_sarah",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"margaret_01"},
    })
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="activity",
        details="Afternoon garden walk",
    )
    tx_id = prop["transaction_id"]
    current_identity.reset(sarah_tok)

    # 2. David attempts to confirm Sarah's proposal
    david_tok = set_current_identity({
        "actor": "caregiver_david",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"arthur_02"},
    })
    try:
        res = await verify_routine_state(confirm=True, transaction_id=tx_id)
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0

        # Invariant: proposal is NOT committed, routine_logs has 0 entries
        conn = storage.get_connection(auth_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM proposals WHERE transaction_id = ?", (tx_id,))
            assert cursor.fetchone()[0] == "pending"
            cursor.execute("SELECT COUNT(*) FROM routine_logs")
            assert cursor.fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        current_identity.reset(david_tok)


@pytest.mark.asyncio
async def test_cannot_preview_other_seniors_transaction_id(auth_db):
    """Caregiver David cannot preview a proposal created for Margaret."""
    sarah_tok = set_current_identity({
        "actor": "caregiver_sarah",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"margaret_01"},
    })
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="meal",
        details="Dinner soup",
    )
    tx_id = prop["transaction_id"]
    current_identity.reset(sarah_tok)

    david_tok = set_current_identity({
        "actor": "caregiver_david",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"arthur_02"},
    })
    try:
        res = await verify_routine_state(confirm=False, transaction_id=tx_id)
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0
    finally:
        current_identity.reset(david_tok)


@pytest.mark.asyncio
async def test_confirmation_with_mismatched_senior_id_rejected(auth_db):
    """Supplying a conflicting senior_id on confirm is rejected."""
    # Create proposal for Margaret
    sarah_tok = set_current_identity({
        "actor": "caregiver_sarah",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"margaret_01"},
    })
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="Water",
    )
    tx_id = prop["transaction_id"]
    current_identity.reset(sarah_tok)

    # Admin confirms but supplies senior_id="arthur_02"
    admin_tok = set_current_identity({
        "actor": "admin",
        "role": Role.ADMIN.value,
        "allowed_seniors": {"*"},
    })
    try:
        res = await verify_routine_state(
            confirm=True,
            transaction_id=tx_id,
            senior_id="arthur_02",  # Mismatch!
        )
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert "belongs to senior 'margaret_01', not 'arthur_02'" in res["message"]
        assert res["database_writes"] == 0

        # Invariant: proposal not committed
        conn = storage.get_connection(auth_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM proposals WHERE transaction_id = ?", (tx_id,))
            assert cursor.fetchone()[0] == "pending"
            cursor.execute("SELECT COUNT(*) FROM routine_logs")
            assert cursor.fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        current_identity.reset(admin_tok)


def test_direct_storage_commit_rejects_unauthorized_senior(auth_db):
    """Direct call to storage.commit_proposal revalidates active identity context."""
    prop = storage.create_proposal("margaret_01", "routine_log", {"category": "hydration", "details": "water"})
    tx_id = prop["transaction_id"]

    # Set identity to David (arthur_02 only)
    tok = set_current_identity({
        "actor": "caregiver_david",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"arthur_02"},
    })
    try:
        res = storage.commit_proposal(tx_id)
        assert res["status"] == "error"
        assert res["error_code"] == ErrorCode.FORBIDDEN
        assert res["database_writes"] == 0

        # Invariant: 0 writes in routine_logs
        conn = storage.get_connection(auth_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM routine_logs")
            assert cursor.fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        current_identity.reset(tok)


# ===========================================================================
# 5. Missing and Expired Transaction IDs Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_confirm_true_missing_transaction_id(auth_db):
    """confirm=True without transaction_id returns MISSING_TRANSACTION_ID."""
    res = await verify_routine_state(confirm=True, transaction_id=None)
    assert res["status"] == "error"
    assert res["error_code"] == ErrorCode.MISSING_TRANSACTION_ID
    assert res["database_writes"] == 0

    res_empty = await verify_routine_state(confirm=True, transaction_id="")
    assert res_empty["status"] == "error"
    assert res_empty["error_code"] == ErrorCode.MISSING_TRANSACTION_ID
    assert res_empty["database_writes"] == 0


@pytest.mark.asyncio
async def test_confirm_nonexistent_transaction_id(auth_db):
    """confirm=True with nonexistent transaction_id returns PROPOSAL_NOT_FOUND."""
    res = await verify_routine_state(confirm=True, transaction_id="tx_nonexistent_99999")
    assert res["status"] == "error"
    assert res["error_code"] == ErrorCode.PROPOSAL_NOT_FOUND
    assert res["database_writes"] == 0


@pytest.mark.asyncio
async def test_confirm_expired_proposal_transitions_status(auth_db):
    """Attempting to confirm an expired proposal marks status='expired' and commits 0 events."""
    past_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    prop = storage.create_proposal(
        "margaret_01",
        "routine_log",
        {"category": "vitamins", "details": "morning vitamins"},
        now=past_time,
    )
    tx_id = prop["transaction_id"]

    # Confirm proposal in current time (proposal has expired)
    res = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert res["status"] == "error"
    assert res["error_code"] == ErrorCode.PROPOSAL_EXPIRED
    assert res["database_writes"] == 0

    # Invariant: status in DB is now 'expired', routine_logs has 0 entries
    conn = storage.get_connection(auth_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM proposals WHERE transaction_id = ?", (tx_id,))
        assert cursor.fetchone()[0] == "expired"
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_preview_expired_proposal_rejected(auth_db):
    """Previewing an expired proposal is rejected with PROPOSAL_EXPIRED."""
    past_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    prop = storage.create_proposal(
        "margaret_01",
        "routine_log",
        {"category": "meal", "details": "past meal"},
        now=past_time,
    )
    tx_id = prop["transaction_id"]

    res = await verify_routine_state(confirm=False, transaction_id=tx_id)
    assert res["status"] == "error"
    assert res["error_code"] == ErrorCode.PROPOSAL_EXPIRED
    assert res["database_writes"] == 0


# ===========================================================================
# 6. Cancelled and Already-Committed Proposals Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_confirm_cancelled_proposal_rejected(auth_db):
    """A cancelled proposal cannot be committed."""
    prop = storage.create_proposal(
        "margaret_01",
        "routine_log",
        {"category": "activity", "details": "walk"},
    )
    tx_id = prop["transaction_id"]

    # Cancel proposal
    cancel_res = storage.cancel_proposal(tx_id)
    assert cancel_res["status"] == "success"

    # Attempt to commit
    commit_res = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert commit_res["status"] == "error"
    assert commit_res["error_code"] == ErrorCode.PROPOSAL_CANCELLED
    assert commit_res["database_writes"] == 0

    # Invariant: 0 rows in routine_logs
    conn = storage.get_connection(auth_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_preview_cancelled_proposal_rejected(auth_db):
    """Previewing a cancelled proposal is rejected with PROPOSAL_CANCELLED."""
    prop = storage.create_proposal(
        "margaret_01",
        "routine_log",
        {"category": "wellness", "details": "resting"},
    )
    tx_id = prop["transaction_id"]
    storage.cancel_proposal(tx_id)

    res = await verify_routine_state(confirm=False, transaction_id=tx_id)
    assert res["status"] == "error"
    assert res["error_code"] == ErrorCode.PROPOSAL_CANCELLED
    assert res["database_writes"] == 0


def test_cancel_already_committed_proposal_fails(auth_db):
    """Attempting to cancel an already-committed proposal returns an error."""
    prop = storage.create_proposal("margaret_01", "routine_log", {"category": "hydration"})
    tx_id = prop["transaction_id"]
    storage.commit_proposal(tx_id)

    res = storage.cancel_proposal(tx_id)
    assert res["status"] == "error"
    assert res["error_code"] == "PROPOSAL_COMMITTED"
    assert res["database_writes"] == 0


# ===========================================================================
# 7. Duplicate Confirmation & Replay Protection Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_duplicate_confirmation_idempotent_no_duplicate_records(auth_db):
    """Replaying confirm=True on an already-committed proposal creates zero duplicate events."""
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="500ml water",
    )
    tx_id = prop["transaction_id"]

    # First commit
    res1 = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert res1["status"] == "COMMITTED"
    assert res1["database_writes"] == 1
    assert "result_id" in res1

    # Second commit (replay)
    res2 = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert res2["status"] == "ALREADY_COMMITTED"
    assert res2["database_writes"] == 0
    assert res2["result_id"] == res1["result_id"]

    # Third commit (replay)
    res3 = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert res3["status"] == "ALREADY_COMMITTED"
    assert res3["database_writes"] == 0

    # Invariant: EXACTLY 1 row in routine_logs
    conn = storage.get_connection(auth_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM routine_logs WHERE senior_id = 'margaret_01'")
        assert cursor.fetchone()[0] == 1
    finally:
        conn.close()


# ===========================================================================
# 8. Concurrent Confirmation Attempts Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_concurrent_confirmation_attempts_atomic(auth_db):
    """Concurrent confirmation calls execute atomically; exactly one commits."""
    prop = storage.create_proposal(
        "margaret_01",
        "routine_log",
        {"category": "meal", "details": "Hearty breakfast"},
    )
    tx_id = prop["transaction_id"]

    # Concurrently launch 10 confirmation attempts
    async def confirm_task():
        return await verify_routine_state(confirm=True, transaction_id=tx_id)

    results = await asyncio.gather(*(confirm_task() for _ in range(10)))

    committed_count = sum(1 for r in results if r["status"] == "COMMITTED")
    already_committed_count = sum(1 for r in results if r["status"] == "ALREADY_COMMITTED")
    conflict_count = sum(1 for r in results if r.get("error_code") == "PROPOSAL_STATE_CONFLICT")

    # Invariant: EXACTLY ONE caller received COMMITTED
    assert committed_count == 1
    # All remaining callers were safely serialized and received ALREADY_COMMITTED or PROPOSAL_STATE_CONFLICT
    assert already_committed_count + conflict_count == 9

    # Invariant: EXACTLY ONE record was written to routine_logs
    conn = storage.get_connection(auth_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM routine_logs WHERE senior_id = 'margaret_01'")
        assert cursor.fetchone()[0] == 1

        cursor.execute("SELECT status FROM proposals WHERE transaction_id = ?", (tx_id,))
        assert cursor.fetchone()[0] == "committed"
    finally:
        conn.close()
