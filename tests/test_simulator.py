"""Janus (ElderSync) — Web Simulator Integrity Test Suite.

Verifies:
1. simulator/index.html exists and is non-empty.
2. Strict offline invariant: Zero external script/font/stylesheet CDN calls (no fonts.googleapis.com, etc.).
3. Echo Show 8 viewport dimensions strictly 768x480.
4. Latency HUD contains two separate numbers (router latency and real HTTP round-trip).
5. Router state machine implements pendingTx, confirmation, cancellation, and clarifying prompt.
6. Authorization: Bearer token is supported and configured.
7. Caregiver dashboard implements 3-second auto-sync interval and live sync flash indicator.
8. 'Try to break it' button row implements all 4 server-side refusal demonstration tests.
"""

from __future__ import annotations

import os
import re
import pytest

SIMULATOR_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "simulator", "index.html"))
DEMO_MD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs", "DEMO.md"))


@pytest.fixture
def simulator_html() -> str:
    assert os.path.exists(SIMULATOR_PATH), f"Simulator file not found at {SIMULATOR_PATH}"
    with open(SIMULATOR_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_simulator_file_exists_and_valid_structure(simulator_html: str):
    """Assert simulator has basic valid HTML5 structure."""
    assert "<!DOCTYPE html>" in simulator_html
    assert "<html" in simulator_html
    assert "</html>" in simulator_html
    assert "<head>" in simulator_html
    assert "<body>" in simulator_html


def test_zero_external_network_requests(simulator_html: str):
    """Assert no external CDN, Google Fonts, or remote asset requests are made."""
    # Check for google fonts
    assert "fonts.googleapis.com" not in simulator_html
    assert "fonts.gstatic.com" not in simulator_html

    # Check that any <link rel="stylesheet"> or <script src="..."> does not load from http/https
    link_hrefs = re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', simulator_html, re.IGNORECASE)
    for href in link_hrefs:
        assert not href.startswith("http://") and not href.startswith("https://") and not href.startswith("//"), (
            f"External stylesheet found: {href}"
        )

    script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', simulator_html, re.IGNORECASE)
    for src in script_srcs:
        assert not src.startswith("http://") and not src.startswith("https://") and not src.startswith("//"), (
            f"External script found: {src}"
        )


def test_echo_show_8_viewport_dimensions(simulator_html: str):
    """Assert Echo Show viewport is strictly 768x480."""
    assert "width: 768px" in simulator_html
    assert "height: 480px" in simulator_html


def test_latency_hud_has_two_separate_numbers(simulator_html: str):
    """Assert latency HUD has separate router and HTTP round-trip indicators."""
    assert "hud-router-ms" in simulator_html
    assert "hud-http-ms" in simulator_html
    assert "Router:" in simulator_html
    assert "HTTP RTT:" in simulator_html


def test_router_state_machine_pending_tx(simulator_html: str):
    """Assert router state machine tracks pendingTx and rejects confirm without preview."""
    assert "let pendingTx" in simulator_html
    assert "There's nothing waiting for confirmation." in simulator_html
    assert "Action cancelled. Nothing was written." in simulator_html
    assert "I didn't quite catch that" in simulator_html


def test_bearer_token_authorization(simulator_html: str):
    """Assert bearer token input exists and is attached as Authorization header."""
    assert "setting-token" in simulator_html
    assert "Bearer" in simulator_html
    assert "'Authorization': `Bearer ${token}`" in simulator_html or 'Authorization' in simulator_html


def test_caregiver_3s_polling_and_sync_flash(simulator_html: str):
    """Assert caregiver dashboard has 3-second auto-sync loop and sync-flash visual indicator."""
    assert "3000" in simulator_html
    assert "sync-flash" in simulator_html
    assert "pollCaregiverSummary" in simulator_html


def test_try_to_break_it_button_row(simulator_html: str):
    """Assert all 4 safety refusal demonstration tests exist."""
    assert "testBreakConfirmNoPreview" in simulator_html
    assert "testBreakExpiredTx" in simulator_html
    assert "testBreakWrongSenior" in simulator_html
    assert "testBreakClinicalViolation" in simulator_html


def test_demo_documentation_exists():
    """Assert docs/DEMO.md exists with required step-by-step instructions."""
    assert os.path.exists(DEMO_MD_PATH)
    with open(DEMO_MD_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    assert "There's nothing waiting for confirmation." in content
    assert "Try to Break It" in content
    assert "Margaret Vance" in content


# =============================================================================
# Background Polling, Speak Option & Voice Toggle Invariant Tests
# =============================================================================

def extract_function_body(source: str, func_name: str) -> str:
    """Extract JavaScript function body by name using brace matching."""
    pattern = rf"function\s+{func_name}\s*\([^)]*\)\s*\{{"
    match = re.search(pattern, source)
    if not match:
        pattern = rf"async\s+function\s+{func_name}\s*\([^)]*\)\s*\{{"
        match = re.search(pattern, source)
    assert match, f"Function {func_name} not found in source."
    start_idx = match.end() - 1
    depth = 0
    for i in range(start_idx, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : i + 1]
    raise ValueError(f"Mismatched braces while extracting {func_name}")


def validate_poll_caregiver_summary_source(fn_body: str) -> None:
    """Validator that raises AssertionError if pollCaregiverSummary does not strictly satisfy safety invariants."""
    assert "callMCPTool" in fn_body, "pollCaregiverSummary must call callMCPTool"
    assert re.search(r"onSuccess\s*:", fn_body), "pollCaregiverSummary MUST pass onSuccess to callMCPTool"
    assert re.search(r"speak\s*:\s*false", fn_body), "pollCaregiverSummary MUST pass speak: false"
    assert "setAlexaSpeaking" not in fn_body, "pollCaregiverSummary must never call setAlexaSpeaking directly"
    assert "renderSummaryOnEchoShow" not in fn_body, "pollCaregiverSummary must never call renderSummaryOnEchoShow directly"
    assert "screen-body" not in fn_body, "pollCaregiverSummary must never touch #screen-body"


def test_poll_caregiver_summary_passes_on_success_and_never_speaks(simulator_html: str):
    """Assert pollCaregiverSummary passes onSuccess, speak: false, and never speaks or repaints senior screen."""
    fn_body = extract_function_body(simulator_html, "pollCaregiverSummary")
    validate_poll_caregiver_summary_source(fn_body)

    # Prove test failure if onSuccess is omitted or disabled
    buggy_body = fn_body.replace("onSuccess", "disabledSuccess")
    with pytest.raises(AssertionError, match="onSuccess"):
        validate_poll_caregiver_summary_source(buggy_body)

    # Prove test failure if speak: false is removed or set to true
    buggy_speak = fn_body.replace("speak: false", "speak: true")
    with pytest.raises(AssertionError, match="speak: false"):
        validate_poll_caregiver_summary_source(buggy_speak)


def test_call_mcp_tool_guards_speak_and_screen_body(simulator_html: str):
    """Assert callMCPTool guards speaking and #screen-body updates behind explicit speak option."""
    fn_body = extract_function_body(simulator_html, "callMCPTool")
    assert "options.speak" in fn_body or "canSpeak" in fn_body
    assert "canSpeak" in fn_body and "setAlexaSpeaking" in fn_body
    assert "else if (canSpeak)" in fn_body or "if (canSpeak)" in fn_body


def test_set_alexa_speaking_ignores_duplicate_within_8_seconds(simulator_html: str):
    """Assert setAlexaSpeaking ignores requests to speak text identical to last spoken text within 8 seconds."""
    fn_body = extract_function_body(simulator_html, "setAlexaSpeaking")
    assert "lastSpokenText" in simulator_html
    assert "lastSpokenTime" in simulator_html
    assert "8000" in fn_body, "setAlexaSpeaking must enforce an 8-second (8000ms) deduplication window"
    assert "lastSpokenText" in fn_body
    assert "return" in fn_body


def test_visible_voice_toggle_in_status_bar(simulator_html: str):
    """Assert a visible Voice on/off toggle exists in status bar, default ON, remembered in memory only."""
    assert 'id="hud-voice-toggle"' in simulator_html
    assert "toggleVoiceOutput" in simulator_html
    assert "let isVoiceEnabled = true" in simulator_html
    voice_fn_body = extract_function_body(simulator_html, "toggleVoiceOutput")
    assert "localStorage" not in voice_fn_body
    assert "sessionStorage" not in voice_fn_body


def test_summary_speech_uses_dynamic_senior_name(simulator_html: str):
    """Assert summary speech replaces hardcoded 'Margaret's summary' with active senior display name."""
    assert "Margaret's summary for today" not in simulator_html
    fn_body = extract_function_body(simulator_html, "handleToolSuccess")
    assert "summary for today" in fn_body
    assert "senior-display-name" in fn_body or "senior_name" in fn_body

