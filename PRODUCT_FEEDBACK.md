# PRODUCT FEEDBACK QUESTIONNAIRE — Alexa+ & FastMCP

> **Hackathon Submission**: *Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ Track)*  
> **Project**: Janus (ElderSync) — Self-Hosted FastMCP Server for Non-Clinical Caregiving  
> **Date**: October 20, 2026  

---

### 1. Which developer tools, APIs, and SDKs did you use and for what?
* **FastMCP Python SDK (v2, `mcp>=1.30.0`)**: Used to construct the self-hosted Model Context Protocol server exposing typed non-clinical eldercare tools (`log_daily_routine`, `get_caregiver_summary`, `verify_routine_state`, `flag_missed_routine`).
* **FastAPI & Uvicorn**: Used to serve the FastMCP app over Streamable HTTP (`POST /mcp`, spec `2025-11-25`) with CORS support and sub-15ms local response times.
* **Pydantic (v2)**: Enforced strict schema validation and typing for input parameters, proposal previews, and Echo Show visual card payloads.
* **SQLite (Standard Library)**: Local persistent data store with atomic transactions for daily routine event logs and caregiver shift handoffs.
* **Web Speech API (`SpeechRecognition` & `SpeechSynthesis`)**: Simulated ambient voice input and audio feedback on Echo Show viewports.
* **Google Antigravity & Pytest**: Employed for automated contract testing, benchmark generation, and architectural consistency verification.

---

### 2. What worked well?
* **Decorator-Driven Tool Registration**: FastMCP's `@mcp.tool()` decorator made defining schemas, parameter documentation, and async handlers exceptionally fast. Type annotations automatically generated compliant JSON schemas for tool discovery.
* **Stateless Streamable HTTP**: Migrating to Streamable HTTP (`POST /mcp`) was a breakthrough. It completely bypassed the connection fragility of legacy SSE streams and easily met Alexa's strict $< 500\text{ ms}$ round-trip latency requirement.
* **Two-Step Confirmation Architecture**: Designing safety gates (`confirm: bool = False`) for state-mutating actions provided an intuitive, human-centered safety model that fits natural voice interaction (*"Do you confirm handing off to Sarah?"* -> *"Yes, confirm"*).

---

### 3. What needs work?
* **Developer Preview Onboarding**: Gating native Alexa+ developer preview tools to select enterprise partners creates friction for hackathon builders. An open, un-gated local CLI or Docker container emulating the Alexa+ host agent is urgently needed.
* **Starter Kit Protocol Alignment**: Starter kits and inspector tools should immediately point developers to Streamable HTTP (`POST /mcp`) rather than older SSE or stdio patterns.
* **Smart Display Visual Templates**: Providing official, pre-tested CSS / JSON display templates for Echo Show 8, 10, and 15 visual cards in the MCP starter kit would dramatically accelerate frontend parity.

---

### 4. How was your onboarding experience?
* **Speed to First Tool**: Onboarding with FastMCP v2 was smooth. Writing our first typed tool handler took less than 15 minutes.
* **Documentation Clarity**: The core MCP specification is clean, but examples illustrating how to handle confirmation gates and custom visual display card payloads in voice hosts are sparse. Once we established our two-step pattern, development accelerated rapidly.

---

### 5. Would you build with these devices and services again?
* **Yes, absolutely.** The Model Context Protocol provides an elegant abstraction that completely decouples model reasoning from backend business logic. Combining ambient voice smart displays (Echo Show) with local, deterministic FastMCP servers represents the future of trustworthy, non-intrusive ambient computing in eldercare.
