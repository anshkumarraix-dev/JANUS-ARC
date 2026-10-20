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
import httpx
from starlette.testclient import TestClient

# Ensure src directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from janus import storage
from janus.server import (
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
    """Test Tool 1: log_daily_routine inserts routine events."""
    res = await log_daily_routine(
        senior_id="margaret_01",
        routine_type="hydration",
        logged_by="senior_voice",
        notes="400ml water",
    )

    assert res["status"] == "success"
    assert res["senior_id"] == "margaret_01"
    assert res["routine_type"] == "hydration"
    assert "echo_show_card" in res
    assert res["echo_show_card"]["title"] == "Logged: Hydration"


@pytest.mark.asyncio
async def test_get_caregiver_summary_unit(isolated_db):
    """Test Tool 2: get_caregiver_summary returns completed and pending routines."""
    # Seed events
    await log_daily_routine("margaret_01", "meal", "senior_voice", "Morning oatmeal")
    await log_daily_routine("margaret_01", "vitamins", "caregiver_sarah", "Morning vitamins")

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
        senior_id="margaret_01",
        action_type="shift_handoff",
        payload=payload,
        confirm=False,
    )

    assert preview["status"] == "PROPOSAL_PREVIEW"
    assert preview["confirm_required"] is True
    assert preview["database_writes"] == 0
    assert "spoken_prompt" in preview

    # Verify that database has zero shift handoffs committed
    latest_handoff = storage.get_latest_handoff("margaret_01", db_path=isolated_db)
    assert latest_handoff is None

    # Step 2: Confirmed Commit (confirm=True)
    committed = await verify_routine_state(
        senior_id="margaret_01",
        action_type="shift_handoff",
        payload=payload,
        confirm=True,
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

    # Log the hydration
    await log_daily_routine("margaret_01", "hydration", "senior_voice", "2 glasses water")

    # When routine HAS been logged
    res_done = await flag_missed_routine(
        senior_id="margaret_01",
        routine_name="hydration",
        scheduled_time="14:00",
    )
    assert res_done["is_missed"] is False


def test_tool_discovery_streamable_http(isolated_db):
    """Test tool discovery (tools/list) over Streamable HTTP per MCP spec 2025-11-25 using httpx / TestClient."""
    app = get_app(host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        r_list = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_list.status_code == 200
        tools = [t["name"] for t in r_list.json()["result"]["tools"]]
        assert "log_daily_routine" in tools
        assert "get_caregiver_summary" in tools
        assert "verify_routine_state" in tools
        assert "flag_missed_routine" in tools


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
                            "handoff_notes": "All morning vitals normal; water reminder given",
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

        # Assert no writes occurred in the database
        assert storage.get_latest_handoff("margaret_01", db_path=isolated_db) is None


def test_tool_execution_latency_under_100ms(isolated_db):
    """Assert local tool execution latency completes in under 100 ms (round-trip < 500 ms)."""
    app = get_app(host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        latencies = []
        for i in range(15):
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
            latencies.append(elapsed_ms)
            assert r.status_code == 200

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
        print(f"\nLatency Benchmark (15 calls): Avg={avg_latency:.2f}ms, P95={p95_latency:.2f}ms, Max={max_latency:.2f}ms")
        assert max_latency < 100.0, f"Max execution latency exceeded 100ms: {max_latency:.2f}ms"
