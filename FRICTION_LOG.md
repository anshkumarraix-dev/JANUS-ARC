# FRICTION LOG — Alexa+ Track & MCP Developer Experience

> **Hackathon Submission**: *Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ Track)*  
> **Bonus Category**: Official Friction Log Submission (+10% Judging Bonus)  
> **Project**: Janus (ElderSync) — Self-Hosted FastMCP Server for Alexa+  
> **Date**: October 20, 2026  

---

## Executive Summary
During the development of **Janus (ElderSync)**, our team implemented a self-hosted Model Context Protocol (MCP) server adhering to spec `2025-11-25` over Streamable HTTP, integrating with a custom Alexa+ Web Simulator and Echo Show visual card renderer. While the MCP paradigm dramatically simplifies tool registration, we encountered four distinct developer friction points across tooling discovery, local simulation gating, tunneling protocols, and browser CORS negotiation.

---

## Detailed Friction Log Entries

### Entry #1: Gated Developer Preview Access for Alexa+ & Lack of Local Test Containers
* **Task Attempted**:
  Deploying and testing our custom MCP server directly against the native Alexa+ developer preview runtime and Echo Show device simulators.
* **Steps Taken**:
  1. Followed official Amazon Developer documentation to register our custom MCP tool endpoint.
  2. Attempted to initialize the developer preview CLI (`alexa-ai`) and connect local smart display previewers.
* **Expected Result**:
  An open developer sandbox CLI or a local Docker container emulating the Alexa+ host agent runtime, allowing developers to execute end-to-end voice turns and inspect MCP tool invocations locally.
* **Actual Result**:
  The native developer preview tools (`alexa-ai`) and direct device simulator access were restricted to select enterprise preview partners, requiring custom whitelisting.
* **Severity**: High (Blocks native on-device verification for indie hackathon builders).
* **Workaround Used**:
  Developed a standalone HTML5/JS **Alexa+ Web Simulator** (`simulator/index.html`) implementing the official Streamable HTTP client contract, Web Speech API for voice interactions, and responsive Echo Show visual card viewports.
* **Actionable Suggestion for Amazon / FastMCP Team**:
  Publish a public, un-gated local developer emulator (e.g. `npx @alexa-developer/local-host` or a pre-configured Docker image) that mocks Alexa+ speech recognition, intent routing, and Echo Show visual rendering against any localhost MCP server.

---

### Entry #2: `@modelcontextprotocol/inspector` Defaulting to Legacy SSE Transport
* **Task Attempted**:
  Validating tool schemas (`tools/list`) and running interactive test calls (`tools/call`) using the official MCP Inspector.
* **Steps Taken**:
  Ran the standard inspector command:
  ```bash
  npx @modelcontextprotocol/inspector
  ```
  Attempted to connect to `http://localhost:8000/sse`.
* **Expected Result**:
  Seamless connection to the FastMCP server, listing our 4 non-clinical care tools (`log_daily_routine`, `get_caregiver_summary`, `verify_routine_state`, `flag_missed_routine`).
* **Actual Result**:
  The inspector failed to connect, displaying socket timeout errors. Default CLI arguments and web UI dropdowns in older versions of the inspector defaulted strictly to legacy Server-Sent Events (`/sse`) or `stdio`, whereas modern FastMCP v2 uses Streamable HTTP (`POST /mcp`, spec `2025-11-25`).
* **Severity**: Medium (Confusing onboarding experience for new MCP developers).
* **Workaround Used**:
  Configured the Inspector connection settings manually to use "Streamable HTTP" transport, setting the endpoint explicitly to `http://127.0.0.1:8000/mcp` and passing custom header `MCP-Protocol-Version: 2025-11-25`.
* **Actionable Suggestion for MCP Maintainers**:
  Update the Inspector CLI to detect endpoint protocols automatically and default newly scaffolded inspector sessions to Streamable HTTP (`/mcp`) in line with spec `2025-11-25`.

---

### Entry #3: Cloudflare Quick Tunnel SSE Buffering & Connection Drops
* **Task Attempted**:
  Exposing the local FastMCP server to remote cloud endpoints and mobile testers via temporary public ingress using Cloudflare Quick Tunnels (`cloudflared tunnel --url http://localhost:8000`).
* **Steps Taken**:
  Attempted to stream long-lived Server-Sent Events over the public tunnel.
* **Expected Result**:
  Stable bidirectional streaming of tool notifications and prompt responses.
* **Actual Result**:
  Cloudflare Quick Tunnels buffered HTTP chunks, delayed packet flushes, and dropped idle SSE streams after 100 seconds without keepalive pings.
* **Severity**: Medium (High impact on remote testing stability).
* **Workaround Used**:
  Transitioned entirely to FastMCP v2's **Streamable HTTP** transport over standard HTTP POST requests (`POST /mcp`). Because each tool call is a stateless HTTP transaction completed in $< 20\text{ ms}$, tunnel buffering and connection drops were completely eliminated.
* **Actionable Suggestion**:
  Document tunneling best practices in the Alexa+ MCP starter guide, recommending stateless Streamable HTTP over SSE for public tunneling tools (Cloudflare, ngrok).

---

### Entry #4: Browser CORS `Mcp-Session-Id` Header Redaction
* **Task Attempted**:
  Executing tool calls directly from our browser-based Web Simulator to `http://127.0.0.1:8000/mcp`.
* **Steps Taken**:
  Sent standard fetch requests from `http://localhost:3000` or local file origin to the FastAPI FastMCP endpoint.
* **Expected Result**:
  Full access to response headers, including session identifiers returned by FastMCP.
* **Actual Result**:
  Browser security policies blocked client JavaScript from reading the `Mcp-Session-Id` response header because FastAPI's default CORS middleware did not expose it.
* **Severity**: Low (Easily fixed once diagnosed, but consumes debugging time).
* **Workaround Used**:
  Added explicit CORS middleware in `src/janus/server.py`:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
      expose_headers=["Mcp-Session-Id", "MCP-Protocol-Version"]
  )
  ```
* **Actionable Suggestion**:
  Include `expose_headers=["Mcp-Session-Id"]` by default in FastMCP's built-in FastAPI mounting helpers.
