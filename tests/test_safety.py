"""Tests for Janus (ElderSync) — Shared Non-Clinical Medical Safety Policy.

Validates deterministic safety policy classification, rule precedence,
input sanitization, and MCP tool guard integration.
"""

import pytest

from janus.safety import (
    MAX_INPUT_LENGTH,
    SafetyAssessment,
    SafetyOutcome,
    assess_safety,
    is_routine_allowed,
)
from janus.server import log_daily_routine, verify_routine_state
from janus import storage


# ===========================================================================
# 1. Ordinary Hydration, Meals, Activity & Wellness Reports
# ===========================================================================

@pytest.mark.parametrize(
    "text,category",
    [
        ("500ml water", "hydration"),
        ("Drank a glass of cold water", "hydration"),
        ("Finished 2 cups of herbal chamomile tea", "hydration"),
        ("Had a glass of fresh orange juice with breakfast", "hydration"),
        ("Morning oatmeal with blueberries and honey", "meal"),
        ("Finished half a turkey sandwich and vegetable soup for lunch", "meal"),
        ("Dinner: baked salmon and steamed broccoli", "meal"),
        ("Afternoon snack: apple slices with peanut butter", "meal"),
        ("Morning porch and garden walk for 15 minutes", "activity"),
        ("Completed gentle chair yoga stretching session", "activity"),
        ("Walked around the living room and hallway", "activity"),
        ("Tended to flowers on the back patio", "activity"),
        ("Evening check-in: rested quietly in armchair", "wellness"),
        ("Had a pleasant chat with neighbor on the phone", "wellness"),
        ("Feeling good and in cheerful spirits today", "wellness"),
    ],
)
def test_ordinary_routine_reports_allowed(text: str, category: str):
    """Ordinary non-clinical daily living routines must be ROUTINE_ALLOWED."""
    res = assess_safety(text, category=category)
    assert res.outcome == SafetyOutcome.ROUTINE_ALLOWED
    assert res.is_allowed is True
    assert is_routine_allowed(text, category=category) is True
    assert res.matched_rule is None


# ===========================================================================
# 2. Scheduled Vitamins vs. Medication-Change Requests
# ===========================================================================

@pytest.mark.parametrize(
    "vitamin_text",
    [
        "Took morning vitamins",
        "Margaret took her daily multivitamin",
        "Vitamin D 1000 IU taken with breakfast",
        "Scheduled morning vitamins completed",
        "Daily calcium supplement taken",
        "Took morning vitamin C with a glass of water",
        "Had her regular daily vitamins as scheduled",
    ],
)
def test_scheduled_vitamins_reports_allowed(vitamin_text: str):
    """Reports of completed scheduled vitamins must NEVER be blocked as medication changes."""
    res = assess_safety(vitamin_text, category="vitamins")
    assert res.outcome == SafetyOutcome.ROUTINE_ALLOWED
    assert res.is_allowed is True
    assert is_routine_allowed(vitamin_text, category="vitamins") is True


@pytest.mark.parametrize(
    "med_change_text",
    [
        "Increase lisinopril dose to 20mg",
        "Doctor said to double the dose of blood pressure pills",
        "Reduce the medication to half",
        "Cut the pill in half before taking it",
        "Give an extra pill of metformin tonight",
        "Stop taking blood pressure medication",
        "Discontinue the antibiotic",
        "Skip the morning dose of medicine",
        "Please prescribe a painkiller for Margaret",
        "Adjust insulin units before dinner",
        "Start taking warfarin 5mg daily",
    ],
)
def test_medication_change_requests_blocked(med_change_text: str):
    """Medication dosage changes, starting/stopping medicines, and prescription advice must be blocked."""
    res = assess_safety(med_change_text, category="vitamins")
    assert res.outcome == SafetyOutcome.MEDICAL_ACTION_BLOCKED
    assert res.is_allowed is False
    assert is_routine_allowed(med_change_text) is False
    assert res.matched_rule is not None
    assert "physician" in res.guidance.lower() or "pharmacist" in res.guidance.lower()


# ===========================================================================
# 3. Clear Emergency Indicators
# ===========================================================================

