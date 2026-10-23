#!/usr/bin/env python3
"""scripts/judge_check.py -- Standalone Security & Confirmation Gate Verification Script.

Proves the security, authentication, role isolation, and two-step confirmation gate
claims against a LIVE running JANUS-ARC FastMCP v2 server over Streamable HTTP.

Usage:
    python scripts/judge_check.py --url http://127.0.0.1:8000
    python scripts/judge_check.py --url https://your-public-tunnel.trycloudflare.com

Dependencies:
    httpx (standard library only for the rest)

Checks Verified (PASS/FAIL):
    2.a. No Authorization header, get_caregiver_summary for margaret_01 -> HTTP 401
    2.b. Garbage token -> HTTP 401
    2.c. Token "janus-demo-x" (wildcard-prefix) -> HTTP 401
    2.d. janus-demo-senior-margaret reading arthur_02 -> FORBIDDEN, no data returned
    2.e. senior token doing a shift handoff -> FORBIDDEN
    2.f. caregiver token reading its own senior -> OK
    2.g. log_daily_routine -> returns pending transaction_id and database_writes == 0
    2.h. verify_routine_state(confirm=True) with no transaction_id -> error, database_writes == 0
    2.i. confirm with real transaction_id -> COMMITTED; replay -> ALREADY_COMMITTED
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

import httpx


def extract_tool_result(resp_json: Any) -> Dict[str, Any]:
    """Extract tool structured result dictionary from JSON-RPC 2.0 response."""
    if not isinstance(resp_json, dict):
        return {}
    res = resp_json.get("result", {})
    if not isinstance(res, dict):
        return {}
    # 1. FastMCP structuredContent
    if "structuredContent" in res:
        sc = res["structuredContent"]
        if isinstance(sc, dict):
            if "result" in sc and isinstance(sc["result"], dict):
                return sc["result"]
            return sc
    # 2. FastMCP content text list
    if "content" in res and isinstance(res["content"], list) and len(res["content"]) > 0:
        c0 = res["content"][0]
        if isinstance(c0, dict) and "text" in c0:
            try:
                parsed = json.loads(c0["text"])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {"text": c0["text"]}
    return res


def send_mcp_call(
    client: httpx.Client,
    mcp_endpoint: str,
    tool_name: str,
    arguments: Dict[str, Any],
    token: Optional[str] = None,
    rpc_id: int = 1,
) -> httpx.Response:
    """Send an MCP JSON-RPC tools/call request to the /mcp endpoint."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    return client.post(mcp_endpoint, json=payload, headers=headers)


