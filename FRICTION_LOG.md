# FRICTION LOG — Alexa+ Track & MCP Developer Experience

> **Hackathon Submission**: *Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ Track)*  
> **Project Name**: JANUS-ARC — Non-Clinical Caregiver Synchronization FastMCP Server for Alexa+  
> **Repository**: [JANUS-ARC](https://github.com/anshkumarraix-dev/JANUS-ARC)  
> **Architecture**: Self-hosted FastMCP v2 Server over Streamable HTTP (`MCP spec 2025-11-25`), local SQLite WAL storage, Echo Show 8 (768×480) Web Simulator.  
> **Evaluation Scope**: Non-clinical elder daily living routines and caregiver shift handoffs. Zero cloud paid APIs or unverified device claims.

---

## 📋 Friction Log Template

Use the following template for each confirmed friction entry:

### Entry #[NUMBER]: [Concise Title of Friction Point]
- **Date**: YYYY-MM-DD
- **Environment**: [e.g. Windows 11 CMD / PowerShell / Ubuntu 22.04 / macOS Sonoma]
- **Versions**:
  - Python: [e.g. 3.12.x / 3.14.x]
  - MCP SDK / FastMCP: [e.g. mcp>=1.30.0]
  - Key Dependencies: [e.g. starlette, uvicorn, pydantic]
- **Task Being Attempted**:
  [Detailed description of what you were trying to accomplish and why]
- **Exact Command / URL**:
  ```bash
  [Exact command executed or URL requested]
  ```
- **Exact Error Text**:
  ```
  [Verbatim terminal output, exception traceback, or HTTP response error]
  ```
- **Expected vs. Actual Result**:
  - *Expected*: [What should have occurred]
  - *Actual*: [What actually occurred]
- **Severity & Impact**:
  [Blocker / High / Medium / Low — effect on development progress or evaluation]
- **Time Lost**:
  [Estimated engineering time spent diagnosing, debugging, and resolving]
- **Workaround Actually Used**:
  [Step-by-step technical workaround implemented to unblock progress]
- **Root Cause**:
  [Underlying architectural, configuration, or platform cause, if established]
- **Actionable Suggestion for Maintainers / Platform**:
  [Specific recommendation for MCP specification, framework maintainers, or Amazon platform]

---

## 📜 Confirmed Entries

### Entry #01: Simulator Connection Failure and Subsequent HTTP 401 Rejection in Local Demo Mode
- **Date**: 2026-10-23
- **Environment**: Windows 11 (Command Prompt & PowerShell)
- **Versions**:
  - Python: 3.12 / 3.14
  - MCP SDK: `mcp>=1.30.0`
  - Key Dependencies: Starlette 0.36+, Uvicorn 0.28+, Pydantic 2.6+
- **Task Being Attempted**:  
  Connecting the local dual-screen web simulator (`simulator/index.html`) to the local FastMCP server running at `http://127.0.0.1:8000/mcp` to test senior routine proposals and caregiver timeline synchronization.
- **Exact Command / URL**:  
  1. Starting server:
     ```cmd
     set JANUS_DEMO_MODE=1
     .smoke_venv\Scripts\python.exe -m janus.server
     ```
  2. Simulator dispatching tool invocation to:
     `POST http://127.0.0.1:8000/mcp`
- **Exact Error Text**:  
  *Initial symptom*:
  ```
  Unable to sync with 127.0.0.1:8000/mcp. Ensure the Python FastMCP server is running.
  ```
  *Subsequent symptom*:
  ```
  Authentication refused (HTTP 401): Unauthorized: Missing or invalid Bearer token
  ```
- **Expected vs. Actual Result**:  
  - *Expected*: The simulator connects cleanly to `http://127.0.0.1:8000/mcp` using its pre-configured default demo Bearer token (`janus-demo-senior-margaret`), displays `Server Online` with a green pulse, and executes `tools/call` for `log_daily_routine`.
  - *Actual*: The simulator first reported an unreachable server connection failure, and subsequently returned HTTP 401 with `Unauthorized: Missing or invalid Bearer token`, despite the server startup log confirming: `[INFO] janus.server: JANUS_DEMO_MODE=1 active. Demo tokens (margaret_01, arthur_02) are enabled.`
- **Severity & Impact**:  
  **High** — Prevented initial simulator-to-server communication and blocked end-to-end user evaluation until connection and Bearer token parsing were investigated.
- **Time Lost**:  
  [AUTHOR INPUT REQUIRED: Estimate engineering time spent diagnosing the connection failure and HTTP 401 token rejection sequence.]
- **Workaround Actually Used**:  
  1. Verified server process was actively listening on `0.0.0.0:8000` via `/health`.
  2. Hardened Bearer token extraction in `src/janus/auth.py` to strip accidental surrounding quotation marks and redundant `Bearer ` prefixes from token strings.
  3. Normalized Starlette `AuthMiddleware` 401 error payloads to include both `message` and `detail` keys (`src/janus/server.py`) so web clients expecting either convention receive the exact refusal reason.
  4. Hardened `JANUS_DEMO_MODE` environment variable parsing in `src/janus/auth.py` and `src/janus/server.py` to strip shell quotation marks (e.g. handling `set JANUS_DEMO_MODE="1"` vs `set JANUS_DEMO_MODE=1`).
- **Root Cause**:  
  Local application configuration and data-handling (not an upstream MCP SDK or Amazon platform bug):
  1. Initial connection failure occurred because the backend server process had not yet started or had bound to an alternate port.
  2. Subsequent HTTP 401 occurred due to payload format mismatch (Starlette returning `message` while the simulator frontend parsed `detail`) combined with token string wrapping sensitivity in local shell environments.
- **Final Outcome Verification**:  
  [AUTHOR INPUT REQUIRED: Confirm whether your subsequent manual test run of the simulator with `janus-demo-senior-margaret` connected cleanly and showed 'Server Online' after this fix.]
- **Actionable Suggestion for Maintainers / Platform**:  
  Provide standardized cross-platform environment variable guidelines for Windows shells in MCP quickstart templates, and adopt standardized error JSON response conventions (`{"detail": "...", "message": "..."}`) across ASGI authentication middleware examples.

---

### Entry #02: Cloudflare Quick Tunnels Dropping Long-Lived Server-Sent Events (SSE)
- **Date**: 2026-10-20
- **Environment**: Windows 11 / Ubuntu 22.04
- **Versions**:
  - Python: 3.12+
  - MCP SDK: `mcp>=1.30.0`
  - Ingress Tool: `cloudflared` (Cloudflare Quick Tunnels)
- **Task Being Attempted**:  
  Exposing the local FastMCP server to external hackathon evaluators over a public HTTPS URL using Server-Sent Events (`/sse`) via Cloudflare Quick Tunnels (`cloudflared tunnel --url http://localhost:8000`).
- **Exact Command / URL**:  
  ```bash
  cloudflared tunnel --url http://localhost:8000
  # Client connecting to:
  https://*.trycloudflare.com/sse
  ```
- **Exact Error Text**:  
  ```
  net::ERR_HTTP2_PROTOCOL_ERROR (or connection timeout after 30-60s idle)
  FastMCP SSE client failed to receive stream flushes; tool invocation timed out.
  ```
- **Expected vs. Actual Result**:  
  - *Expected*: Continuous, persistent SSE event streaming over public HTTPS tunnel for remote MCP tool execution.
  - *Actual*: Cloudflare Quick Tunnels buffered chunked transfer encodings or terminated idle SSE connections prematurely, causing tool invocation timeouts.
- **Severity & Impact**:  
  **Medium** — Prevented relying on persistent SSE streams for remote reviewer evaluation over free quick tunnels.
- **Time Lost**:  
  [AUTHOR INPUT REQUIRED: Estimate engineering time spent troubleshooting SSE buffering and disconnection over quick tunnels.]
- **Workaround Actually Used**:  
  Switched FastMCP v2 transport configuration from persistent SSE to stateless **Streamable HTTP** over `POST /mcp` (`stateless_http=True`, `json_response=True` in `src/janus/server.py:1336-1341`). Stateless request-response JSON-RPC turns completely bypass reverse-proxy chunk buffering issues.
- **Root Cause**:  
  Free Cloudflare Quick Tunnels enforce connection timeouts and buffer chunked HTTP streams by default unless specific enterprise streaming configurations or continuous heartbeat pings are active.
- **Actionable Suggestion for Maintainers / Platform**:  
  MCP SDK documentation should prominently document that `stateless_http=True` over Streamable HTTP (`POST /mcp`) is the recommended transport when exposing local servers through reverse proxies, tunnels, or API gateways.

---

### Entry #03: Browser Sandbox `Origin: null` Disabling Web Speech API in Simulator
- **Date**: 2026-10-20
- **Environment**: Google Chrome & Microsoft Edge on Windows 11
- **Versions**:
  - Web Speech API (`webkitSpeechRecognition`)
  - Web Simulator: Vanilla JS / HTML5
- **Task Being Attempted**:  
  Demonstrating hands-free ambient voice logging for elderly seniors in `simulator/index.html` when loaded via local `file:///` paths or embedded within an iframe.
- **Exact Command / URL**:  
  `file:///C:/Users/Lenovo/Downloads/JANUS%20ARC/simulator/index.html`
- **Exact Error Text**:  
  ```
  DOMException: Failed to execute 'start' on 'SpeechRecognition': recognition has already started or microphone permission was denied.
  Browser console warning: SpeechRecognition is disabled for opaque origins (Origin: null).
  ```
- **Expected vs. Actual Result**:  
  - *Expected*: Clicking the voice microphone button captures audio, transcribes speech locally, and routes the utterance to the MCP server.
  - *Actual*: Browsers strictly block microphone access and disable `webkitSpeechRecognition` when loaded under an opaque `Origin: null` context (such as direct `file:///` opening or unprivileged iframes).
- **Severity & Impact**:  
  **Medium** — Risked preventing evaluators opening `simulator/index.html` directly from testing voice input.
- **Time Lost**:  
  [AUTHOR INPUT REQUIRED: Estimate engineering time spent identifying Origin: null restrictions and implementing typed fallbacks.]
- **Workaround Actually Used**:  
  Implemented a dual-input architecture in `simulator/index.html`: Web Speech API voice capture is utilized when running on secure origins (`http://localhost` or `http://127.0.0.1`), while clickable preset utterance chips (*"I drank 2 glasses of water"*, *"Confirm"*) and a typed text input bar provide full functionality under any origin.
- **Root Cause**:  
  Chromium and W3C Web Speech security specifications restrict audio hardware capture to trusted origins (`https://` or `http://localhost`) and deny opaque origins (`file://` or sandboxed frames).
- **Actionable Suggestion for Maintainers / Platform**:  
  Hackathon documentation for smart screen / voice tracks should provide reference patterns for dual voice-and-chip input interfaces so browser prototypes remain fully testable without requiring a local web server.

---

### Entry #04: Lack of Offline Local Rendering Tooling for APL 2024.3 Documents
- **Date**: 2026-10-20
- **Environment**: Local Development (Windows 11 / Linux)
- **Versions**:
  - APL Specification: 2024.3
  - Python: 3.12+
- **Task Being Attempted**:  
  Validating and visually previewing Amazon Alexa Presentation Language (APL 2024.3) smart-screen templates (`docs/apl/*.json`) locally during FastMCP server development.
- **Exact Command / URL**:  
  `docs/apl/routine_preview.json`, `docs/apl/caregiver_summary.json`
- **Exact Error Text**:  
  *Obstacle*: No local CLI tool, Python package, or npm library exists to render APL documents into HTML/Canvas outside the proprietary Alexa Developer Console web authoring tool.
- **Expected vs. Actual Result**:  
  - *Expected*: An official open-source local CLI or browser web component to preview APL card documents alongside MCP tool responses.
  - *Actual*: Visual verification required manually writing a custom CSS card renderer in `simulator/index.html` and verifying contracts through JSON schema tests.
- **Severity & Impact**:  
  **Low to Medium** — Added development friction and prevented direct rendering of exact APL binary layouts locally.
- **Time Lost**:  
  [AUTHOR INPUT REQUIRED: Estimate engineering time spent hand-crafting schema tests and CSS bridges for APL templates.]
- **Workaround Actually Used**:  
  Wrote an automated contract test suite (`tests/test_apl.py`) validating JSON schema compliance, 24pt+ glanceability constraints, and data-binding expressions (`${payload.XYZ}`), accompanied by clear disclaimers that templates are built to spec but not console-validated.
- **Root Cause**:  
  Amazon's APL rendering engine is proprietary and hosted primarily within the Alexa Developer Console, with no standalone open-source rendering SDK available for local development.
- **Actionable Suggestion for Maintainers / Platform**:  
  Amazon should release an open-source APL Web Component (e.g. `<alexa-apl-renderer>`) or a headless Node/Python package so developers building MCP servers can validate and preview visual smart screen layouts locally.

---

## 🔍 Summary of Facts for Author Verification

Before submitting this document to Devpost, verify and complete the following 5 items:

1. **Entry #01 Final Outcome**: Confirm whether your manual simulator test run using `janus-demo-senior-margaret` connected cleanly and showed `Server Online` after the server was started with `JANUS_DEMO_MODE=1`.
2. **Entry #01 Time Lost**: State your estimated developer hours spent diagnosing the initial connection error and HTTP 401 token refusal.
3. **Entry #02 Time Lost**: State your estimated developer hours spent troubleshooting Cloudflare quick tunnel SSE drops before switching to `stateless_http=True`.
4. **Entry #03 Time Lost**: State your estimated developer hours spent debugging the `Origin: null` Web Speech API restriction.
5. **Entry #04 Time Lost**: State your estimated developer hours spent building custom schema tests and CSS card bridges for APL templates.
