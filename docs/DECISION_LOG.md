# ElderSync / Janus — Architecture Decision Records (DECISION_LOG.md)

This log records significant architectural, technical, and design decisions made for **Janus (ElderSync)** for the *Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ Track)*.

---

### ADR-001: FastMCP v2 over Streamable HTTP Transport
* **Status**: Accepted
* **Date**: 2026-10-20
* **Context**:
  The Alexa+ hackathon track requires MCP server integration adhering to MCP specification version `2025-11-25`. Previous MCP iterations predominantly utilized either `stdio` pipes (local CLI only) or Server-Sent Events (SSE) long-lived HTTP streams. In voice assistant and cloud gateway topologies, long-lived SSE connections suffer from connection drops, gateway timeouts, and tunnel incompatibilities (e.g., Cloudflare Quick Tunnels).
* **Decision**:
  Implement FastMCP v2 (`mcp>=1.30.0`) mounted on FastAPI using **Streamable HTTP** over `POST /mcp` in stateless JSON-RPC mode.
* **Consequences & Rationale**:
  - **Stateless Efficiency**: Eliminates connection-pool starvation and persistent connection overhead on smart speakers.
  - **Latency Advantage**: Stateless HTTP POST calls complete in $< 15\text{ ms}$ locally, well within Alexa's $< 500\text{ ms}$ round-trip budget.
  - **Tool Discovery & Execution**: Allows the host to query `tools/list` and `tools/call` over standard HTTP requests without bidirectional streaming complexity.

---

### ADR-002: Local Deterministic Keyword Router in Web Simulator
* **Status**: Accepted
* **Date**: 2026-10-20
* **Context**:
  The Web Simulator (`simulator/index.html`) requires an intent-resolution layer to convert senior voice utterances and caregiver commands into structured MCP tool payloads (`tools/call`). Relying on cloud LLM APIs (e.g., OpenAI or Claude API keys) introduces financial costs, network latency, token limits, and nondeterminism during live video demonstrations.
* **Decision**:
  Implement a local, deterministic keyword and regex intent router directly in JavaScript inside the Web Simulator, with an optional transparent bypass for custom JSON-RPC calls.
* **Consequences & Rationale**:
  - **Sub-5ms Resolution**: Intent matching occurs instantly in the client runtime without external network calls.
  - **Zero Cost & Free-Tier Strictness**: Honors hackathon rule to avoid paid API dependencies.
  - **Reproducibility**: Guarantees 100% deterministic, glitch-free execution during evaluation and demonstration video recording.
  - **Clean Fallback**: Provides clear conversational prompts when an utterance does not match non-clinical domain keywords.

---

### ADR-003: Read-Only Preview Before Confirmation Gate for State Writes
* **Status**: Accepted
* **Date**: 2026-10-20
* **Context**:
  In home care environments, accidental writes or voice misrecognitions can corrupt caregiver records (e.g., falsely recording that a senior took medication or completing an accidental shift handoff). Furthermore, safety guidelines mandate that voice agents should not commit sensitive or state-mutating changes without clear user awareness.
* **Decision**:
  Enforce a mandatory two-step confirmation gate on all state-mutating MCP tools:
  ```python
  @mcp.tool()
  async def verify_routine_state(
      senior_id: str,
      departing_caregiver: str,
      incoming_caregiver: str,
      handoff_notes: str,
      confirm: bool = False
  ) -> RoutineStateResponse:
  ```
  When `confirm=False`, the tool executes zero database writes and returns a structured *Read-Only Proposal Preview* highlighting current status and asking for confirmation. Only when `confirm=True` does the tool write the transaction to SQLite.
* **Consequences & Rationale**:
  - **Safety & Auditability**: Completely eliminates unintended database mutations caused by ambient voice triggers.
  - **Voice UX Alignment**: Mirrors Alexa's natural conversational confirmation pattern: *"I found 1 uncompleted routine item. Do you confirm handing off to Sarah?"* -> *"Yes, confirm."*
  - **Testability**: Automated tests can cleanly assert that `confirm=False` leaves the database row count unchanged.
