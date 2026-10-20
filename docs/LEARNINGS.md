# ElderSync / Janus — Project Learnings & Platform Constraints (LEARNINGS.md)

This append-only document captures critical technical discoveries, framework nuances, platform constraints, and operational workarounds encountered during the development of **Janus (ElderSync)** for the *Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ Track)*.

---

### Entry 001: Alexa+ Strict < 500 ms Round-Trip Latency Budget
* **Date**: 2026-10-20
* **Category**: Voice Agent Latency & Host Timing
* **Discovery**:
  Alexa+ voice interactions enforce a strict total round-trip latency ceiling of $< 500\text{ ms}$ from speech input completion to the initiation of voice/display response. If an external tool invocation exceeds this threshold, Alexa will time out or issue a generic failure prompt (*"Sorry, I'm having trouble accessing that skill right now"*).
* **Impact & Solution**:
  - All FastMCP tool executions must complete locally in $< 100\text{ ms}$ (p95 $< 30\text{ ms}$ achieved via SQLite indexes and in-process execution).
  - Heavy remote APIs, third-party network calls, and nested LLM reasoning loops inside tool execution are strictly prohibited.
  - All database queries run against an optimized local SQLite database (`storage.py`) with zero external network hops.

---

### Entry 002: Cloudflare Quick Tunnel Incompatibility with Server-Sent Events (SSE)
* **Date**: 2026-10-20
* **Category**: Network Ingress & Tunneling
* **Discovery**:
  When exposing local MCP servers to external hosts via temporary public tunnels (e.g. `cloudflared tunnel --url http://localhost:8000`), persistent Server-Sent Events (SSE) connections frequently drop or fail buffering flushes. Cloudflare Quick Tunnels cap concurrent connections and buffer chunked responses unless explicit headers are negotiated.
* **Impact & Solution**:
  - FastMCP v2's **Streamable HTTP** transport over `POST /mcp` operates statelessly using standard request-response JSON-RPC.
  - By using `POST /mcp` instead of long-lived SSE connections (`/sse`), the server bypasses tunnel buffering issues and works reliably behind Cloudflare, ngrok, and direct localhost proxies.

---

### Entry 003: Sandboxed Browser Viewport `Origin: null` Web Speech API Restrictions
* **Date**: 2026-10-20
* **Category**: Web Simulator & Browser Security
* **Discovery**:
  When the Web Simulator (`simulator/index.html`) is loaded inside sandboxed iframes or certain local environments (e.g., local preview widgets or file URI contexts), the browser sets `Origin: null`. Modern browsers (Chrome, Edge) strictly disable microphone access and the `webkitSpeechRecognition` API when `Origin: null` or when run in unprivileged frames.
* **Impact & Solution**:
  - The Web Simulator must never rely exclusively on voice input.
  - A dual-mode interface was implemented: full Web Speech API voice interaction when running on `http://localhost`, paired with a responsive, high-contrast typed text input bar and preset utterance buttons for one-click demo testing.

---

### Entry 004: FastMCP Protocol Version Header & CORS Session Negotiation
* **Date**: 2026-10-20
* **Category**: MCP Specification 2025-11-25
* **Discovery**:
  Clients communicating with FastMCP v2 over Streamable HTTP should provide the `MCP-Protocol-Version: 2025-11-25` header. Furthermore, when browser clients (such as the Web Simulator or Inspector) interact with the `/mcp` endpoint, the FastAPI server must expose the `Mcp-Session-Id` header via `Access-Control-Expose-Headers`.
* **Impact & Solution**:
  - FastAPI middleware was configured with explicit CORS headers (`Access-Control-Allow-Origin: *`, `Access-Control-Allow-Headers: *`, and `Access-Control-Expose-Headers: Mcp-Session-Id`).
  - `.agents/mcp_config.json` explicitly documents the server URL and protocol baseline.
