# ElderSync / Janus — System Architecture & Design (DESIGN.md)

## 1. System Overview
**Janus (ElderSync)** is a self-hosted, voice-first Model Context Protocol (MCP) server for Alexa+, built using Python 3.12, FastMCP v2, and FastAPI. It enables ambient, hands-free routine logging for seniors and seamless shift handoffs between family caregivers on Echo Show smart screens.

---

## 2. Architecture Diagram

```mermaid
flowchart TD
    subgraph Host ["Host Layer (Alexa+ / Echo Show / Web Simulator)"]
        Voice["Senior / Caregiver Spoken Voice"] --> STT["Speech-to-Text / Keyword Router"]
        STT --> HostReq["MCP Client / Host"]
        CardRenderer["Echo Show Visual Card Renderer"]
    end

    subgraph Transport ["Streamable HTTP Transport (MCP Spec 2025-11-25)"]
        HostReq -->|POST /mcp\nStateless JSON-RPC| ServerEndpoint["FastAPI / FastMCP v2 (/mcp)"]
        ServerEndpoint -->|JSON Response + Visual Card Payload| CardRenderer
    end

    subgraph MCPCore ["Janus Core Engine (src/janus/)"]
        ServerEndpoint --> SchemaVal["Pydantic v2 Schema Validation"]
        SchemaVal --> GateCheck{"Is Write Tool?"}
        GateCheck -->|No (Read)| ReadExecutor["Read Query Handler"]
        GateCheck -->|Yes & confirm=false| ProposalGen["Proposal Preview Generator (No DB Write)"]
        GateCheck -->|Yes & confirm=true| WriteExecutor["Write Transaction Handler"]
    end

    subgraph Storage ["Persistence Layer (SQLite)"]
        ReadExecutor -->|SELECT| SQLiteDB[("SQLite Database\nroutine_logs\nshift_handoffs")]
        WriteExecutor -->|INSERT / UPDATE\nAtomic Transaction| SQLiteDB
    end
```

---

## 3. SQLite Data Flow & Database Schemas

All persistence is managed locally with zero third-party cloud dependencies via SQLite (`src/janus/storage.py`), guaranteeing $< 10\text{ ms}$ local query execution.

### Table: `routine_logs`
Records non-clinical daily living events (meal, hydration, vitamins, activity, wellness).

| Column | Type | Description |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Unique event identifier |
| `senior_id` | `TEXT NOT NULL` | Target senior profile identifier (e.g., `margaret_01`) |
| `routine_type` | `TEXT NOT NULL` | Enum: `meal`, `hydration`, `vitamins`, `activity`, `wellness` |
| `value` | `TEXT` | Quantity or description (e.g., `500ml water`, `Oatmeal & fruit`) |
| `logged_by` | `TEXT NOT NULL` | Actor identifier (`senior_voice`, `caregiver_sarah`, `caregiver_david`) |
| `timestamp` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | UTC ISO8601 timestamp |
| `notes` | `TEXT` | Optional caregiver context or observation |

### Table: `shift_handoffs`
Maintains an append-only, auditable ledger of shift handovers between family caregivers.

| Column | Type | Description |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Unique handoff event identifier |
| `senior_id` | `TEXT NOT NULL` | Senior profile identifier |
| `departing_caregiver` | `TEXT NOT NULL` | Caregiver ending shift |
| `incoming_caregiver` | `TEXT NOT NULL` | Caregiver assuming shift |
| `routine_snapshot` | `TEXT NOT NULL` | JSON snapshot of routine status at handoff time |
| `handoff_notes` | `TEXT NOT NULL` | Crucial non-clinical notes (e.g., *Margaret completed 20 mins activity, took afternoon water*) |
| `confirmed` | `BOOLEAN NOT NULL DEFAULT 1` | Confirmed status indicator |
| `created_at` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | Timestamp of confirmed handoff |

### Write Data Flow with Confirmation Gate
1. **Initial Trigger**: User speaks: *"Alexa, record morning caregiver shift handoff to Sarah."*
2. **Step 1 (Preview Proposal)**: Host invokes `verify_routine_state(senior_id="margaret_01", incoming="Sarah", confirm=False)`.
   - Tool inspects SQLite database for today's logs.
   - Generates a proposal preview summarizing pending routine items.
   - Pending proposals are assigned a unique transaction ID valid for 5 minutes (`PROPOSAL_TTL_SECONDS = 300`).
   - Database is untouched (`writes = 0`).
   - Alexa speaks: *"Margaret had breakfast and vitamins, but has only had 300ml of water. Do you confirm handing off to Sarah?"*
3. **Step 2 (Host Voice Consent)**: Caregiver responds: *"Yes, confirm."*
4. **Step 3 (Commit)**: Host invokes `verify_routine_state(..., confirm=True)`.
   - Tool writes atomic transaction to `shift_handoffs`.
   - Emits Echo Show Visual Card payload and audio confirmation.

---

## 4. Four Core MCP Tools Specification

All tools are implemented using FastMCP v2 with typed Pydantic v2 request/response models (publishing full `inputSchema` and `outputSchema`), explicit `ToolAnnotations`, and LLM decision-making prompts.

