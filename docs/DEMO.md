# Janus (ElderSync) — Interactive Demonstration Script & Evaluation Guide (`docs/DEMO.md`)

This guide provides the exact step-by-step evaluation and video demonstration script for **Janus (ElderSync)** on the **Alexa+ Echo Show 8 & Off-Site Caregiver Split-Screen Simulator** (`simulator/index.html`).

---

## 🎯 Demonstration Objective
Demonstrate the core value proposition of Janus:
1. **Ambient Non-Clinical Senior Routine Logging**: Senior speaks naturally to an Echo Show 8 smart screen in high-contrast glanceable cards (APL 2024.3, 24pt+ text).
2. **Mandatory Safety Confirmation Gate**: State changes are strictly read-only proposals (`0 database writes`) until confirmed verbally or via button tap.
3. **Real-Time Remote Caregiver Visibility**: An off-site family caregiver dashboard automatically syncs every 3 seconds, flashing green whenever a confirmed event is written.
4. **Server-Side Safety Invariants**: Proving server refusals against unconfirmed commits, expired IDs, and clinical triage violations.
5. **Sub-5ms Local Router & Low-Latency HTTP**: Dual-number latency HUD displaying honest local intent resolution ($<5\text{ ms}$) alongside real Streamable HTTP round-trip latency.

---

## ⚙️ Pre-Demo Setup

### 1. Launch FastMCP v2 Server
Open a terminal in the project root and start the server with demo mode enabled:
```bash
# On Linux / macOS / Git Bash:
export JANUS_DEMO_MODE=1
python -m janus.server

# On Windows PowerShell:
$env:JANUS_DEMO_MODE = "1"
python -m janus.server
```
*Expected log output*:
```
Starting Janus FastMCP v2 server on http://0.0.0.0:8000/mcp ...
INFO: Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 2. Open the Simulator
Open `simulator/index.html` in your modern web browser (Google Chrome, Microsoft Edge, or Firefox):
```bash
# Or open directly from file explorer:
file:///C:/Users/Lenovo/Downloads/JANUS%20ARC/simulator/index.html
```
*Verify initial state*:
- **Top Header**: Server Online indicator (green pulse dot).
- **Latency HUD**: Router: `0.00 ms`, HTTP RTT: `<20 ms`.
- **Left Panel**: Echo Show 8 (768×480 viewport) showing Margaret Vance's Daily Care Timeline.
- **Right Panel**: Off-site Caregiver Dashboard showing 8 routine slot windows and active polling (every 3 seconds).

---

## 🎬 Step-by-Step Demonstration Script

### Scene 1: Senior Ambient Routine Proposal (Two-Step Safety Gate)
* **Goal**: Show that speaking a routine generates a proposal preview with **0 database writes**.

1. **Senior Utterance**: Speak into microphone or click the chip:
   > **Utterance**: `"I drank 2 glasses of water"`
2. **Echo Show Display (Left)**:
   - Amber card appears: **`🛡️ Proposed: HYDRATION`**
   - High-contrast text: `"I drank 2 glasses of water"`
   - Badge: **`Proposal Preview (0 Writes)`**
   - Transaction ID displayed: e.g. `tx_...`
   - Alexa voice & speech bubble:
     > *"I have a pending note to record hydration (I drank 2 glasses of water) for Margaret Vance. Would you like me to confirm and record this?"*
3. **Caregiver Dashboard (Right)**:
   - Notice: **0 writes have occurred**. The caregiver hydration counter remains unchanged. The pending routine is safely gated.
4. **Latency HUD**:
   - Router: `< 1.00 ms` (Local keyword resolution)
   - HTTP RTT: `~12 ms`

---

### Scene 2: Confirmation & Real-Time Caregiver Synchronization
* **Goal**: Show that confirming writes **1 record to SQLite**, and the off-site caregiver dashboard instantly reflects it.

1. **Senior Utterance**: Speak into microphone, type, or click the chip:
   > **Utterance**: `"yes"` *(or click "✅ Confirm ("Yes")" button)*
2. **Echo Show Display (Left)**:
   - Green card appears: **`✅ Routine Recorded`**
   - Badge: **`Committed (1 Write)`**
   - Result ID: `#1`
   - Alexa voice:
     > *"Hydration routine has been verified and recorded."*
3. **Caregiver Dashboard (Right)**:
   - Within 3 seconds (or instantly upon commit), the Caregiver Portal:
     - **Flashes Green Border** (`sync-flash` animation).
     - Banner appears: **`⚡ Live Update Synced from Echo Show!`**
     - **Hydration Metric increments** (e.g. from `0` to `1`).
     - Activity Feed displays: **`💧 HYDRATION: I drank 2 glasses of water [senior_voice] [Time]`**.
     - Morning Hydration slot marks as **`COMPLETED`**.

