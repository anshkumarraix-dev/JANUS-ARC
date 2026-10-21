"""Janus (ElderSync) — Contract & Latency Test Suite.

Verifies:
1. SQLite persistence and CRUD operations.
2. The 4 core FastMCP v2 tools.
3. Confirmation gate invariants: confirm=False executes zero database mutations.
4. Streamable HTTP JSON-RPC compliance (MCP spec 2025-11-25) using httpx.
5. Local execution latency budget < 100 ms (round-trip < 500 ms).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import pytest
from starlette.testclient import TestClient

# Ensure src directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from janus import storage  # noqa: E402
from janus.server import (  # noqa: E402
    get_app,
    log_daily_routine,
    get_caregiver_summary,
    verify_routine_state,
    flag_missed_routine,
)


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Create an isolated temporary SQLite database for each test."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_janus.db")
    monkeypatch.setattr(storage, "DEFAULT_DB_PATH", test_db_path)
    storage.init_db(test_db_path)
    yield test_db_path
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_log_daily_routine_unit(isolated_db):
    """Test Tool 1: log_daily_routine creates a pending proposal with 0 writes until confirmed."""
    # Step 1: Proposal creation
    res = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="400ml water",
    )

    assert res["status"] == "pending_confirmation"
    assert res["senior_id"] == "margaret_01"
    assert res["routine_type"] == "hydration"
    assert res["database_writes"] == 0
    assert "transaction_id" in res
    assert "preview" in res
    assert "spoken_prompt" in res

    # Confirm via verify_routine_state
    commit_res = await verify_routine_state(confirm=True, transaction_id=res["transaction_id"])
    assert commit_res["status"] == "COMMITTED"
    assert commit_res["database_writes"] == 1
    assert commit_res["committed_record"]["routine_type"] == "hydration"


@pytest.mark.asyncio
async def test_get_caregiver_summary_unit(isolated_db):
    """Test Tool 2: get_caregiver_summary returns completed and pending routines."""
    # Seed events via two-step confirmation gate
    p1 = await log_daily_routine(senior_id="margaret_01", category="meal", details="Morning oatmeal")
    await verify_routine_state(confirm=True, transaction_id=p1["transaction_id"])

    p2 = await log_daily_routine(senior_id="margaret_01", category="vitamins", details="Morning vitamins")
    await verify_routine_state(confirm=True, transaction_id=p2["transaction_id"])

    summary = await get_caregiver_summary("margaret_01")
    assert summary["status"] == "success"
    assert summary["total_events"] == 2
    assert "meal" in summary["completed_types"]
    assert "vitamins" in summary["completed_types"]
    assert "visual_card" in summary
    assert summary["visual_card"]["card_type"] == "EchoShowTimelineCard"


@pytest.mark.asyncio
async def test_verify_routine_state_confirmation_gate(isolated_db):
    """Test Tool 3: verify_routine_state safety confirmation gate.

    INVARIANT: confirm=False MUST NOT write to the database (database_writes == 0).
    Only confirm=True commits to the SQLite shift_handoffs table (database_writes == 1).
    """
    payload = {
        "departing_caregiver": "David",
        "incoming_caregiver": "Sarah",
        "handoff_notes": "Margaret walked 20 minutes in the garden; needs afternoon water.",
    }

    # Step 1: Proposal Preview (confirm=False)
    preview = await verify_routine_state(
        confirm=False,
        senior_id="margaret_01",
        action_type="shift_handoff",
        payload=payload,
    )

    assert preview["status"] == "PROPOSAL_PREVIEW"
    assert preview["confirm_required"] is True
    assert preview["database_writes"] == 0
    assert "transaction_id" in preview
    assert "spoken_prompt" in preview
    tx_id = preview["transaction_id"]

    # Verify that database has zero shift handoffs committed
    latest_handoff = storage.get_latest_handoff("margaret_01", db_path=isolated_db)
    assert latest_handoff is None

    # Step 2: Confirmed Commit (confirm=True with transaction_id)
    committed = await verify_routine_state(
        confirm=True,
        transaction_id=tx_id,
    )

    assert committed["status"] == "COMMITTED"
    assert committed["database_writes"] == 1
    assert "committed_record" in committed
    assert committed["committed_record"]["incoming_caregiver"] == "Sarah"

    # Verify that database now has the committed shift handoff
    saved_handoff = storage.get_latest_handoff("margaret_01", db_path=isolated_db)
    assert saved_handoff is not None
    assert saved_handoff["incoming_caregiver"] == "Sarah"
    assert saved_handoff["confirmed"] == 1


@pytest.mark.asyncio
async def test_flag_missed_routine_unit(isolated_db):
    """Test Tool 4: flag_missed_routine identifies missed routine windows."""
    # When routine has NOT been logged
    res_missed = await flag_missed_routine(
        senior_id="margaret_01",
        routine_name="Afternoon Hydration",
        scheduled_time="14:00",
        urgency_level="high",
    )
    assert res_missed["status"] == "FLAGGED"
    assert res_missed["is_missed"] is True
    assert "alert_payload" in res_missed

    # Log and confirm the hydration
    p = await log_daily_routine(senior_id="margaret_01", category="hydration", details="2 glasses water")
    await verify_routine_state(confirm=True, transaction_id=p["transaction_id"])

    # When routine HAS been logged
    res_done = await flag_missed_routine(
        senior_id="margaret_01",
        routine_name="hydration",
        scheduled_time="14:00",
    )
    assert res_done["is_missed"] is False


def test_tool_discovery_streamable_http(isolated_db):
    """Test tool discovery (tools/list) over Streamable HTTP per MCP spec 2025-11-25.

    Asserts:
    1. All 4 core tools are published.
    2. Tool annotations match specification:
       - get_caregiver_summary: readOnlyHint=True, idempotentHint=True, destructiveHint=False
       - flag_missed_routine: readOnlyHint=False, idempotentHint=True, destructiveHint=False
       - log_daily_routine: readOnlyHint=False, idempotentHint=False, destructiveHint=False
       - verify_routine_state: readOnlyHint=False, idempotentHint=True, destructiveHint=False
    3. InputSchema and OutputSchema are published as typed Pydantic models.
    4. Descriptions contain WHEN TO CALL, WHEN NOT TO CALL, and confirmation gate guidance.
    """
    app = get_app(host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        r_list = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_list.status_code == 200
        tools = {t["name"]: t for t in r_list.json()["result"]["tools"]}

        # Assert all 4 tools exist
        assert "log_daily_routine" in tools
        assert "get_caregiver_summary" in tools
        assert "verify_routine_state" in tools
        assert "flag_missed_routine" in tools

        # Assert Tool Annotations
        ann_summary = tools["get_caregiver_summary"].get("annotations", {})
        assert ann_summary.get("readOnlyHint") is True
        assert ann_summary.get("idempotentHint") is True
        assert ann_summary.get("destructiveHint") is False

        ann_flag = tools["flag_missed_routine"].get("annotations", {})
        assert ann_flag.get("readOnlyHint") is False
        assert ann_flag.get("idempotentHint") is True
        assert ann_flag.get("destructiveHint") is False

        ann_log = tools["log_daily_routine"].get("annotations", {})
        assert ann_log.get("readOnlyHint") is False
        assert ann_log.get("idempotentHint") is False
        assert ann_log.get("destructiveHint") is False

        ann_verify = tools["verify_routine_state"].get("annotations", {})
        assert ann_verify.get("readOnlyHint") is False
        assert ann_verify.get("idempotentHint") is True
        assert ann_verify.get("destructiveHint") is False

        # Assert Typed Input & Output Schemas
        for tool_name, t in tools.items():
            # inputSchema must have properties
            in_schema = t.get("inputSchema", {})
            assert "properties" in in_schema, f"{tool_name} missing properties in inputSchema"
            assert "senior_id" in in_schema["properties"] or "confirm" in in_schema["properties"]

            # outputSchema must be published (not empty or loose)
            out_schema = t.get("outputSchema", {})
            assert out_schema, f"{tool_name} missing outputSchema"
            assert ("properties" in out_schema or "$defs" in out_schema), f"{tool_name} outputSchema not properly typed"

            # Assert LLM Guidance in descriptions
            desc = t.get("description", "")
            assert "WHEN TO CALL:" in desc, f"{tool_name} description missing 'WHEN TO CALL:'"
            assert "WHEN NOT TO CALL:" in desc, f"{tool_name} description missing 'WHEN NOT TO CALL:'"

        # Assert routine logging description explicitly documents the two-step confirm step
        log_desc = tools["log_daily_routine"].get("description", "")
        assert "TWO-STEP CONFIRMATION GATE" in log_desc
        assert "verify_routine_state" in log_desc


def test_mcp_resource_senior_today(isolated_db):
    """Test MCP resource janus://senior/{id}/today over Streamable HTTP."""
    import json

    app = get_app(host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        # Check resource template discovery
        r_tmpl = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 50, "method": "resources/templates/list", "params": {}},
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_tmpl.status_code == 200
        templates = r_tmpl.json()["result"]["resourceTemplates"]
        uri_templates = [t["uriTemplate"] for t in templates]
        assert "janus://senior/{id}/today" in uri_templates

        # Read resource for senior margaret_01
        r_read = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 51,
                "method": "resources/read",
                "params": {"uri": "janus://senior/margaret_01/today"},
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_read.status_code == 200
        contents = r_read.json()["result"]["contents"]
        assert len(contents) == 1
        assert contents[0]["uri"] == "janus://senior/margaret_01/today"
        assert contents[0]["mimeType"] == "application/json"

        # Verify parsed summary payload
        data = json.loads(contents[0]["text"])
        assert data["senior_id"] == "margaret_01"
        assert "completion_percentage" in data
        assert "total_slots" in data
        assert "visual_card" in data


