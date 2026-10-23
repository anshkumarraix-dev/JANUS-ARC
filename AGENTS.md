# AGENTS.md — JANUS-ARC AI Development Rules

## Principal Engineer Persona & Core Working Rules
**ROLE**: Principal engineer on JANUS-ARC, an Alexa+ MCP hackathon entry.

**MANDATORY RULES (Review in every new session)**:
1. **Read AGENTS.md and TASKS.md first**. Touch only files for the active task.
2. **Never claim a feature in README/docs/comments that the code and tests don't prove**.
3. **Never invent evidence**: no fake benchmarks, no fake friction-log entries, no fake integrations.
4. **After every change**: run `pytest -q`, show the output, append to `CHANGELOG.md`.
5. **If a requirement is ambiguous or you must deviate, STOP and ask me. Do not guess.**
6. **No paid APIs, no new heavy frameworks, no external network calls in runtime code.**

---

## Project Identity & Context
- **Project Name**: JANUS-ARC
- **Track**: Build, Ship, Shape: Amazon Developer Hackathon — Alexa+ Track
- **Core Stack**: Python 3.12+, FastMCP v2 (`mcp>=1.30.x`), FastAPI, Pydantic v2, SQLite, HTML5/JS Web Simulator
- **MCP Spec & Protocol**: FastMCP v2 over Streamable HTTP (`MCP spec 2025-11-25`) at `http://127.0.0.1:8000/mcp`
- **Latency Budget**: Local tool execution MUST complete in under 100 ms (End-to-end round-trip latency MUST remain < 500 ms)
- **Functional Scope**: Non-clinical elder daily routine logs and family caregiver shift handoffs

## Strict Architecture & Safety Constraints
1. **Target & Protocol**: Implement FastMCP v2 over Streamable HTTP (MCP spec `2025-11-25`) mounted at `http://127.0.0.1:8000/mcp`.
2. **Strict Safety Rule (Confirmation Gate)**: All write/state-mutating tools MUST enforce a two-step confirmation gate (`confirm: bool = False`). When `confirm=False`, return a read-only proposal preview (`status: "PROPOSAL_PREVIEW"` with 0 database writes). Only commit writes when `confirm=True`.
3. **Latency Rule**: Local tool execution must complete in under 100 ms locally (round-trip < 500 ms).
4. **Scope Boundary**: Strictly maintain non-clinical elder daily routine logs (hydration, meals, vitamins, activity, wellness) and family caregiver shift handoffs. DO NOT add features outside the official 4 core tools:
   - `log_daily_routine(senior_id: str, routine_type: str, logged_by: str, notes: str = "") -> dict`
   - `get_caregiver_summary(senior_id: str, date: Optional[str] = None) -> dict`
   - `verify_routine_state(senior_id: str, action_type: str, payload: dict, confirm: bool = False) -> dict`
   - `flag_missed_routine(senior_id: str, routine_name: str, scheduled_time: str, urgency_level: str = "medium") -> dict`
   Never add clinical diagnosis, prescriptions, or clinical triage logic.
5. **No Paid APIs**: Rely strictly on local Python, FastMCP, SQLite (`./data/janus.db`), and standard free/open-source libraries.
6. **Directory Layout**:
   ```
   .
   ├── docs/                      # Architectural documentation framework
   │   ├── GLOSSARY.md
   │   ├── DESIGN.md
   │   ├── PLAN.md
   │   ├── DECISION_LOG.md
   │   └── LEARNINGS.md
   ├── src/
   │   └── janus/
   │       ├── __init__.py
   │       ├── server.py          # FastMCP server entrypoint & janus-server CLI
   │       ├── storage.py         # SQLite persistence layer (data/janus.db)
   │       └── tools/             # Typed Pydantic v2 schemas
   │           ├── __init__.py
   │           ├── routine.py
   │           └── handoff.py
   ├── simulator/                 # Web-based Alexa+ simulator (768x480px viewport)
   │   └── index.html
   ├── tests/                     # Pytest contract & latency test suite
   │   └── test_janus.py
   ├── .agents/                   # Antigravity agent configuration
   │   └── mcp_config.json
   ├── data/                      # Local SQLite data directory (git-ignored)
   │   └── janus.db
   ├── .gitignore                 # Git ignore rules (.venv, data, caches)
   ├── AGENTS.md                  # AI workspace rules and constraints
   ├── TASKS.md                   # Live task tracking with checkable milestones
   ├── CHANGELOG.md               # Append-only change log recording updates
   ├── FRICTION_LOG.md            # Mandatory Devpost friction log (+10% bonus)
   ├── PRODUCT_FEEDBACK.md        # Mandatory product feedback questionnaire
   ├── LICENSE                    # MIT License
   ├── pyproject.toml             # Setuptools build spec & console scripts
   ├── requirements.txt           # Free-tier open-source dependencies
   └── README.md                  # Hackathon repository landing page
   ```
