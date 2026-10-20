# Janus (ElderSync) — Non-Clinical Caregiver Synchronization for Alexa+

[![Build, Ship, Shape: Amazon Developer Hackathon](https://img.shields.io/badge/Hackathon-Amazon%20Developer%20Alexa%2B%20Track-FF9900?logo=amazon&logoColor=white)](https://buildshipshape.devpost.com/)
[![MCP Spec](https://img.shields.io/badge/MCP%20Spec-2025--11--25-blue)](https://spec.modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Janus (ElderSync)** is a self-hosted Model Context Protocol (MCP) server for Alexa+ running over **FastMCP v2** and **Streamable HTTP**. It bridges the gap between aging seniors living independently and their distributed family caregivers by providing hands-free ambient voice logging on Echo devices, glanceable visual timeline cards for Echo Show smart screens, and auditable two-step confirmation shift handoffs.

---

## 🌟 The Problem & The Janus Solution

* **The Problem**: Aging seniors struggle with tiny touchscreens, app passwords, and complex mobile menus to log basic daily wellness routines (hydration, meals, vitamins, fresh air walks). At the same time, adult children and family caregivers suffer from anxious, fragmented text threads wondering: *"Did Mom drink water this afternoon? Has someone walked with her yet?"*
* **The Janus Solution**: Janus turns any Alexa+ enabled device into an ambient, zero-touch routine assistant. Seniors speak naturally (*"Alexa, tell Janus I finished my morning oatmeal and took my vitamins"*), while off-site family caregivers receive real-time, glanceable Echo Show visual timeline cards. Caregivers transferring shifts execute safe, verified handoffs using voice-confirmed safety gates.

---

## 🏗️ Architecture Overview

```mermaid
flowchart LR
    subgraph Host ["Voice / Smart Screen Host"]
        User(["Senior / Caregiver"]) <-->|Ambient Voice| Alexa["Alexa+ / Web Simulator"]
        Alexa <-->|Echo Show Visual Card| Display["Smart Display Viewport"]
    end

    subgraph MCP ["Janus FastMCP Server (:8000/mcp)"]
        Alexa <-->|Streamable HTTP\nJSON-RPC 2.0| FastMCP["FastMCP v2 Engine\n(Python 3.12 / FastAPI)"]
        FastMCP --> Gate{"Confirmation\nGate"}
        Gate -->|confirm=False| Preview["Proposal Preview\n(0 Writes)"]
        Gate -->|confirm=True| Commit["Atomic Commit"]
    end

    subgraph Storage ["Local Storage"]
        Commit --> DB[("SQLite Database\nroutine_logs\nshift_handoffs")]
    end
```

### Key Technical Attributes
* **FastMCP v2 over Streamable HTTP**: Implements MCP specification `2025-11-25` over stateless `POST /mcp`, bypassing long-lived SSE tunnel connection drops and meeting Alexa's $< 500\text{ ms}$ round-trip latency limit.
* **Two-Step Confirmation Gate**: Write-heavy tools enforce `confirm: bool = False` by default. When unconfirmed, the server returns a read-only proposal preview. Database commits require explicit voice confirmation (`confirm=True`).
* **Non-Clinical Safety Boundary**: Strictly restricted to lifestyle, wellness, hydration, and caregiver handoffs. Excludes clinical diagnosis, vitals triage, or prescription drug administration.
* **Zero Paid APIs**: Operates 100% locally with open-source Python libraries and SQLite.

---

## 🛠️ The 4 Core MCP Tools

| Tool Name | Type | Description | Confirmation Gate | Local Latency |
|---|---|---|:---:|:---:|
| `log_daily_routine` | Write | Logs non-clinical wellness events (hydration, meals, vitamins, walks). | Yes (`confirm=False` preview) | $< 20\text{ ms}$ |
| `get_caregiver_summary` | Read | Aggregates daily logs into an Echo Show visual card timeline payload. | No (Read-only) | $< 15\text{ ms}$ |
| `verify_routine_state` | Write | Verifies pending tasks and executes caregiver shift handoffs. | Yes (`confirm=False` preview) | $< 25\text{ ms}$ |
| `flag_missed_routine` | Read | Scans scheduled daily check-in windows to spot missed routines. | No (Read-only) | $< 20\text{ ms}$ |

---

## 🚀 Quickstart & Installation

### 1. Prerequisites
* Python 3.12+
* Node.js (Optional, for MCP Inspector)

### 2. Clone and Install Dependencies
```bash
git clone https://github.com/<your-username>/janus-mcp.git
cd janus-mcp
pip install -r requirements.txt
```

### 3. Start the FastMCP Server
```bash
python src/janus/server.py
```
The server will bind to `http://127.0.0.1:8000/mcp` with Streamable HTTP enabled.

### 4. Launch the Alexa+ Web Simulator
Open `simulator/index.html` in your web browser:
* Test voice input via Web Speech API or use the typed text input bar.
* Click sample caregiver queries: *"Log 500ml water for Margaret"*, *"Show caregiver summary"*, or *"Record shift handoff"*.
* View real-time Echo Show visual card rendering.

---

## 🧪 Testing & Latency Benchmarks

Run the complete contract and latency test suite:
```bash
pytest tests/ -v
```
All tests validate:
1. Two-step confirmation gate invariants (zero writes on `confirm=False`).
2. Correct Pydantic schema validation for all 4 tools.
3. p95 local execution latency $< 100\text{ ms}$ (total round-trip $< 500\text{ ms}$).

---

## 📁 Repository Structure & Documentation

```
janus-mcp/
├── docs/
│   ├── GLOSSARY.md         # Canonical domain terminology
│   ├── DESIGN.md           # Architecture, SQLite schemas & tool specs
│   ├── PLAN.md             # 4-phase implementation roadmap
│   ├── DECISION_LOG.md     # Architecture Decision Records (ADR-001 to ADR-003)
│   └── LEARNINGS.md        # Technical platform constraints (<500ms latency, tunnels)
├── src/
│   └── janus/
│       ├── __init__.py
│       ├── server.py       # FastMCP server entrypoint (FastAPI /mcp)
│       ├── storage.py      # Local SQLite persistence engine
│       └── tools/          # Pydantic v2 tool schemas
│           ├── routine.py
│           └── handoff.py
├── simulator/              # Web-based Alexa+ smart screen simulator
│   ├── index.html
│   ├── app.js
│   └── style.css
├── tests/                  # Pytest contract & latency test suite
│   └── test_janus.py
├── .agents/                # AI Agent configurations
│   └── mcp_config.json
├── AGENTS.md               # AI development rules & safety boundaries
├── TASKS.md                # Live task tracker with checkable milestones
├── CHANGELOG.md            # Append-only change audit log
├── FRICTION_LOG.md         # Mandatory Devpost friction log (+10% bonus)
├── PRODUCT_FEEDBACK.md     # Product feedback questionnaire response
├── LICENSE                 # MIT License
├── requirements.txt        # Free open-source dependencies
└── README.md
```

---

## 🏆 Hackathon Submission Checklist

- [x] FastMCP v2 server over Streamable HTTP (`MCP spec 2025-11-25`)
- [x] 4 Core non-clinical MCP tools implemented with confirmation gate safety
- [x] Interactive Alexa+ Web Simulator with Echo Show visual cards
- [x] Pytest suite with sub-100 ms local latency verification
- [x] Mandatory [`FRICTION_LOG.md`](FRICTION_LOG.md) (+10% judging bonus)
- [x] Mandatory [`PRODUCT_FEEDBACK.md`](PRODUCT_FEEDBACK.md)
- [x] Standard [`LICENSE`](LICENSE) (MIT License) for public open-source submission
- [ ] 2.5-Minute Demonstration Video link added to Devpost