@pytest.mark.parametrize(
    "emergency_text,expected_rule",
    [
        ("Margaret has severe crushing chest pain", "cardiac_chest_pain"),
        ("Grandma is experiencing severe chest tightness", "cardiac_chest_pain"),
        ("Margaret can't breathe and is gasping for air", "respiratory_distress"),
        ("Difficulty breathing, turning blue", "respiratory_distress"),
        ("Grandmother is choking on food", "respiratory_distress"),
        ("Margaret collapsed and is unconscious on the floor", "unresponsive_consciousness"),
        ("She passed out and won't wake up", "unresponsive_consciousness"),
        ("Fell down and can't get up, bleeding heavily", "severe_fall_trauma"),
        ("Sudden facial droop and slurred speech", "stroke_neurological"),
        ("Sudden paralysis in right arm and leg", "stroke_neurological"),
        ("Margaret is having a seizure and convulsing", "stroke_neurological"),
        ("Severe bleeding from head wound", "severe_hemorrhage"),
        ("Coughing up blood after walk", "severe_hemorrhage"),
        ("Throat is closing and swelling, severe allergic reaction", "anaphylaxis_poison_overdose"),
        ("Accidentally swallowed bleach from kitchen", "anaphylaxis_poison_overdose"),
        ("Call 911 immediately, need an ambulance", "explicit_emergency_call"),
    ],
)
def test_clear_emergency_indicators(emergency_text: str, expected_rule: str):
    """Acute emergency indicators must trigger EMERGENCY_GUIDANCE with immediate 911 advice."""
    res = assess_safety(emergency_text)
    assert res.outcome == SafetyOutcome.EMERGENCY_GUIDANCE
    assert res.is_allowed is False
    assert res.matched_rule == expected_rule
    assert "911" in res.guidance
    assert is_routine_allowed(emergency_text) is False


# ===========================================================================
# 4. Emergency Indicators Mixed with Ordinary Routine Words
# ===========================================================================

@pytest.mark.parametrize(
    "mixed_text,category",
    [
        ("Margaret drank a glass of water but then collapsed and is unconscious", "hydration"),
        ("Finished morning oatmeal and now having severe chest pain", "meal"),
        ("Took morning walk on the porch and suddenly can't breathe", "activity"),
        ("Took scheduled vitamins but is choking and suffocating", "vitamins"),
        ("Had lunch, then had a bad fall and can't get up", "meal"),
        ("Drank tea, then face started drooping with slurred speech", "hydration"),
    ],
)
def test_emergency_takes_precedence_over_routine_words(mixed_text: str, category: str):
    """Emergency indicators must take strict priority even when mixed with routine words or categories."""
    res = assess_safety(mixed_text, category=category)
    assert res.outcome == SafetyOutcome.EMERGENCY_GUIDANCE
    assert res.is_allowed is False
    assert "911" in res.guidance
    assert is_routine_allowed(mixed_text, category=category) is False


# ===========================================================================
# 5. Ambiguous Health Requests & Priority Over Clarification
# ===========================================================================

@pytest.mark.parametrize(
    "ambiguous_text,expected_rule",
    [
        ("Margaret has a slight headache after breakfast", "non_emergency_symptom"),
        ("Feeling a little dizzy and lightheaded this morning", "non_emergency_symptom"),
        ("Mild nausea and upset stomach after lunch", "non_emergency_symptom"),
        ("Margaret feels sick and weak today", "general_unwell_complaint"),
        ("Not feeling well, has a low fever", "non_emergency_symptom"),
        ("Knee pain and swollen ankle after sitting", "non_emergency_symptom"),
        ("Blood pressure is 150/95 today", "clinical_vital_signs"),
        ("Blood sugar is 210 mg/dL", "clinical_vital_signs"),
        ("Administered morning insulin dose", "unverified_prescription_reporting"),
        ("Took lisinopril blood pressure pill", "unverified_prescription_reporting"),
        ("Should she rest or see a doctor for this?", "medical_inquiry"),
    ],
)
def test_ambiguous_health_requests_require_clarification(ambiguous_text: str, expected_rule: str):
    """Non-emergency symptoms, vital signs, and prescription reports must require clarification."""
    res = assess_safety(ambiguous_text)
    assert res.outcome == SafetyOutcome.CLARIFICATION_REQUIRED
    assert res.is_allowed is False
    assert res.matched_rule == expected_rule
    assert "clarify" in res.guidance.lower() or "caregiver" in res.guidance.lower()


