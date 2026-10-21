"""Tests for janus.auth, janus.audit, and janus.gate modules."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from janus import storage
from janus.auth import (
    DEMO_TOKEN,
    extract_bearer_token,
    verify_token,
    check_senior_access,
    get_actor_from_header,
    AuthError,
    Role,
)
from janus.audit import verify_audit_chain, main as audit_main
from janus.gate import ConfirmationGate
from janus.errors import InvalidCategoryError, ProposalExpiredError, ProposalNotFoundError, ErrorCode


@pytest.fixture
def test_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_auth_audit.db")
    storage.init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Auth Module Tests
# ---------------------------------------------------------------------------
def test_extract_bearer_token():
    assert extract_bearer_token("Bearer test-token-123") == "test-token-123"
    assert extract_bearer_token("bearer my-token") == "my-token"
    assert extract_bearer_token("BEARER uppercase") == "uppercase"
    assert extract_bearer_token("Basic dXNlcjpwYXNz") is None
    assert extract_bearer_token("") is None
    assert extract_bearer_token(None) is None


def test_verify_token_valid():
    is_valid, claims, reason = verify_token(DEMO_TOKEN)
    assert is_valid is True
    assert claims["actor"] == "caregiver_david"
    assert claims["role"] == "caregiver"
    assert "margaret_01" in claims["allowed_seniors"]


def test_verify_token_demo_prefix():
    is_valid, claims, _ = verify_token("janus-demo-custom-key")
    assert is_valid is True
    assert claims["actor"] == "demo_user"
    assert "*" in claims["allowed_seniors"]


def test_verify_token_invalid_and_empty():
    is_valid, claims, _ = verify_token("invalid-random-token")
    assert is_valid is False
    assert claims is None

    is_valid, claims, _ = verify_token(None)
    assert is_valid is False
    assert claims is None


def test_check_senior_access():
    # Empty token permits ambient simulator access
    assert check_senior_access(None, "margaret_01") is True

    # Valid demo token permits margaret_01 and wildcard
    assert check_senior_access(DEMO_TOKEN, "margaret_01") is True
    assert check_senior_access(DEMO_TOKEN, "any_other_senior") is True

    # Token with restricted list
    custom_registry = {
        "restricted-tok": {
            "actor": "sarah",
            "role": "caregiver",
            "allowed_seniors": {"margaret_01"},
        }
    }
    assert check_senior_access("restricted-tok", "margaret_01", token_registry=custom_registry) is True
    assert check_senior_access("restricted-tok", "unauthorized_senior", token_registry=custom_registry) is False


def test_get_actor_from_header():
    assert get_actor_from_header(f"Bearer {DEMO_TOKEN}") == "caregiver_david"
    assert get_actor_from_header("Bearer invalid-tok", default_actor="senior_voice") == "senior_voice"
    assert get_actor_from_header(None, default_actor="senior_voice") == "senior_voice"


def test_auth_error_exception():
    err = AuthError("Unauthorized senior access")
    assert err.code == ErrorCode.FORBIDDEN
    assert "Unauthorized senior access" in str(err)
    assert Role.CAREGIVER == "caregiver"


# ---------------------------------------------------------------------------
# Audit Module Tests
# ---------------------------------------------------------------------------
def test_verify_audit_chain_empty(test_db):
    is_valid, broken_id, msg = verify_audit_chain(db_path=test_db)
    assert is_valid is True
    assert broken_id is None
    assert "empty" in msg.lower()


def test_verify_audit_chain_valid_entries(test_db):
    # Log several events to populate audit chain
    p1 = storage.create_proposal("margaret_01", "routine_log", {"category": "hydration", "details": "water"}, db_path=test_db)
    storage.commit_proposal(p1["transaction_id"], db_path=test_db)

    p2 = storage.create_proposal("margaret_01", "routine_log", {"category": "meal", "details": "lunch"}, db_path=test_db)
    storage.commit_proposal(p2["transaction_id"], db_path=test_db)

    is_valid, broken_id, msg = verify_audit_chain(db_path=test_db)
    assert is_valid is True
    assert broken_id is None
    assert "verified successfully" in msg


def test_verify_audit_chain_detects_tamper(test_db):
    # Log an event
    p1 = storage.create_proposal("margaret_01", "routine_log", {"category": "hydration", "details": "water"}, db_path=test_db)
    storage.commit_proposal(p1["transaction_id"], db_path=test_db)

    # Manually tamper with hash in audit_log
    conn = storage.get_connection(test_db)
    with conn:
        conn.execute("UPDATE audit_log SET hash = 'corrupted_hash_12345' WHERE id = 1")
    conn.close()

    is_valid, broken_id, msg = verify_audit_chain(db_path=test_db)
    assert is_valid is False
    assert broken_id == 1
    assert "mismatch" in msg


def test_audit_main_cli(test_db, monkeypatch):
    # Verify CLI runner returns 0 for valid db
    code = audit_main(["verify", "--db", test_db])
    assert code == 0


# ---------------------------------------------------------------------------
# Gate Module Tests
# ---------------------------------------------------------------------------
def test_confirmation_gate_workflow(test_db):
    gate = ConfirmationGate(db_path=test_db)

    # 1. Propose routine
    prop = gate.propose(
        senior_id="margaret_01",
        action_type="routine_log",
        payload={"category": "hydration", "details": "300ml water"},
        actor="senior_voice",
    )
    tx_id = prop["transaction_id"]
    assert prop["status"] == "pending"

    # 2. Preview proposal
    preview = gate.preview(tx_id)
    assert preview["transaction_id"] == tx_id

    # 3. Commit proposal
    commit_res = gate.commit(tx_id)
    assert commit_res["status"] == "COMMITTED"
    assert commit_res["database_writes"] == 1

    # 4. Replay commit (idempotent)
    replay = gate.commit(tx_id)
    assert replay["status"] == "ALREADY_COMMITTED"
    assert replay["database_writes"] == 0


def test_confirmation_gate_cancel(test_db):
    gate = ConfirmationGate(db_path=test_db)
    prop = gate.propose("margaret_01", "routine_log", {"category": "meal", "details": "snack"})
    tx_id = prop["transaction_id"]

    res = gate.cancel(tx_id)
    assert res["status"] == "success"

    # Commit cancelled proposal fails
    commit_res = gate.commit(tx_id)
    assert commit_res["status"] == "error"
    assert commit_res["error_code"] == ErrorCode.PROPOSAL_CANCELLED


def test_check_senior_access_invalid_token():
    assert check_senior_access("invalid-token-12345", "margaret_01") is False


def test_confirmation_gate_invalid_category(test_db):
    gate = ConfirmationGate(db_path=test_db)
    with pytest.raises(InvalidCategoryError):
        gate.propose("margaret_01", "routine_log", {"category": "unapproved_category"})
    with pytest.raises(InvalidCategoryError):
        gate.propose("margaret_01", "routine_log", {})


def test_confirmation_gate_not_found(test_db):
    gate = ConfirmationGate(db_path=test_db)
    with pytest.raises(ProposalNotFoundError):
        gate.preview("tx_nonexistent_123")


def test_confirmation_gate_preview_expired(test_db):
    gate = ConfirmationGate(db_path=test_db)
    prop = gate.propose("margaret_01", "routine_log", {"category": "hydration"})
    tx_id = prop["transaction_id"]
    future_time = datetime(2099, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ProposalExpiredError):
        gate.preview(tx_id, now=future_time)


def test_confirmation_gate_commit_missing_tx(test_db):
    gate = ConfirmationGate(db_path=test_db)
    res = gate.commit("")
    assert res["status"] == "error"
    assert res["error_code"] == ErrorCode.MISSING_TRANSACTION_ID


def test_audit_chain_prev_hash_tamper(test_db):
    gate = ConfirmationGate(db_path=test_db)
    prop1 = gate.propose("margaret_01", "routine_log", {"category": "hydration"})
    gate.commit(prop1["transaction_id"])
    prop2 = gate.propose("margaret_01", "routine_log", {"category": "activity"})
    gate.commit(prop2["transaction_id"])

    # Tamper with prev_hash in second row
    conn = storage.get_connection(test_db)
    conn.execute("UPDATE audit_log SET prev_hash = 'corrupted_prev_hash' WHERE id = 2")
    conn.commit()
    conn.close()

    is_valid, broken_id, msg = verify_audit_chain(db_path=test_db)
    assert is_valid is False
    assert broken_id == 2
    assert "prev_hash mismatch" in msg

    # CLI verification failure code
    ret = audit_main(["verify", "--db", test_db])
    assert ret == 1