---

### Scene 3: Accidental Confirmation with No Pending Proposal
* **Goal**: Show that the router refuses to commit when nothing is waiting.

1. **Senior Utterance**:
   > **Utterance**: `"confirm"`
2. **Expected Behavior**:
   - Router instantly intercepts in `< 0.5 ms` with `pendingTx === null`.
   - **No network call** is dispatched.
   - Alexa speaks and displays:
     > *"There's nothing waiting for confirmation."*
   - Echo Show displays an informative card confirming 0 state changes.

---

### Scene 4: Cancellation Flow
* **Goal**: Show that saying "no" or "cancel" immediately dismisses a proposal without touching storage.

1. **Senior Utterance**:
   > **Utterance**: `"Finished morning oatmeal and tea"`
   *(Generates amber Meal Proposal Preview)*
2. **Senior Utterance**:
   > **Utterance**: `"no"` *(or `"cancel"`)*
3. **Expected Behavior**:
   - Pending transaction is cleared from memory.
   - Echo Show returns to clean timeline.
   - Alexa speaks:
     > *"Action cancelled. Nothing was written."*
   - Caregiver Dashboard shows 0 new meal events.

---

### Scene 5: Caregiver Shift Handoff
* **Goal**: Show shift changeover between David and Sarah with routine snapshot.

1. **Caregiver Utterance**:
   > **Utterance**: `"Hand off shift"` *(or click chip "🤝 Shift Handoff (Preview)")*
2. **Echo Show Display (Left)**:
   - Amber Proposal Card: **`Shift Handoff Proposal`**
   - Details: *"Shift handoff proposal: David -> Sarah. Pending items: 7."*
   - Alexa voice:
     > *"Margaret Vance currently has 7 pending routine items... Do you confirm handing off care from David to Sarah...?"*
3. **Caregiver Confirmation**:
   > **Utterance**: `"yes, confirm"`
4. **Echo Show Display (Left)**:
   - Green Card: **`✅ Shift Handoff Confirmed`**
   - Alexa speaks:
     > *"Caregiver shift handoff from David to Sarah has been verified and recorded."*
5. **Caregiver Dashboard (Right)**:
   - Active Care Shift updates from **David** to **Sarah**.
   - Sync flash pulses green.

---

### Scene 6: "Try to Break It" — Server-Side Safety Invariant Refusals
* **Goal**: Visually prove that the server refuses invalid mutations, expired IDs, and clinical triage.

| Test Button | Action Dispatched | Expected Server Refusal | Screen Feedback |
| :--- | :--- | :--- | :--- |
| **1. Confirm With No Preview** | `verify_routine_state(confirm=True, transaction_id="")` | `ErrorCode.MISSING_TRANSACTION_ID` | Red/amber refusal banner: *"confirm=True REQUIRES a valid transaction_id of a live pending proposal."* |
| **2. Expired / Invalid TX ID** | `verify_routine_state(confirm=True, transaction_id="tx_expired_demo_99999")` | `ErrorCode.PROPOSAL_NOT_FOUND` | Red/amber refusal banner: *"Proposal 'tx_expired_demo_99999' was not found or has expired."* |
| **3. Unknown Senior ID** | `get_caregiver_summary(senior_id="unknown_senior_999")` | Handled gracefully | Returns 0 events and empty schedule without crashing. |
| **4. Clinical Scope Violation** | `log_daily_routine(category="chemotherapy_prescription")` | `ErrorCode.INVALID_CATEGORY` | Red refusal banner: *"Janus is strictly non-clinical. Category 'chemotherapy_prescription' is prohibited."* |

---

## 📊 Summary of Demonstration Evidence

| Requirement | Proof in Simulator | Invariant Verified |
| :--- | :--- | :--- |
| **Vanilla JS & System Fonts** | `simulator/index.html` contains zero CDN links, zero Google Fonts, 100% system fonts. | Zero external network calls at runtime. |
| **Echo Show 8 (768×480)** | Strictly sized 768×480px viewport with 24pt+ high-contrast typography. | Seniors glance from arm's length. |
| **Real-time Caregiver Sync** | Right panel polls `get_caregiver_summary` every 3s and flashes green on new events. | Real-time family peace of mind. |
| **Two-Step Confirmation Gate** | Amber proposal preview (0 writes) $\to$ Green committed state (1 write). | Prevents accidental voice logging. |
| **Separate Latency HUD** | Router latency ($<1\text{ ms}$) and HTTP RTT ($<25\text{ ms}$) clearly separated. | Sub-500ms round-trip budget met. |