def test_emergency_precedence_over_ambiguous_symptoms():
    """Emergency guidance must NEVER be delayed or overridden by non-emergency symptom matches."""
    text = "Margaret has a headache and mild nausea, but also has crushing chest pain and can't breathe"
    res = assess_safety(text)
    assert res.outcome == SafetyOutcome.EMERGENCY_GUIDANCE
    assert "911" in res.guidance


# ===========================================================================
# 6. Caller-Supplied Labels Must Not Be Trusted
# ===========================================================================

def test_caller_supplied_safety_labels_ignored():
    """Caller-supplied flags such as is_safe=True or safe routine categories must be ignored."""
    # Emergency text labeled as 'hydration' with is_safe=True
    res_emergency = assess_safety(
        "Grandmother fell and is unconscious",
        category="hydration",
        is_safe=True,
        emergency=False,
    )
    assert res_emergency.outcome == SafetyOutcome.EMERGENCY_GUIDANCE
    assert res_emergency.is_allowed is False

    # Medication change labeled as 'wellness' with is_safe=True
    res_med = assess_safety(
        "Double the dose of lisinopril tomorrow",
        category="wellness",
        is_safe=True,
    )
    assert res_med.outcome == SafetyOutcome.MEDICAL_ACTION_BLOCKED
    assert res_med.is_allowed is False


# ===========================================================================
# 7. Empty, Malformed, and Oversized Inputs
# ===========================================================================

def test_empty_input_without_category():
    """Empty input with no valid category requires clarification."""
    res = assess_safety("")
    assert res.outcome == SafetyOutcome.CLARIFICATION_REQUIRED
    assert res.matched_rule == "empty_input"

    res_spaces = assess_safety("   ", category=None)
    assert res_spaces.outcome == SafetyOutcome.CLARIFICATION_REQUIRED


def test_empty_input_with_valid_category():
    """Empty input with a valid non-clinical category is permitted."""
    res = assess_safety("", category="hydration")
    assert res.outcome == SafetyOutcome.ROUTINE_ALLOWED
    assert res.is_allowed is True


def test_malformed_inputs_handled_conservatively():
    """Non-string or malformed inputs must be safely rejected with CLARIFICATION_REQUIRED."""
    # Integer input
    res_int = assess_safety(12345)
    assert res_int.outcome == SafetyOutcome.CLARIFICATION_REQUIRED
    assert res_int.matched_rule == "malformed_non_string"

    # Dict input
    res_dict = assess_safety({"details": "water"})
    assert res_dict.outcome == SafetyOutcome.CLARIFICATION_REQUIRED
    assert res_dict.matched_rule == "malformed_non_string"

    # Control characters / null byte
    res_null = assess_safety("Drank water\x00call 911")
    assert res_null.outcome == SafetyOutcome.CLARIFICATION_REQUIRED
    assert res_null.matched_rule == "malformed_control_chars"


def test_oversized_input_rejected():
    """Inputs exceeding MAX_INPUT_LENGTH must be conservatively rejected."""
    oversized = "glass of water " * 100  # 1500 chars > MAX_INPUT_LENGTH (1000)
    assert len(oversized) > MAX_INPUT_LENGTH
    res = assess_safety(oversized)
    assert res.outcome == SafetyOutcome.CLARIFICATION_REQUIRED
    assert res.matched_rule == "oversized_input_exceeded"
    assert "exceeds" in res.reason.lower()


# ===========================================================================
# 8. Deterministic Repeated Classification
# ===========================================================================

def test_deterministic_repeated_classification():
    """Classification must be strictly deterministic across repeated invocations."""
    test_cases = [
        ("Drank 500ml water", "hydration", SafetyOutcome.ROUTINE_ALLOWED),
        ("Took morning vitamins", "vitamins", SafetyOutcome.ROUTINE_ALLOWED),
        ("Grandma is having crushing chest pain", "wellness", SafetyOutcome.EMERGENCY_GUIDANCE),
        ("Double the dose of insulin", "wellness", SafetyOutcome.MEDICAL_ACTION_BLOCKED),
        ("Feels dizzy and has a headache", "wellness", SafetyOutcome.CLARIFICATION_REQUIRED),
    ]

    for text, cat, expected in test_cases:
        first = assess_safety(text, category=cat)
        assert first.outcome == expected

        # Repeat 50 times to guarantee determinism
        for _ in range(50):
            repeated = assess_safety(text, category=cat)
            assert repeated.outcome == first.outcome
            assert repeated.reason == first.reason
            assert repeated.guidance == first.guidance
            assert repeated.matched_rule == first.matched_rule
            assert repeated.is_allowed == first.is_allowed