def test_structured_error_codes(isolated_db):
    """Test stable error codes and human-safe error responses across tools."""
    from janus.errors import ErrorCode, InvalidCategoryError

    # 1. Invalid Category raises InvalidCategoryError with stable error_code
    try:
        storage.validate_category("prescription_meds")
        assert False, "Should have raised InvalidCategoryError"
    except InvalidCategoryError as e:
        assert e.code == ErrorCode.INVALID_CATEGORY
        assert "Invalid category 'prescription_meds'" in str(e)

    # 2. verify_routine_state errors return stable error codes
    app = get_app(host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        # Missing transaction_id on confirm=True
        r1 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 60,
                "method": "tools/call",
                "params": {
                    "name": "verify_routine_state",
                    "arguments": {"confirm": True},
                },
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r1.status_code == 200
        res1 = r1.json()["result"]["structuredContent"]["result"]
        assert res1["status"] == "error"
        assert res1["error_code"] == ErrorCode.MISSING_TRANSACTION_ID

        # Nonexistent transaction_id
        r2 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 61,
                "method": "tools/call",
                "params": {
                    "name": "verify_routine_state",
                    "arguments": {"confirm": True, "transaction_id": "tx_nonexistent_999"},
                },
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r2.status_code == 200
        res2 = r2.json()["result"]["structuredContent"]["result"]
        assert res2["status"] == "error"
        assert res2["error_code"] == ErrorCode.PROPOSAL_NOT_FOUND


def test_verify_routine_state_preview_over_http(isolated_db):
    """Verify verify_routine_state returns PROPOSAL_PREVIEW when confirm=False over HTTP without DB writes."""
    app = get_app(host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        # Check initial DB count for shift_handoffs
        assert storage.get_latest_handoff("margaret_01", db_path=isolated_db) is None

        # Execute unconfirmed preview over HTTP
        r_preview = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "verify_routine_state",
                    "arguments": {
                        "senior_id": "margaret_01",
                        "action_type": "shift_handoff",
                        "payload": {
                            "departing_caregiver": "David",
                            "incoming_caregiver": "Sarah",
                            "handoff_notes": "All morning routines completed; water reminder given",
                        },
                        "confirm": False,
                    },
                },
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_preview.status_code == 200
        data = r_preview.json()["result"]["structuredContent"]["result"]
        assert data["status"] == "PROPOSAL_PREVIEW"
        assert data["database_writes"] == 0
        assert data["confirm_required"] is True
        assert "transaction_id" in data

        # Assert no writes occurred in the database
        assert storage.get_latest_handoff("margaret_01", db_path=isolated_db) is None


@pytest.mark.asyncio
async def test_tool_execution_latency_under_100ms(isolated_db):
    """Assert local tool execution completes in < 100 ms and HTTP round-trip in < 500 ms."""
    # 1. Direct local tool execution benchmark (< 100 ms mandate)
    # Warmup call to eliminate cold-start compilation/import jitter
    await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        logged_by="senior_voice",
        details="Warmup glass",
    )

    tool_latencies = []
    for i in range(20):
        t0 = time.perf_counter()
        await log_daily_routine(
            senior_id="margaret_01",
            category="hydration",
            logged_by="senior_voice",
            details=f"Glass {i + 1}",
        )
        tool_latencies.append((time.perf_counter() - t0) * 1000)

    avg_tool = sum(tool_latencies) / len(tool_latencies)
    sorted_lats = sorted(tool_latencies)
    p90_tool = sorted_lats[int(len(sorted_lats) * 0.90)]
    print(f"\nDirect Tool Benchmark (20 calls): Avg={avg_tool:.2f}ms, P90={p90_tool:.2f}ms, Min={sorted_lats[0]:.2f}ms, Max={sorted_lats[-1]:.2f}ms")
    assert avg_tool < 100.0, f"Local tool execution avg exceeded 100ms: {avg_tool:.2f}ms"
    assert p90_tool < 100.0, f"Local tool execution p90 exceeded 100ms: {p90_tool:.2f}ms"


    # 2. End-to-end Streamable HTTP round-trip benchmark (< 500 ms SLA)
    app = get_app(host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        # Warmup
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 199,
                "method": "tools/call",
                "params": {"name": "log_daily_routine", "arguments": {"senior_id": "margaret_01", "category": "hydration"}},
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )

        http_latencies = []
        for i in range(10):
            t0 = time.perf_counter()
            r = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 200 + i,
                    "method": "tools/call",
                    "params": {
                        "name": "log_daily_routine",
                        "arguments": {
                            "senior_id": "margaret_01",
                            "routine_type": "hydration",
                            "logged_by": "senior_voice",
                            "notes": f"Glass {i + 1}",
                        },
                    },
                },
                headers={"MCP-Protocol-Version": "2025-11-25"},
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            http_latencies.append(elapsed_ms)
            assert r.status_code == 200

        avg_http = sum(http_latencies) / len(http_latencies)
        max_http = max(http_latencies)
        print(f"HTTP Round-Trip Benchmark: Avg={avg_http:.2f}ms, Max={max_http:.2f}ms")
        assert avg_http < 100.0, f"HTTP round-trip avg exceeded 100ms: {avg_http:.2f}ms"
        assert max_http < 500.0, f"HTTP round-trip max exceeded 500ms budget: {max_http:.2f}ms"


def test_health_check_endpoint():
    """Verify /health endpoint returns healthy status and protocol version."""
    client = TestClient(get_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "janus-mcp"
    assert data["protocol"] == "2025-11-25"