def run_checks(base_url: str, timeout: float = 10.0) -> int:
    """Execute all 9 security, role isolation, and confirmation gate checks."""
    base_url = base_url.rstrip("/")
    mcp_endpoint = f"{base_url}/mcp"
    health_endpoint = f"{base_url}/health"

    print("=" * 110)
    print(" JANUS-ARC -- SECURITY & CONFIRMATION GATE LIVE VERIFICATION")
    print(f" Target Server Base URL : {base_url}")
    print(f" FastMCP /mcp Endpoint  : {mcp_endpoint}")
    print("=" * 110)

    results: List[Tuple[str, str, str, str]] = []  # (code, desc, status, details)

    with httpx.Client(timeout=timeout) as client:
        # Pre-flight health check probe
        try:
            h_resp = client.get(health_endpoint)
            if h_resp.status_code == 200:
                h_data = h_resp.json()
                print(f" [OK] Server probe healthy: service={h_data.get('service')} version={h_data.get('version')} protocol={h_data.get('protocol')}")
            else:
                print(f" [WARN] /health returned HTTP {h_resp.status_code}")
        except Exception as e:
            print(f" [WARN] /health probe failed ({e}); continuing directly to /mcp checks...")

        print("\nRunning Verification Checks (2.a through 2.i):\n")

        # -------------------------------------------------------------------
        # Check 2.a: No Authorization header -> expect HTTP 401
        # -------------------------------------------------------------------
        try:
            resp_a = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="get_caregiver_summary",
                arguments={"senior_id": "margaret_01"},
                token=None,  # No Authorization header
                rpc_id=101,
            )
            passed = resp_a.status_code == 401
            detail = f"HTTP {resp_a.status_code} (Expected 401)"
            if passed:
                err_body = resp_a.json() if resp_a.headers.get("content-type", "").startswith("application/json") else {}
                detail = f"HTTP 401 UNAUTHORIZED ({err_body.get('error', 'UNAUTHORIZED')}: {err_body.get('message', '')})"
            status = "PASS" if passed else "FAIL"
            print(f" [{status}] Check 2.a: No Authorization header -> {detail}")
            results.append(("2.a", "No Authorization header -> expect HTTP 401", status, detail))
        except Exception as e:
            print(f" [FAIL] Check 2.a: Exception: {e}")
            results.append(("2.a", "No Authorization header -> expect HTTP 401", "FAIL", str(e)))

        # -------------------------------------------------------------------
        # Check 2.b: Garbage token -> expect HTTP 401
        # -------------------------------------------------------------------
        try:
            resp_b = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="get_caregiver_summary",
                arguments={"senior_id": "margaret_01"},
                token="garbage-invalid-token-xyz-12345",
                rpc_id=102,
            )
            passed = resp_b.status_code == 401
            detail = f"HTTP {resp_b.status_code} (Expected 401)"
            if passed:
                err_body = resp_b.json() if resp_b.headers.get("content-type", "").startswith("application/json") else {}
                detail = f"HTTP 401 UNAUTHORIZED ({err_body.get('error', 'UNAUTHORIZED')}: {err_body.get('message', '')})"
            status = "PASS" if passed else "FAIL"
            print(f" [{status}] Check 2.b: Garbage token -> {detail}")
            results.append(("2.b", "Garbage token -> expect HTTP 401", status, detail))
        except Exception as e:
            print(f" [FAIL] Check 2.b: Exception: {e}")
            results.append(("2.b", "Garbage token -> expect HTTP 401", "FAIL", str(e)))

        # -------------------------------------------------------------------
        # Check 2.c: Token 'janus-demo-x' (wildcard-prefix) -> expect HTTP 401
        # -------------------------------------------------------------------
        try:
            resp_c = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="get_caregiver_summary",
                arguments={"senior_id": "margaret_01"},
                token="janus-demo-x",
                rpc_id=103,
            )
            passed = resp_c.status_code == 401
            detail = f"HTTP {resp_c.status_code} (Expected 401)"
            if passed:
                err_body = resp_c.json() if resp_c.headers.get("content-type", "").startswith("application/json") else {}
                detail = f"HTTP 401 UNAUTHORIZED ({err_body.get('error', 'UNAUTHORIZED')}: {err_body.get('message', '')})"
            status = "PASS" if passed else "FAIL"
            print(f" [{status}] Check 2.c: Wildcard-prefix 'janus-demo-x' -> {detail}")
            results.append(("2.c", "Wildcard-prefix 'janus-demo-x' -> expect HTTP 401", status, detail))
        except Exception as e:
            print(f" [FAIL] Check 2.c: Exception: {e}")
            results.append(("2.c", "Wildcard-prefix 'janus-demo-x' -> expect HTTP 401", "FAIL", str(e)))

        # -------------------------------------------------------------------
        # Check 2.d: janus-demo-senior-margaret reading arthur_02 -> FORBIDDEN, no data returned
        # -------------------------------------------------------------------
        try:
            resp_d = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="get_caregiver_summary",
                arguments={"senior_id": "arthur_02"},
                token="janus-demo-senior-margaret",
                rpc_id=104,
            )
            if resp_d.status_code == 200:
                res_d = extract_tool_result(resp_d.json())
                err_code = res_d.get("error_code", "")
                is_err = res_d.get("status") == "error"
                has_forbidden = "FORBIDDEN" in err_code or "forbidden" in res_d.get("message", "").lower()
                # Ensure no sensitive clinical / summary data returned
                has_no_data = "events" not in res_d and "slots" not in res_d and "total_events" not in res_d
                passed = is_err and has_forbidden and has_no_data
                detail = f"error_code={err_code or 'None'}, writes={res_d.get('database_writes', 0)}, data_leaked={not has_no_data}"
            elif resp_d.status_code == 403:
                passed = True
                detail = "HTTP 403 FORBIDDEN"
            else:
                passed = False
                detail = f"Unexpected HTTP status {resp_d.status_code}"
            status = "PASS" if passed else "FAIL"
            print(f" [{status}] Check 2.d: Senior Margaret reading Arthur (cross-senior) -> {detail}")
            results.append(("2.d", "Senior reading cross-senior arthur_02 -> FORBIDDEN (no data)", status, detail))
        except Exception as e:
            print(f" [FAIL] Check 2.d: Exception: {e}")
            results.append(("2.d", "Senior reading cross-senior arthur_02 -> FORBIDDEN (no data)", "FAIL", str(e)))

        # -------------------------------------------------------------------
        # Check 2.e: senior token doing a shift handoff -> FORBIDDEN
        # -------------------------------------------------------------------
        try:
            resp_e = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="verify_routine_state",
                arguments={
                    "confirm": False,
                    "senior_id": "margaret_01",
                    "action_type": "shift_handoff",
                    "payload": {
                        "departing_caregiver": "Senior Margaret",
                        "incoming_caregiver": "Caregiver Sarah",
                        "handoff_notes": "Attempting shift handoff using senior role token",
                    },
                },
                token="janus-demo-senior-margaret",
                rpc_id=105,
            )
            if resp_e.status_code == 200:
                res_e = extract_tool_result(resp_e.json())
                err_code = res_e.get("error_code", "")
                is_err = res_e.get("status") == "error"
                has_forbidden = "FORBIDDEN" in err_code or "forbidden" in res_e.get("message", "").lower()
                zero_writes = res_e.get("database_writes", 0) == 0
                passed = is_err and has_forbidden and zero_writes
                detail = f"error_code={err_code}, writes={res_e.get('database_writes', 0)} ({res_e.get('message', '')})"
            elif resp_e.status_code == 403:
                passed = True
                detail = "HTTP 403 FORBIDDEN"
            else:
                passed = False
                detail = f"Unexpected HTTP status {resp_e.status_code}"
            status = "PASS" if passed else "FAIL"
            print(f" [{status}] Check 2.e: Senior token executing shift handoff -> {detail}")
            results.append(("2.e", "Senior token doing shift handoff -> FORBIDDEN", status, detail))
        except Exception as e:
            print(f" [FAIL] Check 2.e: Exception: {e}")
            results.append(("2.e", "Senior token doing shift handoff -> FORBIDDEN", "FAIL", str(e)))

        # -------------------------------------------------------------------
        # Check 2.f: caregiver token reading its own senior -> OK
        # -------------------------------------------------------------------
        try:
            resp_f = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="get_caregiver_summary",
                arguments={"senior_id": "margaret_01"},
                token="janus-demo-caregiver-sarah",
                rpc_id=106,
            )
            passed = False
            detail = f"HTTP {resp_f.status_code}"
            if resp_f.status_code == 200:
                res_f = extract_tool_result(resp_f.json())
                status_f = res_f.get("status", "")
                senior_id_f = res_f.get("senior_id", "")
                has_events = "events" in res_f or "slots" in res_f
                if status_f == "success" and senior_id_f == "margaret_01" and has_events:
                    passed = True
                    total_events = res_f.get("total_events", len(res_f.get("events", [])))
                    total_slots = len(res_f.get("slots", []))
                    detail = f"status=success, senior={senior_id_f}, events={total_events}, slots={total_slots}"
                else:
                    detail = f"status={status_f}, res={res_f}"
            status = "PASS" if passed else "FAIL"
            print(f" [{status}] Check 2.f: Caregiver Sarah reading Margaret -> {detail}")
            results.append(("2.f", "Caregiver token reading own senior -> OK", status, detail))
        except Exception as e:
            print(f" [FAIL] Check 2.f: Exception: {e}")
            results.append(("2.f", "Caregiver token reading own senior -> OK", "FAIL", str(e)))

        # -------------------------------------------------------------------
        # Check 2.g: log_daily_routine -> pending transaction_id and database_writes == 0
        # -------------------------------------------------------------------
        created_tx_id: Optional[str] = None
        try:
            resp_g = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="log_daily_routine",
                arguments={
                    "senior_id": "margaret_01",
                    "category": "hydration",
                    "details": "250ml water logged during judge_check audit",
                    "logged_by": "senior_voice",
                },
                token="janus-demo-senior-margaret",
                rpc_id=107,
            )
            passed = False
            detail = f"HTTP {resp_g.status_code}"
            if resp_g.status_code == 200:
                res_g = extract_tool_result(resp_g.json())
                status_g = res_g.get("status", "")
                writes_g = res_g.get("database_writes", -1)
                tx_id_g = res_g.get("transaction_id", "")
                if status_g == "pending_confirmation" and writes_g == 0 and tx_id_g.startswith("tx_"):
                    passed = True
                    created_tx_id = tx_id_g
                    detail = f"status={status_g}, tx_id={tx_id_g}, database_writes={writes_g}"
                else:
                    detail = f"status={status_g}, tx_id={tx_id_g}, database_writes={writes_g}"
            status = "PASS" if passed else "FAIL"
            print(f" [{status}] Check 2.g: log_daily_routine confirmation gate -> {detail}")
            results.append(("2.g", "log_daily_routine -> pending transaction_id, writes 0", status, detail))
        except Exception as e:
            print(f" [FAIL] Check 2.g: Exception: {e}")
            results.append(("2.g", "log_daily_routine -> pending transaction_id, writes 0", "FAIL", str(e)))

        # -------------------------------------------------------------------
        # Check 2.h: verify_routine_state(confirm=True) with no transaction_id -> error, 0 writes
        # -------------------------------------------------------------------
        try:
            resp_h = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="verify_routine_state",
                arguments={
                    "confirm": True,
                    # Deliberately omitting transaction_id
                },
                token="janus-demo-caregiver-sarah",
                rpc_id=108,
            )
            passed = False
            detail = f"HTTP {resp_h.status_code}"
            if resp_h.status_code == 200:
                res_h = extract_tool_result(resp_h.json())
                status_h = res_h.get("status", "")
                err_code_h = res_h.get("error_code", "")
                writes_h = res_h.get("database_writes", -1)
                if status_h == "error" and err_code_h == "MISSING_TRANSACTION_ID" and writes_h == 0:
                    passed = True
                    detail = f"status=error, error_code={err_code_h}, database_writes={writes_h}"
                else:
                    detail = f"status={status_h}, error_code={err_code_h}, database_writes={writes_h}"
            status = "PASS" if passed else "FAIL"
            print(f" [{status}] Check 2.h: verify_routine_state(confirm=True, no tx_id) -> {detail}")
            results.append(("2.h", "verify_routine_state(confirm=True, no tx) -> error, writes 0", status, detail))
        except Exception as e:
            print(f" [FAIL] Check 2.h: Exception: {e}")
            results.append(("2.h", "verify_routine_state(confirm=True, no tx) -> error, writes 0", "FAIL", str(e)))

        # -------------------------------------------------------------------
        # Check 2.i: confirm with real transaction_id -> COMMITTED; replay -> ALREADY_COMMITTED
        # -------------------------------------------------------------------
        try:
            if not created_tx_id:
                raise ValueError("Cannot test 2.i: No transaction_id obtained from Check 2.g.")

            # Step 1: Initial Commit
            resp_i1 = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="verify_routine_state",
                arguments={
                    "confirm": True,
                    "transaction_id": created_tx_id,
                },
                token="janus-demo-senior-margaret",
                rpc_id=109,
            )
            res_i1 = extract_tool_result(resp_i1.json())
            status_i1 = res_i1.get("status", "")
            writes_i1 = res_i1.get("database_writes", -1)
            first_commit_ok = (status_i1 == "COMMITTED" and writes_i1 == 1)

            # Step 2: Replay Commit (Idempotency)
            resp_i2 = send_mcp_call(
                client=client,
                mcp_endpoint=mcp_endpoint,
                tool_name="verify_routine_state",
                arguments={
                    "confirm": True,
                    "transaction_id": created_tx_id,
                },
                token="janus-demo-senior-margaret",
                rpc_id=110,
            )
            res_i2 = extract_tool_result(resp_i2.json())
            status_i2 = res_i2.get("status", "")
            writes_i2 = res_i2.get("database_writes", -1)
            replay_ok = (status_i2 == "ALREADY_COMMITTED" and writes_i2 == 0)

            passed = first_commit_ok and replay_ok
            detail = (
                f"Commit: status={status_i1}, writes={writes_i1} | "
                f"Replay: status={status_i2}, writes={writes_i2}"
            )
            status = "PASS" if passed else "FAIL"
            print(f" [{status}] Check 2.i: Confirm real tx ({created_tx_id}) -> {detail}")
            results.append(("2.i", "confirm real tx -> COMMITTED; replay -> ALREADY_COMMITTED", status, detail))
        except Exception as e:
            print(f" [FAIL] Check 2.i: Exception: {e}")
            results.append(("2.i", "confirm real tx -> COMMITTED; replay -> ALREADY_COMMITTED", "FAIL", str(e)))

    # -----------------------------------------------------------------------
    # Summary Table Output
    # -----------------------------------------------------------------------
    print("\n" + "=" * 115)
    print(" VERIFICATION SUMMARY TABLE")
    print("=" * 115)
    print(f"| {'#':<3} | {'Check Description':<52} | {'Status':<6} | {'Observed Evidence':<44} |")
    print("|" + "-" * 5 + "|" + "-" * 54 + "|" + "-" * 8 + "|" + "-" * 46 + "|")
    for code, desc, st, det in results:
        det_truncated = (det[:42] + "..") if len(det) > 44 else det
        print(f"| {code:<3} | {desc:<52} | {st:<6} | {det_truncated:<44} |")
    print("=" * 115)

    passed_count = sum(1 for _, _, st, _ in results if st == "PASS")
    total_count = len(results)
    failed_count = total_count - passed_count

    print(f"\nFinal Verdict: {passed_count}/{total_count} checks passed ({failed_count} failed).")
    if failed_count == 0:
        print("[SUCCESS] All security, authorization, and confirmation gate invariants verified!\n")
        return 0
    else:
        print(f"[ERROR] {failed_count} check(s) failed. See logs above.\n")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="JANUS-ARC -- Standalone Security & Gate Claim Verification Script"
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://127.0.0.1:8000",
        help="Base URL of running Janus FastMCP server (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP request timeout in seconds (default: 10.0)",
    )
    args = parser.parse_args()

    exit_code = run_checks(base_url=args.url, timeout=args.timeout)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