# ===========================================================================
# 9. MCP Tool Integration Invariants (log_daily_routine & verify_routine_state)
# ===========================================================================

@pytest.mark.asyncio
async def test_log_daily_routine_refuses_emergency_with_zero_writes(isolated_db):
    """Calling log_daily_routine with emergency indicators must return EMERGENCY_GUIDANCE with 0 writes."""
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="Grandma collapsed and is unconscious on the kitchen floor",
    )
    assert res["status"] == "error"
    assert res["error_code"] == "EMERGENCY_GUIDANCE"
    assert res["database_writes"] == 0
    assert "911" in res["message"]

    # Invariant: ZERO proposals or routine logs written to SQLite
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proposals")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_log_daily_routine_refuses_medication_changes_with_zero_writes(isolated_db):
    """Calling log_daily_routine with medication modification requests must return MEDICAL_ACTION_BLOCKED."""
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="vitamins",
        details="Doctor said to increase lisinopril dose to 20mg",
    )
    assert res["status"] == "error"
    assert res["error_code"] == "MEDICAL_ACTION_BLOCKED"
    assert res["database_writes"] == 0
    assert "physician" in res["message"].lower() or "pharmacist" in res["message"].lower()

    # Invariant: ZERO proposals written
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proposals")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_log_daily_routine_refuses_ambiguous_health_with_zero_writes(isolated_db):
    """Calling log_daily_routine with ambiguous clinical symptoms must return CLARIFICATION_REQUIRED."""
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="wellness",
        details="Margaret has a slight headache and feels dizzy",
    )
    assert res["status"] == "error"
    assert res["error_code"] == "CLARIFICATION_REQUIRED"
    assert res["database_writes"] == 0

    # Invariant: ZERO proposals written
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proposals")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_log_daily_routine_permits_safe_routine_and_creates_proposal(isolated_db):
    """Calling log_daily_routine with safe routine details creates a pending proposal."""
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="500ml water",
    )
    assert res["status"] == "pending_confirmation"
    assert res["database_writes"] == 0
    assert "transaction_id" in res
    assert res["category"] == "hydration"


@pytest.mark.asyncio
async def test_verify_routine_state_handoff_safety_guard(isolated_db):
    """Shift handoff proposals containing emergency or clinical notes must be rejected."""
    res = await verify_routine_state(
        confirm=False,
        senior_id="margaret_01",
        action_type="shift_handoff",
        payload={
            "departing_caregiver": "Sarah",
            "incoming_caregiver": "David",
            "handoff_notes": "Margaret fell down and can't get up, bleeding heavily",
        },
    )
    assert res["status"] == "error"
    assert res["error_code"] == "EMERGENCY_GUIDANCE"
    assert res["database_writes"] == 0

    # Invariant: ZERO proposals written
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proposals")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