| Tool Name | Annotations | Return Type | Confirmation Gate |
|---|---|---|---|
| `log_daily_routine` | `readOnlyHint=False`, `idempotentHint=False`, `destructiveHint=False` | `RoutineProposalPreview` / `RoutineLogProposalResponse` | Step 1 creates proposal (`confirm=False`), Step 2 commits via `verify_routine_state` |
| `get_caregiver_summary` | `readOnlyHint=True`, `idempotentHint=True`, `destructiveHint=False` | `CaregiverSummaryResponse` | Read-only (0 writes) |
| `verify_routine_state` | `readOnlyHint=False`, `idempotentHint=True`, `destructiveHint=False` | `ProposalPreviewResponse` / `CommittedStateResponse` / `AlreadyCommittedResponse` / `ProposalErrorResponse` | Strict two-step proposal gate (0 writes until `confirm=True`) |
| `flag_missed_routine` | `readOnlyHint=False`, `idempotentHint=True`, `destructiveHint=False` | `MissedRoutineResponse` | Writes alert history record |

---

## 5. MCP Resources

Janus exposes standard MCP read-only resources over Streamable HTTP:

### Resource: `janus://senior/{id}/today`
- **MIME Type**: `application/json`
- **Description**: Real-time read-only daily wellness timeline, schedule completion status, and visual card payload for senior `{id}`.
- **Protocol Method**: `resources/read` and `resources/templates/list`.

---

## 6. Structured Error Handling

Janus uses stable, machine-readable error codes mapped to human-safe messages via `src/janus/errors.py`:

| Error Code | HTTP / Response Context | Description |
|---|---|---|
| `INVALID_CATEGORY` | Tool validation | Requested category not in allowed non-clinical enum (`meal`, `hydration`, `vitamins`, `activity`, `wellness`) |
| `PROPOSAL_NOT_FOUND` | `verify_routine_state` | Transaction ID does not exist in `proposals` table |
| `PROPOSAL_EXPIRED` | `verify_routine_state` | Proposal passed 5-minute validity TTL |
| `PROPOSAL_CANCELLED` | `verify_routine_state` | User actively cancelled pending proposal |
| `MISSING_TRANSACTION_ID` | `verify_routine_state` | `confirm=True` called without specifying `transaction_id` |
| `INVALID_ARGUMENTS` | Tool invocation | Missing or malformed parameters |
| `FORBIDDEN` | Access control | Unauthorized senior profile access |
| `INTERNAL_ERROR` | System failure | Storage or unexpected runtime error |

---

## 7. Non-Clinical Care Boundaries & Safety

Janus operates under strict non-clinical safety boundaries designed to prevent medical liability and ensure caregiver safety:

1. **Explicit Scope Permitted**:
   * Hydration tracking (glasses, ounces, water intake reminders).
   * Meal tracking (breakfast, lunch, dinner, snacks).
   * Routine daily vitamin logging (confirming scheduled vitamins were taken).
   * Physical activity and wellness routines (chair stretches, light movement, steps).
   * Caregiver check-in logs and shift changeover notes.
2. **Prohibited Medical Features**:
   * 🚫 No prescription drug dosage changes, titrations, or scheduling.
   * 🚫 No vital signs triage (blood pressure, heart rate, blood glucose clinical evaluation).
   * 🚫 No diagnostic interpretations or clinical recommendations.
3. **Known Limitations**:
   * Janus is not an emergency or medical system and does not detect emergencies.

---

## 8. Multimodal Visual Architecture: Alexa Presentation Language (APL 2024.3)

Janus implements official **Alexa Presentation Language (APL specification version `2024.3`)** documents and structured datasources, replacing invented card structures with production-grade multimodal interfaces for Echo Show smart displays.

### Design Principles for Senior Glanceability
- **Form Factor**: Echo Show 8 Landscape viewport (`1280x800 dp`).
- **Arm's-Length Glanceability**: All visual cards are strictly limited to **at most 3 top-level visual elements**:
  1. *Header Banner*: Senior identity, context label, and status badge.
  2. *Hero Status Frame*: High-contrast category icon, large primary metric, or prominent status text.
  3. *Ambient Voice Prompt Footer*: Clear, high-contrast action guidance (e.g. *"Say: 'Alexa, confirm' to commit"*).
- **Senior Readability Constraint**: Every text component enforces **`fontSize >= 24dp`** (24pt to 48dp) with high-contrast color pairings (`#F9FAFB` on `#0B0F19` dark canvas).

### Four Core APL Documents & Authoring Tool Assets
Every document is saved to `docs/apl/` as standalone JSON ready for import into the Alexa Developer Console APL Authoring Tool:

| Card Type | APL Document | Datasource Payload | Tool Trigger |
|---|---|---|---|
| **Routine Proposal Preview** | `docs/apl/routine_preview.json` | `docs/apl/routine_preview_datasource.json` | `log_daily_routine` (confirm=False) |
| **Caregiver Wellness Timeline** | `docs/apl/caregiver_summary.json` | `docs/apl/caregiver_summary_datasource.json` | `get_caregiver_summary` |
| **Shift Handoff Confirmation** | `docs/apl/handoff_confirm.json` | `docs/apl/handoff_confirm_datasource.json` | `verify_routine_state` (preview & committed) |
| **Gentle Missed Routine Reminder** | `docs/apl/missed_routine.json` | `docs/apl/missed_routine_datasource.json` | `flag_missed_routine` |

### Headless & Non-APL Fallback
Every tool return model provides a parallel `display` property:
```json
{
  "display": {
    "title": "Proposed: Hydration",
    "lines": [
      "Margaret Vance (margaret_01)",
      "500ml water completed",
      "Say 'Alexa, confirm' to commit"
    ]
  }
}
```
Non-screen hosts, audio-only Echo dots, and third-party MCP clients parse the `display` fallback without needing an APL rendering engine.

### Verification Notice
APL contract tests (`tests/test_apl.py`) validate JSON syntax, top-level APL 2024.3 properties, typography constraints (24pt+ text), and complete data-binding resolution (`${payload.XYZ}`). Testing verifies document schema and datasource binding contracts, and does not claim physical device execution.


