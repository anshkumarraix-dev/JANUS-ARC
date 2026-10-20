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
Records non-clinical daily living events (hydration, meals, vitamins, mobility, walks).

| Column | Type | Description |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Unique event identifier |
| `senior_id` | `TEXT NOT NULL` | Target senior profile identifier (e.g., `margaret_01`) |
| `routine_type` | `TEXT NOT NULL` | Enum: `hydration`, `meal`, `vitamins`, `mobility`, `walk`, `wellness` |
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
| `handoff_notes` | `TEXT NOT NULL` | Crucial non-clinical notes (e.g., *Margaret walked 20 mins, took afternoon water*) |
| `confirmed` | `BOOLEAN NOT NULL DEFAULT 1` | Confirmed status indicator |
| `created_at` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | Timestamp of confirmed handoff |

### Write Data Flow with Confirmation Gate
1. **Initial Trigger**: User speaks: *"Alexa, record morning caregiver shift handoff to Sarah."*
2. **Step 1 (Preview Proposal)**: Host invokes `verify_routine_state(senior_id="margaret_01", incoming="Sarah", confirm=False)`.
   - Tool inspects SQLite database for today's logs.
   - Generates a proposal preview summarizing pending routine items.
   - Database is untouched (`writes = 0`).
   - Alexa speaks: *"Margaret had breakfast and vitamins, but has only had 300ml of water. Do you confirm handing off to Sarah?"*
3. **Step 2 (Host Voice Consent)**: Caregiver responds: *"Yes, confirm."*
4. **Step 3 (Commit)**: Host invokes `verify_routine_state(..., confirm=True)`.
   - Tool writes atomic transaction to `shift_handoffs`.
   - Emits Echo Show Visual Card payload and audio confirmation.

---

## 4. Four Core MCP Tools Specification

### 1. `log_daily_routine`
* **Purpose**: Records a non-clinical wellness event for the senior household member.
* **Parameters**:
  * `senior_id` (`str`): Target senior identifier.
  * `routine_type` (`str`): `hydration` | `meal` | `vitamins` | `mobility` | `walk` | `wellness`.
  * `value` (`str`): Quantitative or qualitative description (e.g. `2 glasses water`).
  * `logged_by` (`str`, default: `"senior_voice"`): Name or voice profile of initiator.
  * `notes` (`Optional[str]`): Optional observation note.
  * `confirm` (`bool`, default: `False`): Two-step confirmation gate.
* **Return**: Confirmation status, logged entry ID, and visual card update.
* **Local Latency**: $< 20\text{ ms}$.

### 2. `get_caregiver_summary`
* **Purpose**: Read-only timeline aggregation summarizing all routine activities logged for a given day.
* **Parameters**:
  * `senior_id` (`str`): Senior profile identifier.
  * `date` (`Optional[str]`, default: today): Target date in `YYYY-MM-DD`.
* **Return**: Structured timeline object containing total hydration, meals logged, mobility events, and Echo Show visual timeline card schema.
* **Local Latency**: $< 15\text{ ms}$.

### 3. `verify_routine_state`
* **Purpose**: Inspects pending routine tasks and executes family caregiver shift handoffs.
* **Parameters**:
  * `senior_id` (`str`): Senior profile identifier.
  * `departing_caregiver` (`str`): Departing caregiver name.
  * `incoming_caregiver` (`str`): Incoming caregiver name.
  * `handoff_notes` (`str`): Shift notes.
  * `confirm` (`bool`, default: `False`): Confirmation gate flag.
* **Return**:
  * If `confirm=False`: Proposal preview with uncompleted routine checklist and confirmation prompt.
  * If `confirm=True`: Committed handoff confirmation, database record ID, and visual card.
* **Local Latency**: $< 25\text{ ms}$.

### 4. `flag_missed_routine`
* **Purpose**: Read-only evaluation tool scanning daily expectations against actual logs to identify missed check-in windows.
* **Parameters**:
  * `senior_id` (`str`): Senior profile identifier.
  * `as_of_time` (`Optional[str]`): Evaluation cutoff timestamp.
* **Return**: List of missed non-clinical routines (e.g., *Afternoon hydration check-in not logged by 2:00 PM*) and recommended conversational gentle reminder prompts for Alexa+.
* **Local Latency**: $< 20\text{ ms}$.

---

## 5. Non-Clinical Care Boundaries & Safety

Janus operates under strict non-clinical safety boundaries designed to prevent medical liability and ensure caregiver safety:

1. **Explicit Scope Permitted**:
   * Hydration tracking (glasses, ounces, water intake reminders).
   * Meal tracking (breakfast, lunch, dinner, snacks).
   * Routine daily vitamin logging (confirming scheduled vitamins were taken).
   * Physical mobility and gentle exercise (porch walks, chair stretches, steps).
   * Caregiver check-in logs and shift changeover notes.
2. **Prohibited Medical Features**:
   * 🚫 No prescription drug dosage changes, titrations, or scheduling.
   * 🚫 No vital signs triage (blood pressure, heart rate, blood glucose clinical evaluation).
   * 🚫 No diagnostic interpretations or clinical recommendations.
3. **Emergency Escalation Clause**:
   * If any utterance indicates acute pain, chest discomfort, falls, or medical emergency, the tool returns an immediate safety alert: *"Emergency detected: Please dial 911 or your local emergency number immediately."*