# ===========================================================================
# 10. Part 3 Mandatory Invariants & Protected Mutation Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_unsafe_details_cannot_be_disguised_as_allowed_category(isolated_db):
    """Unsafe details disguised under allowed routine categories must be blocked before proposal creation."""
    # Attempt 1: Medication modification disguised as 'hydration'
    res_med = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="Increase lisinopril dose to 20mg daily",
        routine_type="hydration",
    )
    assert res_med["status"] == "error"
    assert res_med["error_code"] == "MEDICAL_ACTION_BLOCKED"
    assert res_med["database_writes"] == 0

    # Attempt 2: Emergency indicator disguised as 'meal'
    res_emerg = await log_daily_routine(
        senior_id="margaret_01",
        category="meal",
        details="Margaret fell down, is bleeding heavily and cannot get up",
        routine_type="meal",
    )
    assert res_emerg["status"] == "error"
    assert res_emerg["error_code"] == "EMERGENCY_GUIDANCE"
    assert res_emerg["database_writes"] == 0

    # Invariant: ZERO proposals or routine_logs written to database
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proposals")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_direct_mcp_call_bypassing_frontend_is_blocked(isolated_db):
    """Direct MCP backend tool call bypassing any frontend validation receives identical protection."""
    # Direct MCP backend tool call with acute emergency
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="activity",
        details="Grandma collapsed and is unresponsive",
    )
    assert res["status"] == "error"
    assert res["error_code"] == "EMERGENCY_GUIDANCE"
    assert res["database_writes"] == 0
    assert "911" in res["message"]

    # Invariant: No proposal created
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proposals")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_blocked_request_cannot_commit_event(isolated_db):
    """A proposal with unsafe payload stored in the database cannot be committed to routine_logs."""
    conn = storage.get_connection(isolated_db)
    tx_id = "tx_unsafe_test_001"
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO proposals (
                    transaction_id, senior_id, action_type, payload_json,
                    actor, created_at, expires_at, status
                ) VALUES (?, ?, 'routine_log', ?, 'test_actor', '2026-10-22T00:00:00Z', '2099-12-31T23:59:59Z', 'pending')
                """,
                (tx_id, "margaret_01", '{"category": "hydration", "details": "crushing chest pain and heart attack"}'),
            )
    finally:
        conn.close()

    # Attempt to commit the unsafe proposal
    res = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert res["status"] == "error"
    assert res["error_code"] == "EMERGENCY_GUIDANCE"
    assert res["database_writes"] == 0

    # Invariant: ZERO records in routine_logs
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 0

        # Proposal status was transitioned to 'blocked'
        cursor.execute("SELECT status FROM proposals WHERE transaction_id = ?", (tx_id,))
        assert cursor.fetchone()[0] == "blocked"

        # Tamper-evident audit log recorded the blocked commit
        cursor.execute("SELECT outcome, tool FROM audit_log WHERE transaction_id = ?", (tx_id,))
        audit_entry = cursor.fetchone()
        assert audit_entry is not None
        assert "BLOCKED_EMERGENCY_GUIDANCE" in audit_entry["outcome"]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_missing_expired_cancelled_or_replayed_cannot_cause_unauthorized_commit(isolated_db):
    """Missing, expired, cancelled, or replayed confirmations cannot cause unauthorized commits."""
    # 1. Missing transaction_id on confirm=True
    res_missing = await verify_routine_state(confirm=True, transaction_id=None)
    assert res_missing["status"] == "error"
    assert res_missing["error_code"] == "MISSING_TRANSACTION_ID"
    assert res_missing["database_writes"] == 0

    # 2. Expired proposal
    conn = storage.get_connection(isolated_db)
    tx_expired = "tx_expired_001"
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO proposals (
                    transaction_id, senior_id, action_type, payload_json,
                    actor, created_at, expires_at, status
                ) VALUES (?, ?, 'routine_log', ?, 'test_actor', '2020-01-01T00:00:00Z', '2020-01-01T00:05:00Z', 'pending')
                """,
                (tx_expired, "margaret_01", '{"category": "hydration", "details": "glass of water"}'),
            )
    finally:
        conn.close()

    res_exp = await verify_routine_state(confirm=True, transaction_id=tx_expired)
    assert res_exp["status"] == "error"
    assert res_exp["error_code"] == "PROPOSAL_EXPIRED"
    assert res_exp["database_writes"] == 0

    # 3. Cancelled proposal
    tx_cancel = "tx_cancel_001"
    conn = storage.get_connection(isolated_db)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO proposals (
                    transaction_id, senior_id, action_type, payload_json,
                    actor, created_at, expires_at, status
                ) VALUES (?, ?, 'routine_log', ?, 'test_actor', '2026-10-22T00:00:00Z', '2026-10-22T23:59:59Z', 'cancelled')
                """,
                (tx_cancel, "margaret_01", '{"category": "hydration", "details": "glass of water"}'),
            )
    finally:
        conn.close()

    res_cnc = await verify_routine_state(confirm=True, transaction_id=tx_cancel)
    assert res_cnc["status"] == "error"
    assert res_cnc["error_code"] == "PROPOSAL_CANCELLED"
    assert res_cnc["database_writes"] == 0

    # 4. Replay of already committed proposal
    # Create valid proposal
    prop = await log_daily_routine(senior_id="margaret_01", category="hydration", details="300ml water")
    tx_valid = prop["transaction_id"]

    # First commit: succeeds
    res_c1 = await verify_routine_state(confirm=True, transaction_id=tx_valid)
    assert res_c1["status"] == "COMMITTED"
    assert res_c1["database_writes"] == 1

    # Second commit: returns ALREADY_COMMITTED with 0 additional writes
    res_c2 = await verify_routine_state(confirm=True, transaction_id=tx_valid)
    assert res_c2["status"] == "ALREADY_COMMITTED"
    assert res_c2["database_writes"] == 0

    # Invariant: Exactly 1 record written across all operations
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_authorization_failure_cannot_mutate_another_senior_data(isolated_db, monkeypatch):
    """Authorization failure prevents cross-senior data mutation."""
    from janus.auth import set_current_identity
    # Restrict identity to margaret_01 only
    set_current_identity({
        "actor": "senior_margaret",
        "role": "senior",
        "allowed_seniors": {"margaret_01"},
        "token": "janus-demo-senior-margaret",
    })

    # Attempt to log routine for arthur_02
    res_log = await log_daily_routine(
        senior_id="arthur_02",
        category="hydration",
        details="500ml water",
    )
    assert res_log["status"] == "error"
    assert res_log["error_code"] == "FORBIDDEN"
    assert res_log["database_writes"] == 0

    # Attempt to confirm routine for arthur_02
    res_ver = await verify_routine_state(
        confirm=False,
        senior_id="arthur_02",
        action_type="shift_handoff",
    )
    assert res_ver["status"] == "error"
    assert res_ver["error_code"] == "FORBIDDEN"
    assert res_ver["database_writes"] == 0

    # Invariant: ZERO records written for Arthur
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proposals WHERE senior_id = 'arthur_02'")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM routine_logs WHERE senior_id = 'arthur_02'")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_emergency_guidance_takes_priority_over_routine_processing(isolated_db):
    """Emergency guidance takes priority over routine processing even with complex mixed input."""
    mixed_details = "Margaret drank 500ml water and walked in garden, but suddenly started choking and cannot breathe"
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details=mixed_details,
    )
    assert res["status"] == "error"
    assert res["error_code"] == "EMERGENCY_GUIDANCE"
    assert res["database_writes"] == 0
    assert "911" in res["message"]

    # Invariant: No proposal created in proposals table
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proposals")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_successful_ordinary_routine_works_through_existing_workflow(isolated_db):
    """Ordinary safe routine completes full 2-step confirmation lifecycle and commits successfully."""
    # Step 1: Propose routine (creates pending proposal, 0 routine_logs writes)
    prop = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="500ml water",
    )
    assert prop["status"] == "pending_confirmation"
    assert prop["database_writes"] == 0
    tx_id = prop["transaction_id"]
    assert tx_id.startswith("tx_")

    # Verify: 1 proposal in proposals, 0 in routine_logs
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM proposals WHERE transaction_id = ?", (tx_id,))
        assert cursor.fetchone()[0] == "pending"
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()

    # Step 2: Preview proposal (0 writes)
    preview = await verify_routine_state(confirm=False, transaction_id=tx_id)
    assert preview["status"] == "PROPOSAL_PREVIEW"
    assert preview["database_writes"] == 0
    assert preview["transaction_id"] == tx_id

    # Step 3: Confirm proposal (1 write to routine_logs, 1 to audit_log)
    commit = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert commit["status"] == "COMMITTED"
    assert commit["database_writes"] == 1
    assert commit["transaction_id"] == tx_id
    assert commit["result_id"] is not None

    # Verify: Exactly 1 record in routine_logs, status is 'committed' in proposals
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status, result_id FROM proposals WHERE transaction_id = ?", (tx_id,))
        row = cursor.fetchone()
        assert row["status"] == "committed"
        assert row["result_id"] == commit["result_id"]

        cursor.execute("SELECT senior_id, routine_type, value FROM routine_logs WHERE id = ?", (commit["result_id"],))
        log_row = cursor.fetchone()
        assert log_row["senior_id"] == "margaret_01"
        assert log_row["routine_type"] == "hydration"
        assert log_row["value"] == "500ml water"
    finally:
        conn.close()

    # Step 4: Replay confirmation (0 additional writes, idempotent)
    replay = await verify_routine_state(confirm=True, transaction_id=tx_id)
    assert replay["status"] == "ALREADY_COMMITTED"
    assert replay["database_writes"] == 0

    # Invariant: Still exactly 1 record in routine_logs
    conn = storage.get_connection(isolated_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM routine_logs")
        assert cursor.fetchone()[0] == 1
    finally:
        conn.close()

