"""APL schema and shape contract test suite for Echo Show 8 landscape (APL 2024.3).

Verifies:
1. Valid APL 2024.3 JSON documents with mainTemplate and payload parameters.
2. Arm's length glanceable constraints: max 3 visual elements, 24pt+ font size across all text elements.
3. Complete resolution of all ${payload.XYZ} data-binding expressions against matching datasources.
4. Tools publish genuine APL and display fallback objects in structuredContent.
NOTE: Validates static schema and dynamic bindings. Does not claim physical device testing.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, List, Set

import pytest
from starlette.testclient import TestClient

from janus.apl import (
    APL_SPEC_VERSION,
    save_apl_documents,
)
from janus.server import (
    get_app,
    log_daily_routine,
    get_caregiver_summary,
    verify_routine_state,
    flag_missed_routine,
)


DOCS_APL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs", "apl"))

CARD_NAMES = [
    "routine_preview",
    "caregiver_summary",
    "handoff_confirm",
    "missed_routine",
]


def _extract_payload_bindings(obj: Any) -> Set[str]:
    """Recursively extract all property names bound via ${payload.PROPERTY}."""
    bindings = set()
    pattern = re.compile(r"\$\{payload\.([a-zA-Z0-9_]+)\}")

    if isinstance(obj, str):
        for match in pattern.finditer(obj):
            bindings.add(match.group(1))
    elif isinstance(obj, dict):
        for v in obj.values():
            bindings.update(_extract_payload_bindings(v))
    elif isinstance(obj, list):
        for item in obj:
            bindings.update(_extract_payload_bindings(item))

    return bindings


def _extract_font_sizes(obj: Any) -> List[int]:
    """Recursively extract all numeric fontSize values (in dp or pt)."""
    font_sizes = []
    if isinstance(obj, dict):
        if "fontSize" in obj:
            val = str(obj["fontSize"]).replace("dp", "").replace("pt", "").strip()
            if val.isdigit():
                font_sizes.append(int(val))
        for v in obj.values():
            font_sizes.extend(_extract_font_sizes(v))
    elif isinstance(obj, list):
        for item in obj:
            font_sizes.extend(_extract_font_sizes(item))
    return font_sizes


def test_apl_documents_exist_and_are_valid_json():
    """Assert all 4 APL documents and matching datasources exist on disk as valid JSON."""
    save_apl_documents(DOCS_APL_DIR)

    for name in CARD_NAMES:
        doc_path = os.path.join(DOCS_APL_DIR, f"{name}.json")
        data_path = os.path.join(DOCS_APL_DIR, f"{name}_datasource.json")

        assert os.path.exists(doc_path), f"Missing APL document file: {doc_path}"
        assert os.path.exists(data_path), f"Missing APL datasource file: {data_path}"

        # Valid JSON parse
        with open(doc_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        with open(data_path, "r", encoding="utf-8") as f:
            datasource = json.load(f)

        assert isinstance(doc, dict), f"{name}.json must be a JSON object"
        assert isinstance(datasource, dict), f"{name}_datasource.json must be a JSON object"


def test_apl_document_schema_and_version():
    """Assert top-level APL properties: type, version 2024.3, theme, and mainTemplate."""
    for name in CARD_NAMES:
        doc_path = os.path.join(DOCS_APL_DIR, f"{name}.json")
        with open(doc_path, "r", encoding="utf-8") as f:
            doc = json.load(f)

        assert doc.get("type") == "APL", f"{name} type must be 'APL'"
        assert doc.get("version") == APL_SPEC_VERSION, f"{name} version must be '{APL_SPEC_VERSION}'"
        assert doc.get("theme") == "dark", f"{name} theme must be 'dark' for high-contrast arm's-length viewing"

        # mainTemplate assertion
        assert "mainTemplate" in doc, f"{name} missing mainTemplate"
        main_template = doc["mainTemplate"]
        assert "parameters" in main_template, f"{name} mainTemplate missing parameters"
        assert "payload" in main_template["parameters"], f"{name} mainTemplate parameters must include 'payload'"
        assert ("item" in main_template or "items" in main_template), f"{name} mainTemplate missing item/items"


def test_apl_visual_elements_and_glanceable_typography():
    """Assert Echo Show 8 constraints: max 3 visual elements, 24pt+ text size across all text components."""
    for name in CARD_NAMES:
        doc_path = os.path.join(DOCS_APL_DIR, f"{name}.json")
        with open(doc_path, "r", encoding="utf-8") as f:
            doc = json.load(f)

        root_item = doc["mainTemplate"]["item"]
        assert root_item.get("type") == "Container", f"{name} root item must be Container"
        items = root_item.get("items", [])

        # Rule: max 3 visual elements per card (header, hero, footer)
        assert len(items) <= 3, f"{name} has {len(items)} top-level visual elements; maximum is 3 for senior glanceability"

        # Rule: All font sizes must be >= 24dp (arm's length 24pt+ text)
        font_sizes = _extract_font_sizes(doc)
        assert len(font_sizes) > 0, f"{name} must contain text elements with font sizes"
        for fs in font_sizes:
            assert fs >= 24, f"{name} contains fontSize '{fs}dp', which is below the 24pt+ senior readability minimum"


def test_apl_datasource_bindings_resolve():
    """Assert every ${payload.PROPERTY} expression in each APL document resolves to a valid key in its datasource."""
    for name in CARD_NAMES:
        doc_path = os.path.join(DOCS_APL_DIR, f"{name}.json")
        data_path = os.path.join(DOCS_APL_DIR, f"{name}_datasource.json")

        with open(doc_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        with open(data_path, "r", encoding="utf-8") as f:
            datasource = json.load(f)

        bound_properties = _extract_payload_bindings(doc)
        assert len(bound_properties) > 0, f"{name} should use data-binding parameters"

        payload = datasource.get("payload", {})
        for prop in bound_properties:
            assert prop in payload, f"APL document '{name}.json' binds to '${{payload.{prop}}}', but '{prop}' is missing from datasource payload!"


@pytest.mark.asyncio
async def test_tools_return_genuine_apl_and_display_fallback(isolated_db):
    """Assert all 4 core tools return genuine APL document+datasources and display fallback in Python and over HTTP."""
    # 1. log_daily_routine
    prop_res = await log_daily_routine(
        senior_id="margaret_01",
        category="hydration",
        details="500ml water",
    )
    assert prop_res.apl is not None
    assert prop_res.apl["document"]["type"] == "APL"
    assert prop_res.apl["document"]["version"] == "2024.3"
    assert "payload" in prop_res.apl["datasources"]
    assert prop_res.apl["datasources"]["payload"]["categoryTitle"] == "💧 Hydration"
    assert prop_res.display is not None
    assert "Proposed: Hydration" in prop_res.display["title"]
    assert len(prop_res.display["lines"]) >= 2
    tx_id = prop_res.transaction_id

    # 2. get_caregiver_summary
    summary_res = await get_caregiver_summary(senior_id="margaret_01")
    assert summary_res.apl is not None
    assert summary_res.apl["document"]["type"] == "APL"
    assert summary_res.apl["document"]["version"] == "2024.3"
    assert "payload" in summary_res.apl["datasources"]
    assert "Timeline" in summary_res.apl["datasources"]["payload"]["header"]
    assert summary_res.display is not None
    assert len(summary_res.display["lines"]) >= 2

    # 3. verify_routine_state (confirm=False preview)
    handoff_preview = await verify_routine_state(
        senior_id="margaret_01",
        action_type="shift_handoff",
        payload={
            "departing_caregiver": "David",
            "incoming_caregiver": "Sarah",
            "handoff_notes": "All morning routines completed on schedule",
        },
        confirm=False,
    )
    assert handoff_preview.apl is not None
    assert handoff_preview.apl["document"]["type"] == "APL"
    assert "David → Sarah" in handoff_preview.apl["datasources"]["payload"]["header"]
    assert handoff_preview.display is not None
    assert "Shift Handoff: David → Sarah" in handoff_preview.display["title"]

    # 4. verify_routine_state (confirm=True commit)
    commit_res = await verify_routine_state(
        confirm=True,
        transaction_id=tx_id,
    )
    assert commit_res.apl is not None
    assert commit_res.apl["document"]["type"] == "APL"
    assert commit_res.display is not None

    # 5. flag_missed_routine
    missed_res = await flag_missed_routine(
        senior_id="margaret_01",
        routine_name="vitamins",
        scheduled_time="10:00",
    )
    assert missed_res.apl is not None
    assert missed_res.apl["document"]["type"] == "APL"
    assert "Vitamins Window" in missed_res.apl["datasources"]["payload"]["routineTitle"]
    assert missed_res.display is not None
    assert "Reminder: Vitamins" in missed_res.display["title"]


def test_tools_call_over_http_returns_apl_structure(isolated_db):
    """Assert Streamable HTTP /mcp tools/call publishes structuredContent with apl and display objects for all 4 tools."""
    app = get_app(host="127.0.0.1")
    AUTH_HEADERS = {
        "MCP-Protocol-Version": "2025-11-25",
        "Authorization": "Bearer janus-demo-caregiver-sarah",
    }
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        # 1. log_daily_routine over HTTP
        r_log = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 901,
                "method": "tools/call",
                "params": {
                    "name": "log_daily_routine",
                    "arguments": {
                        "senior_id": "margaret_01",
                        "category": "meal",
                        "details": "Morning oatmeal with blueberries",
                    },
                },
            },
            headers=AUTH_HEADERS,
        )
        assert r_log.status_code == 200
        sc_log = r_log.json()["result"]["structuredContent"]
        res_log = sc_log.get("result", sc_log)

        assert "apl" in res_log, "structuredContent missing 'apl' property"
        assert "display" in res_log, "structuredContent missing 'display' fallback property"

        apl_log = res_log["apl"]
        assert apl_log["document"]["type"] == "APL"
        assert apl_log["document"]["version"] == "2024.3"
        assert apl_log["datasources"]["payload"]["categoryTitle"] == "🍽️ Meal"
        display_log = res_log["display"]
        assert display_log["title"] == "Proposed: Meal"
        assert "Morning oatmeal with blueberries" in display_log["lines"][1]
        tx_id = res_log["transaction_id"]

        # 2. get_caregiver_summary over HTTP
        r_sum = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 902,
                "method": "tools/call",
                "params": {
                    "name": "get_caregiver_summary",
                    "arguments": {"senior_id": "margaret_01"},
                },
            },
            headers=AUTH_HEADERS,
        )
        assert r_sum.status_code == 200
        sc_sum = r_sum.json()["result"]["structuredContent"]
        res_sum = sc_sum.get("result", sc_sum)
        assert "apl" in res_sum
        assert res_sum["apl"]["document"]["version"] == "2024.3"
        assert "Timeline" in res_sum["apl"]["datasources"]["payload"]["header"]
        assert "display" in res_sum

        # 3. verify_routine_state (confirm=False preview) over HTTP
        r_prev = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 903,
                "method": "tools/call",
                "params": {
                    "name": "verify_routine_state",
                    "arguments": {
                        "senior_id": "margaret_01",
                        "action_type": "shift_handoff",
                        "payload": {
                            "departing_caregiver": "David",
                            "incoming_caregiver": "Sarah",
                            "handoff_notes": "Morning check complete",
                        },
                        "confirm": False,
                    },
                },
            },
            headers=AUTH_HEADERS,
        )
        assert r_prev.status_code == 200
        sc_prev = r_prev.json()["result"]["structuredContent"]
        res_prev = sc_prev.get("result", sc_prev)
        assert "apl" in res_prev
        assert res_prev["apl"]["document"]["version"] == "2024.3"
        assert "David → Sarah" in res_prev["apl"]["datasources"]["payload"]["header"]
        assert "display" in res_prev

        # 4. verify_routine_state (confirm=True commit) over HTTP
        r_commit = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 904,
                "method": "tools/call",
                "params": {
                    "name": "verify_routine_state",
                    "arguments": {
                        "confirm": True,
                        "transaction_id": tx_id,
                    },
                },
            },
            headers=AUTH_HEADERS,
        )
        assert r_commit.status_code == 200
        sc_commit = r_commit.json()["result"]["structuredContent"]
        res_commit = sc_commit.get("result", sc_commit)
        assert "apl" in res_commit
        assert res_commit["apl"]["document"]["version"] == "2024.3"
        assert "display" in res_commit

        # 5. flag_missed_routine over HTTP
        r_missed = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 905,
                "method": "tools/call",
                "params": {
                    "name": "flag_missed_routine",
                    "arguments": {
                        "senior_id": "margaret_01",
                        "routine_name": "vitamins",
                        "scheduled_time": "10:00",
                    },
                },
            },
            headers=AUTH_HEADERS,
        )
        assert r_missed.status_code == 200
        sc_missed = r_missed.json()["result"]["structuredContent"]
        res_missed = sc_missed.get("result", sc_missed)
        assert "apl" in res_missed
        assert res_missed["apl"]["document"]["version"] == "2024.3"
        assert "Vitamins Window" in res_missed["apl"]["datasources"]["payload"]["routineTitle"]
        assert "display" in res_missed

