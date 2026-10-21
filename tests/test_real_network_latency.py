"""Real-network latency and outputSchema contract test suite.

Verifies:
1. Contract tests per tool: all 4 FastMCP tools publish valid outputSchema and their
   structuredContent responses strictly conform to their published outputSchema (using jsonschema).
2. Real-network latency benchmark: runs uvicorn in an independent OS subprocess on a free port,
   executes 50 real HTTP POST calls per tool via httpx.Client, calculates p50/p95/max,
   asserts p95 < 100ms per call, and prints a formatted evaluation table.
NOTE: Does NOT use Starlette TestClient for the latency benchmark.
"""

from __future__ import annotations

import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Tuple

import httpx
import jsonschema
import pytest


def get_free_port() -> int:
    """Find and return an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_mcp_server():
    """Start uvicorn in a real background subprocess on a free port and yield base URL."""
    port = get_free_port()
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "real_network_test.db")

    env = os.environ.copy()
    env["JANUS_PORT"] = str(port)
    env["JANUS_HOST"] = "127.0.0.1"
    env["JANUS_DB_PATH"] = db_path
    env["JANUS_LOG_LEVEL"] = "warning"
    # Ensure src directory is in PYTHONPATH for the subprocess
    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [sys.executable, "-m", "janus.server"]
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15.0
    ready = False

    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        while time.time() < deadline:
            try:
                r = client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                    headers={"MCP-Protocol-Version": "2025-11-25"},
                )
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.1)

    if not ready:
        proc.terminate()
        proc.wait(timeout=5)
        raise RuntimeError(f"Failed to start uvicorn subprocess on {base_url} within 15s.")

    yield base_url

    # Cleanup subprocess
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)

    # Cleanup temp db
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Test 1: Contract tests per tool including outputSchema conformance
# ---------------------------------------------------------------------------
def test_contract_output_schema_conformance_all_tools(live_mcp_server: str):
    """Verify each tool publishes an outputSchema and its structuredContent response conforms to it."""
    with httpx.Client(base_url=live_mcp_server, timeout=10.0) as client:
        # Step 1: Discover tools and outputSchemas
        r_list = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}},
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_list.status_code == 200
        tools = {t["name"]: t for t in r_list.json()["result"]["tools"]}

        for name in ["log_daily_routine", "get_caregiver_summary", "verify_routine_state", "flag_missed_routine"]:
            assert name in tools, f"Missing tool: {name}"
            assert tools[name].get("outputSchema"), f"Tool {name} is missing outputSchema"

        # 1. log_daily_routine contract
        r_log = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "log_daily_routine",
                    "arguments": {
                        "senior_id": "margaret_01",
                        "category": "hydration",
                        "details": "250ml water",
                        "logged_by": "senior_voice",
                    },
                },
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_log.status_code == 200
        sc_log = r_log.json()["result"]["structuredContent"]
        jsonschema.validate(instance=sc_log, schema=tools["log_daily_routine"]["outputSchema"])
        assert sc_log["status"] == "pending_confirmation"
        assert sc_log["database_writes"] == 0
        tx_id = sc_log["transaction_id"]

        # 2. get_caregiver_summary contract
        r_summary = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "get_caregiver_summary",
                    "arguments": {"senior_id": "margaret_01"},
                },
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_summary.status_code == 200
        sc_summary = r_summary.json()["result"]["structuredContent"]
        jsonschema.validate(instance=sc_summary, schema=tools["get_caregiver_summary"]["outputSchema"])
        assert "events" in sc_summary
        assert "slots" in sc_summary
        assert "visual_card" in sc_summary

        # 3a. verify_routine_state (preview) contract
        r_verify_prev = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {
                    "name": "verify_routine_state",
                    "arguments": {
                        "confirm": False,
                        "senior_id": "margaret_01",
                        "action_type": "shift_handoff",
                        "payload": {
                            "departing_caregiver": "David",
                            "incoming_caregiver": "Sarah",
                            "handoff_notes": "All morning routines completed on schedule",
                        },
                    },
                },
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_verify_prev.status_code == 200
        sc_verify_prev = r_verify_prev.json()["result"]["structuredContent"]
        jsonschema.validate(instance=sc_verify_prev, schema=tools["verify_routine_state"]["outputSchema"])
        verify_prev_data = sc_verify_prev.get("result", sc_verify_prev)
        assert verify_prev_data["status"] == "PROPOSAL_PREVIEW"
        assert verify_prev_data["database_writes"] == 0

        # 3b. verify_routine_state (commit) contract
        r_verify_commit = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 14,
                "method": "tools/call",
                "params": {
                    "name": "verify_routine_state",
                    "arguments": {
                        "confirm": True,
                        "transaction_id": tx_id,
                    },
                },
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_verify_commit.status_code == 200
        sc_verify_commit = r_verify_commit.json()["result"]["structuredContent"]
        jsonschema.validate(instance=sc_verify_commit, schema=tools["verify_routine_state"]["outputSchema"])
        verify_commit_data = sc_verify_commit.get("result", sc_verify_commit)
        assert verify_commit_data["status"] == "COMMITTED"
        assert verify_commit_data["database_writes"] == 1

        # 4. flag_missed_routine contract
        r_missed = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {
                    "name": "flag_missed_routine",
                    "arguments": {
                        "senior_id": "margaret_01",
                        "threshold_hours": 1,
                    },
                },
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        assert r_missed.status_code == 200
        sc_missed = r_missed.json()["result"]["structuredContent"]
        jsonschema.validate(instance=sc_missed, schema=tools["flag_missed_routine"]["outputSchema"])
        assert "status" in sc_missed
        assert "alert_payload" in sc_missed


# ---------------------------------------------------------------------------
# Test 2: Real-network latency test (50 calls per tool via httpx, assert p95 < 100ms)
# ---------------------------------------------------------------------------
def test_real_network_latency_benchmark(live_mcp_server: str):
    """Execute 50 real-network HTTP calls per tool via httpx, report stats, and assert p95 < 100ms."""
    call_configs = [
        (
            "log_daily_routine",
            {
                "name": "log_daily_routine",
                "arguments": {
                    "senior_id": "margaret_01",
                    "category": "hydration",
                    "details": "Water sip",
                },
            },
        ),
        (
            "get_caregiver_summary",
            {
                "name": "get_caregiver_summary",
                "arguments": {
                    "senior_id": "margaret_01",
                },
            },
        ),
        (
            "verify_routine_state",
            {
                "name": "verify_routine_state",
                "arguments": {
                    "confirm": False,
                    "senior_id": "margaret_01",
                    "action_type": "shift_handoff",
                    "payload": {
                        "departing_caregiver": "David",
                        "incoming_caregiver": "Sarah",
                        "handoff_notes": "Morning routines completed on schedule",
                    },
                },
            },
        ),
        (
            "flag_missed_routine",
            {
                "name": "flag_missed_routine",
                "arguments": {
                    "senior_id": "margaret_01",
                    "threshold_hours": 1,
                },
            },
        ),
    ]

    benchmark_results: List[Dict[str, Any]] = []

    with httpx.Client(base_url=live_mcp_server, timeout=10.0) as client:
        # Warmup call
        client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )

        for tool_name, params in call_configs:
            # Per-tool warmup to initialize Pydantic models and DB schema
            for _ in range(2):
                client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 999, "method": "tools/call", "params": params},
                    headers={"MCP-Protocol-Version": "2025-11-25", "Authorization": "Bearer janus-demo-token-alexa-plus-2026"},
                )

            durations: List[float] = []

            for i in range(50):
                t0 = time.perf_counter()
                r = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1000 + i,
                        "method": "tools/call",
                        "params": params,
                    },
                    headers={
                        "MCP-Protocol-Version": "2025-11-25",
                        "Authorization": "Bearer janus-demo-token-alexa-plus-2026",
                    },
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                assert r.status_code == 200, f"{tool_name} failed on call {i}: {r.text}"
                durations.append(elapsed_ms)

            # Calculate statistics
            p50 = statistics.median(durations)
            sorted_durations = sorted(durations)
            # p95 on 50 samples is at index 47 (0-indexed: int(50 * 0.95) = 47)
            p95 = sorted_durations[int(len(sorted_durations) * 0.95)]
            max_lat = max(durations)
            avg_lat = sum(durations) / len(durations)

            benchmark_results.append({
                "tool": tool_name,
                "calls": len(durations),
                "avg": avg_lat,
                "p50": p50,
                "p95": p95,
                "max": max_lat,
            })

            # Strict SLA assertion: p95 must be under 100ms per call
            assert p95 < 100.0, f"Tool '{tool_name}' p95 latency {p95:.2f}ms exceeded 100ms limit"

    # Print formatted markdown table
    print("\n" + "=" * 78)
    print("REAL-NETWORK FAST-MCP LATENCY BENCHMARK (uvicorn subprocess over loopback HTTP)")
    print("=" * 78)
    print(f"{'Tool':<25} | {'Calls':>5} | {'Avg (ms)':>9} | {'p50 (ms)':>9} | {'p95 (ms)':>9} | {'Max (ms)':>9} | {'SLA (<100ms)':>12}")
    print("-" * 25 + "-+-" + "-" * 5 + "-+-" + "-" * 9 + "-+-" + "-" * 9 + "-+-" + "-" * 9 + "-+-" + "-" * 9 + "-+-" + "-" * 12)

    for res in benchmark_results:
        sla_pass = "PASS" if res["p95"] < 100.0 else "FAIL"
        print(
            f"{res['tool']:<25} | {res['calls']:>5} | {res['avg']:>8.2f}ms | {res['p50']:>8.2f}ms | {res['p95']:>8.2f}ms | {res['max']:>8.2f}ms | {sla_pass:>12}"
        )
    print("=" * 78 + "\n")
