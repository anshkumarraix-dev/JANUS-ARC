# PRODUCT FEEDBACK QUESTIONNAIRE — Alexa+ & FastMCP

> **Hackathon Submission**: *Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ Track)*  
> **Project Name**: Janus (ElderSync) — Non-Clinical Caregiver Synchronization FastMCP Server for Alexa+  
> **Repository**: [JANUS-ARC](https://github.com/anshkumarraix-dev/JANUS-ARC)  
> **Architecture & Track**: Self-hosted FastMCP v2 Server over Streamable HTTP (`MCP spec 2025-11-25`), SQLite WAL persistence, Echo Show 8 (768×480) Web Simulator.  
> **AWS Integration Scope**: No AWS cloud runtime services (e.g., AWS Lambda, Amazon DynamoDB, Amazon Bedrock, or Boto3) were used; the system executes 100% locally with open-source Python and SQLite. *AWS Builder mini-challenge eligibility is explicitly not claimed.*

---

## 📑 Table of Contents

1. [Tool-by-Tool Developer Experience Evaluation](#1-tool-by-tool-developer-experience-evaluation)
   - [1.1 Official Model Context Protocol Python SDK (`mcp`)](#11-official-model-context-protocol-python-sdk-mcp)
   - [1.2 Amazon Alexa Presentation Language (APL 2024.3)](#12-amazon-alexa-presentation-language-apl-20243)
   - [1.3 Starlette ASGI Framework & Uvicorn](#13-starlette-asgi-framework-uvicorn)
   - [1.4 Pydantic v2 Contract Framework](#14-pydantic-v2-contract-framework)
   - [1.5 Python SQLite3 Engine with WAL Mode](#15-python-sqlite3-engine-with-wal-mode)
   - [1.6 Web Speech API in Modern Web Browsers](#16-web-speech-api-in-modern-web-browsers)
   - [1.7 Cloudflare Quick Tunnels (`cloudflared`)](#17-cloudflare-quick-tunnels-cloudflared)
   - [1.8 Amazon Alexa+ Track Developer Experience & Platform Tooling](#18-amazon-alexa-track-developer-experience-platform-tooling)
2. [Structured Product Feedback Entries](#2-structured-product-feedback-entries)
   - [Entry #01: FastMCP Streamable HTTP Auth & Header Exposition](#entry-01-fastmcp-streamable-http-auth-header-exposition)
   - [Entry #02: Offline Developer Preview Tooling for APL Documents](#entry-02-offline-developer-preview-tooling-for-apl-documents)
   - [Entry #03: Streamable HTTP vs. Server-Sent Events Behind Tunnels](#entry-03-streamable-http-vs-server-sent-events-behind-tunnels)
   - [Entry #04: Auth Error Normalization Across ASGI and Browser Client](#entry-04-auth-error-normalization-across-asgi-and-browser-client)
3. [Summary of Remaining Author-Input Items](#3-summary-of-remaining-author-input-items)

---

## 1. Tool-by-Tool Developer Experience Evaluation

### 1.1 Official Model Context Protocol Python SDK (`mcp`)

* **Role in Project**:  
  Acts as the core protocol engine for JANUS ARC. Implements the official Model Context Protocol (MCP specification `2025-11-25`), handles tool registration (`@mcp.tool`), generates JSON Schema contracts (`tools/list`), routes JSON-RPC 2.0 tool execution (`tools/call`), and mounts the Streamable HTTP transport layer (`mcp.streamable_http_app`).
* **What Worked Well**:  
  - Clean, idiomatic decorator-based tool definition via `@mcp.tool`.
  - Native integration with Python type hints and Pydantic v2 models, which automatically compiles `inputSchema` and complex `$defs` output schemas.
  - Standardized behavioral tool annotations (`ToolAnnotations(read_only_hint=..., destructive_hint=..., idempotent_hint=...)`) enabling explicit hints for LLM hosts.
  - Built-in support for `stateless_http=True`, allowing standard request-response JSON-RPC turns over HTTP POST without maintaining long-lived server-side state.
* **What Needs Improvement**:  
  - **Middleware & Security Hooks**: FastMCP lacks built-in hooks for extracting Bearer tokens or injecting identity context into tools. The project had to construct a custom Starlette `AuthMiddleware` wrapping the ASGI application.
  - **Documentation on Streamable HTTP**: Most official documentation and online examples prioritize Standard I/O (stdio) or Server-Sent Events (SSE). Documentation and examples for mounting Streamable HTTP with CORS for browser-based simulators are sparse.
  - **Session Cleanup Logging**: In stateless mode, the session manager logs `Terminating session: None` on every single turn, creating noisy logs in production environments unless log levels are adjusted.
* **Setup & Onboarding Experience**:  
  Straightforward installation via `pip install mcp>=1.30.0`. Clean imports (`from mcp.server.mcpserver import MCPServer as FastMCP` and `from mcp.types import ToolAnnotations`).
* **Would the Author Build with it Again & Why**:  
  [AUTHOR INPUT REQUIRED: State whether you would build with the official Python FastMCP SDK again, and your primary technical rationale.]
* **Verified Evidence**:  
  - Manifest: `mcp>=1.30.0` in `requirements.txt` and `pyproject.toml`.
  - Code: `src/janus/server.py:19-20, 153-156, 1336-1341`.
  - Tests: Verified across `tests/test_janus.py` and `tests/test_real_network_latency.py`.

---

### 1.2 Amazon Alexa Presentation Language (APL 2024.3)

* **Role in Project**:  
  Provides the structured visual document specification for rendering glanceable cards on Echo Show smart screens (specifically tested against Echo Show 8 landscape, 768×480 viewport). Located in `src/janus/apl.py` and `docs/apl/*.json` (`routine_preview.json`, `caregiver_summary.json`, `handoff_confirm.json`, `missed_routine.json`).
* **What Worked Well**:  
  - Declarative JSON layout with clear separation between template structure and dynamic data bindings (`${payload.details}`, `${payload.spoken_prompt}`).
  - High-contrast responsive styling options well-suited for arm's length readability (24pt+ typography tokens, max 3 visual elements).
  - Clear specification documentation for APL 2024.3 document schemas.
* **What Needs Improvement**:  
  - **No Standalone Local Rendering Engine**: Amazon provides no open-source, local headless CLI or lightweight browser web component to render APL documents locally. Developers must either rely on the closed Alexa Developer Console or hand-craft CSS bridges in their own simulators.
  - **Data-Binding Schema Validation**: When data bindings fail or point to missing payload properties, error output in standard tools is silent rather than emitting structural warnings.
* **Setup & Onboarding Experience**:  
  Creating templates required manually authoring JSON documents and writing custom automated test suites (`tests/test_apl.py`) with regular expressions to verify that all `${payload.XYZ}` binding expressions match backend datasources.
* **Would the Author Build with it Again & Why**:  
  [AUTHOR INPUT REQUIRED: State whether you would author APL templates again for Alexa smart screens, and why.]
* **Verified Evidence**:  
  - Schemas: `docs/apl/*.json` (APL version `"2024.3"`).
  - Generator: `src/janus/apl.py:21-24, 75-190`.
  - Contract Tests: `tests/test_apl.py:1-60` (validating schema, font size tokens $\ge 24\text{pt}$, and 100% data-binding resolution).

---

### 1.3 Starlette ASGI Framework & Uvicorn

* **Role in Project**:  
  Underlying high-performance asynchronous web server layer hosting FastMCP's Streamable HTTP app, custom Bearer authentication middleware, CORS preflight handling, and the unauthenticated `/health` probe.
* **What Worked Well**:  
  - Minimalist, fast, and unopinionated ASGI framework.
  - Direct async execution delivering sub-15ms HTTP responses on local loopback.
  - Clean middleware composition (`AuthMiddleware` nested cleanly inside `CORSMiddleware`).
* **What Needs Improvement**:  
  - Direct ASGI scope manipulation requires caution: request streams cannot be consumed more than once, requiring token extraction directly from ASGI `scope["headers"]` rather than standard request body inspection.
* **Setup & Onboarding Experience**:  
  Standard Python installation (`uvicorn>=0.28.0`, `starlette>=0.36.0`). Native compatibility with `mcp.streamable_http_app`.
* **Would the Author Build with it Again & Why**:  
  [AUTHOR INPUT REQUIRED: State whether you would choose Starlette/Uvicorn as your ASGI foundation for MCP microservices again, and why.]
* **Verified Evidence**:  
  - Manifest: `pyproject.toml:17-18`.
  - Code: `src/janus/server.py:15-18, 70-150, 1330-1411`.

---

### 1.4 Pydantic v2 Contract Framework

* **Role in Project**:  
  Provides type validation, schema definitions, and serialization models for all 4 MCP tools (`src/janus/tools/`). Enforces validation on routine categories (`meal`, `hydration`, `vitamins`, `activity`, `wellness`), timestamps, confirmation gate flags, and shift handoff payloads.
* **What Worked Well**:  
  - Tremendous execution speed powered by the Pydantic core Rust engine.
  - Seamless generation of JSON Schema contracts including complex discriminated unions (`Union[RoutineLogProposalResponse, ProposalErrorResponse]`).
  - Native integration with Python's `typing.Annotated` and `pydantic.Field` for rich parameter descriptions.
* **What Needs Improvement**:  
  - Schema resolution for complex union returns required explicit `$defs` mapping so external validators (`jsonschema.validate()`) would not reject valid proposal previews.
* **Setup & Onboarding Experience**:  
  Seamless installation via `pydantic>=2.6.0`.
* **Would the Author Build with it Again & Why**:  
  [AUTHOR INPUT REQUIRED: State whether you would use Pydantic v2 again for MCP schemas.]
* **Verified Evidence**:  
  - Manifest: `pydantic>=2.6.0` in `requirements.txt`.
  - Code: `src/janus/tools/base.py`, `src/janus/tools/routine.py`, `src/janus/tools/handoff.py`.
  - Tests: Schema validation verified via `jsonschema` in `tests/test_real_network_latency.py`.

---

### 1.5 Python SQLite3 Engine with WAL Mode

* **Role in Project**:  
  Provides zero-cost, zero-dependency local persistence (`data/janus.db`) storing senior profiles, routine logs, routine schedules, two-step confirmation proposals, and SHA-256 cryptographic audit logs.
* **What Worked Well**:  
  - Zero external database installation, zero cloud credentials, zero hosting fees.
  - Write-Ahead Logging (`PRAGMA journal_mode=WAL`) and `PRAGMA synchronous=NORMAL` delivered sub-5ms write operations and non-blocking concurrent reads.
  - Native Python standard library inclusion guarantees 100% portability across Windows, macOS, and Linux.
* **What Needs Improvement**:  
  - SQLite is single-node by design. Multi-process write concurrency on Windows requires careful timeout configuration (`timeout=10.0`) and single-writer locks to avoid `sqlite3.OperationalError: database is locked`.
* **Setup & Onboarding Experience**:  
  Instant setup; tables and initial seed data automatically initialize on first server launch via `storage.init_db()`.
* **Would the Author Build with it Again & Why**:  
  [AUTHOR INPUT REQUIRED: State whether you would choose SQLite WAL mode again for local/edge eldercare servers.]
* **Verified Evidence**:  
  - Code: `src/janus/storage.py:30-110`.
  - Audit: `src/janus/audit.py:1-135`.

---

### 1.6 Web Speech API in Modern Web Browsers

* **Role in Project**:  
  Provides ambient speech recognition (`webkitSpeechRecognition`) and voice synthesis (`speechSynthesis`) inside `simulator/index.html` to simulate an Echo Show smart screen hands-free voice experience.
* **What Worked Well**:  
  - Zero API keys, zero cloud costs, and runs directly within the user's browser.
  - Low transcription latency on Google Chrome and Microsoft Edge.
* **What Needs Improvement**:  
  - Browser support is fragmented (Firefox and Safari do not support `webkitSpeechRecognition` out of the box).
  - Security policies block microphone access when running under `Origin: null` (such as inside sandboxed iframes or certain local file contexts), necessitating manual fallback to typed input chips.
* **Setup & Onboarding Experience**:  
  Built into browser JavaScript; required writing defensive feature detection and typed chip fallbacks.
* **Would the Author Build with it Again & Why**:  
  [AUTHOR INPUT REQUIRED: State whether you would use the Web Speech API again for browser-based voice prototyping.]
* **Verified Evidence**:  
  - Code: `simulator/index.html:4720-4780`.
  - Documentation: `docs/LEARNINGS.md:Entry 003`.

---

### 1.7 Cloudflare Quick Tunnels (`cloudflared`)

* **Role in Project**:  
  Provides optional ephemeral public HTTPS ingress (`scripts/tunnel.ps1`, `scripts/tunnel.sh`) allowing hackathon reviewers to test the local FastMCP server remotely (`https://*.trycloudflare.com`) without configuring firewall port-forwarding.
* **What Worked Well**:  
  - Free, requires no account creation, and terminates TLS automatically.
* **What Needs Improvement**:  
  - Quick Tunnel URLs are ephemeral and change whenever the local machine reboots or the network reconnects.
  - Long-lived Server-Sent Events (SSE) connections frequently drop or buffer behind free tunnels, requiring the use of stateless Streamable HTTP over `POST /mcp`.
* **Setup & Onboarding Experience**:  
  Single portable binary; automated via PowerShell and Bash helper scripts.
* **Would the Author Build with it Again & Why**:  
  [AUTHOR INPUT REQUIRED: State whether you would use Cloudflare quick tunnels again for hackathon demo endpoints.]
* **Verified Evidence**:  
  - Scripts: `scripts/tunnel.ps1`, `scripts/tunnel.sh`.
  - Documentation: `docs/LEARNINGS.md:Entry 002`.

---

### 1.8 Amazon Alexa+ Track Developer Experience & Platform Tooling

* **Role in Project**:  
  The target hackathon track and host ecosystem for Janus (ElderSync).
* **What Worked Well**:  
  - **Adoption of Open Standards**: Embracing the Model Context Protocol (MCP) as the tool integration layer allows developers to build portable, standard-compliant servers rather than proprietary closed skills.
  - **Clear Hackathon Rules & FAQ**: The Devpost FAQ explicitly clarified that invite-only preview tools (such as the Category SDK) were not required for general developer submissions, leveling the playing field for open-source participants.
* **What Needs Improvement**:  
  - **Availability of an Official Alexa+ Testing Sandbox**: The absence of an open developer preview simulator for Alexa+ forces developers to construct their own web simulators from scratch. Providing an official local MCP client simulator mimicking Alexa+ display viewports and prompt-handling would save substantial engineering time.
* **Setup & Onboarding Experience**:  
  Devpost portal, FAQ documentation, and standard MCP specification guides.
* **Would the Author Build with it Again & Why**:  
  [AUTHOR INPUT REQUIRED: State whether you would participate in an Amazon Alexa+ developer hackathon again.]

---

## 2. Structured Product Feedback Entries

### Entry #01: FastMCP Streamable HTTP Auth & Header Exposition
- **Date**: 2026-10-20
- **Versions**:
  - Python: 3.12 / 3.14
  - OS: Windows 11 / Ubuntu 22.04
  - MCP SDK: `mcp>=1.30.0`
  - Related Frameworks: Starlette 0.36+, Uvicorn 0.28+
- **What I Tried**:  
  Mounting FastMCP over Streamable HTTP (`mcp.streamable_http_app(streamable_http_path="/mcp")`) while enforcing Bearer token authentication and allowing browser-based simulator clients to inspect protocol headers.
- **Exact Command / URL**:  
  `POST http://127.0.0.1:8000/mcp`
- **Exact Error Text / Obstacle**:  
  Browser simulators received CORS errors and could not read session headers because `Mcp-Session-Id` and `MCP-Protocol-Version` were not exposed by default in the ASGI response headers. Additionally, direct browser CORS preflight `OPTIONS` requests failed when auth middleware was placed naively in the application stack.
- **Time Lost**:  
  [AUTHOR INPUT REQUIRED: Estimate hours spent diagnosing FastMCP CORS headers and ASGI middleware order.]
- **Workaround**:  
  Wrapped FastMCP with custom Starlette `AuthMiddleware` that explicitly exempts `OPTIONS` and `/health`, and configured `CORSMiddleware` with `expose_headers=["Mcp-Session-Id", "MCP-Protocol-Version"]` (implemented in `src/janus/server.py:81-90, 1347-1354`).
- **Suggested Fix**:  
  The FastMCP Python SDK should provide a native configuration parameter on `streamable_http_app()` to accept custom authentication handlers and automatically expose standard MCP headers in CORS configurations.

---

### Entry #02: Offline Developer Preview Tooling for APL Documents
- **Date**: 2026-10-20
- **Versions**:
  - APL Specification: 2024.3
  - Python: 3.12+
  - Web Simulator: Vanilla JS / HTML5
- **What I Tried**:  
  Authoring and previewing Amazon Alexa Presentation Language (APL 2024.3) visual card templates for Margaret Vance's Echo Show 8 timeline cards (`docs/apl/*.json`) locally.
- **Exact Command / URL**:  
  `docs/apl/routine_preview.json`, `docs/apl/caregiver_summary.json`
- **Exact Error Text / Obstacle**:  
  No local open-source CLI, npm package, or Python library exists to parse and render APL documents into HTML/Canvas outside the proprietary Alexa Developer Console web authoring tool.
- **Time Lost**:  
  [AUTHOR INPUT REQUIRED: Estimate hours spent hand-building schema tests and CSS card bridges for APL templates.]
- **Workaround**:  
  Developed automated Python contract tests (`tests/test_apl.py`) validating APL JSON schema compliance, 24pt+ glanceability tokens, and regex data-binding completeness (`${payload.XYZ}`), paired with a custom CSS card renderer in `simulator/index.html`.
- **Suggested Fix**:  
  Amazon should release an official, lightweight open-source APL Web Component (`<alexa-apl-preview>`) or CLI renderer so developers building MCP servers can validate and preview smart screen cards locally without logging into the developer console.

---

### Entry #03: Streamable HTTP vs. Server-Sent Events Behind Tunnels
- **Date**: 2026-10-20
- **Versions**:
  - Python: 3.12+
  - MCP SDK: `mcp>=1.30.0`
  - Tunnel: `cloudflared` (Cloudflare Quick Tunnels)
- **What I Tried**:  
  Exposing the local FastMCP server to external hackathon reviewers using Server-Sent Events (`/sse`) over Cloudflare Quick Tunnels (`cloudflared tunnel --url http://localhost:8000`).
- **Exact Command / URL**:  
  `https://*.trycloudflare.com/sse`
- **Exact Error Text / Obstacle**:  
  Cloudflare Quick Tunnels buffered chunked SSE responses and dropped persistent connections after brief idle periods, causing external clients to fail handshake initialization.
- **Time Lost**:  
  [AUTHOR INPUT REQUIRED: Estimate hours spent debugging SSE connection drops over Cloudflare tunnels.]
- **Workaround**:  
  Configured FastMCP in `stateless_http=True` mode over `POST /mcp` instead of long-lived SSE streams. Standard request-response HTTP POST calls completely bypass tunnel chunking issues and execute reliably.
- **Suggested Fix**:  
  MCP SDK documentation should highlight that `stateless_http=True` over Streamable HTTP is the recommended transport when operating behind reverse proxies, tunnels, or serverless gateways.

---

### Entry #04: Auth Error Normalization Across ASGI and Browser Client
- **Date**: 2026-10-23
- **Versions**:
  - Python: 3.12 / 3.14
  - MCP SDK: `mcp>=1.30.0`
  - Client: `simulator/index.html`
- **What I Tried**:  
  Connecting the web simulator to `http://127.0.0.1:8000/mcp` and displaying readable error states when authentication fails or demo tokens are rejected.
- **Exact Command / URL**:  
  `POST http://127.0.0.1:8000/mcp` (with missing or invalid Bearer token)
- **Exact Error Text / Obstacle**:  
  `HTTP 401 Unauthorized: Missing or invalid Bearer token`  
  Starlette's `AuthMiddleware` originally emitted `{"message": "..."}`, whereas the web simulator expected FastAPI's standard `{"detail": "..."}` convention, causing the simulator to fall back to a generic network failure message rather than explaining the auth issue to the evaluator.
- **Time Lost**:  
  [AUTHOR INPUT REQUIRED: Estimate hours spent diagnosing the 401 detail vs. message payload discrepancy.]
- **Workaround**:  
  Updated Starlette's `JSONResponse` to return both `message` and `detail` keys (`src/janus/server.py:125-135`), sanitized incoming Bearer tokens against copy-pasted quotation marks (`src/janus/auth.py:65-75`), and updated `simulator/index.html` to parse both fields.
- **Suggested Fix**:  
  Web application templates for MCP should document standardized error schema conventions across ASGI middlewares and frontend inspector tools.

---

## 3. Summary of Remaining Author-Input Items

The following author-experience items represent personal opinions, developer hours, or forward-looking choices that only the hackathon participant can answer. Complete these fields before submitting:

- [ ] **Section 1.1**: Would you build with the official Python FastMCP SDK again, and what is your primary rationale?
- [ ] **Section 1.2**: Would you author APL templates again for Alexa smart screens, and why?
- [ ] **Section 1.3**: Would you choose Starlette/Uvicorn as your ASGI foundation for MCP microservices again, and why?
- [ ] **Section 1.4**: Would you use Pydantic v2 again for MCP schemas?
- [ ] **Section 1.5**: Would you choose SQLite WAL mode again for local/edge eldercare servers?
- [ ] **Section 1.6**: Would you use the Web Speech API again for browser-based voice prototyping?
- [ ] **Section 1.7**: Would you use Cloudflare quick tunnels again for hackathon demo endpoints?
- [ ] **Section 1.8**: Would you participate in an Amazon Alexa+ developer hackathon again?
- [ ] **Entry #01 Time Lost**: Estimated hours spent diagnosing FastMCP CORS headers and ASGI middleware order.
- [ ] **Entry #02 Time Lost**: Estimated hours spent hand-building schema tests and CSS card bridges for APL templates.
- [ ] **Entry #03 Time Lost**: Estimated hours spent debugging SSE connection drops over Cloudflare tunnels.
- [ ] **Entry #04 Time Lost**: Estimated hours spent diagnosing the 401 detail vs. message payload discrepancy.
