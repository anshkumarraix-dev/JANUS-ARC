# ElderSync / Janus — Live Task Tracker (TASKS.md)

This document tracks all implementation, testing, and submission milestones for **Janus (ElderSync)** for the *Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ Track)*.

**Legend**:
- `[x]` Completed
- `[/]` In Progress
- `[ ]` Pending
- `[HUMAN]` Human Checkpoint / Action Required

---

## 🏗️ Phase 0: Workspace Rules & Documentation Framework
- [x] **Setup 0.1**: Scaffold repository configuration files (`AGENTS.md`, `.agents/mcp_config.json`, `requirements.txt`, `LICENSE`).
- [x] **Setup 0.2**: Create canonical domain terminology reference in [`docs/GLOSSARY.md`](docs/GLOSSARY.md).
- [x] **Setup 0.3**: Detail system architecture, SQLite data flow, and tool schemas in [`docs/DESIGN.md`](docs/DESIGN.md).
- [x] **Setup 0.4**: Establish phased build roadmap in [`docs/PLAN.md`](docs/PLAN.md).
- [x] **Setup 0.5**: Record architecture decisions (ADR-001, ADR-002, ADR-003) in [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md).
- [x] **Setup 0.6**: Document platform constraints (<500ms latency, Cloudflare tunnels) in [`docs/LEARNINGS.md`](docs/LEARNINGS.md).
- [x] **Setup 0.7**: Pre-fill submission documents ([`README.md`](README.md), [`FRICTION_LOG.md`](FRICTION_LOG.md), [`PRODUCT_FEEDBACK.md`](PRODUCT_FEEDBACK.md)).
- [x] **Setup 0.8**: Initialize persistent append-only change audit log in [`CHANGELOG.md`](CHANGELOG.md).

---

## ⚙️ Phase 1: Core FastMCP v2 Server & Storage Engine
- [x] **Core 1.1**: Implement local SQLite storage engine in `src/janus/storage.py` with `seniors`, `routine_logs`, and `shift_handoffs` tables.
- [x] **Core 1.2**: Define Pydantic v2 schemas for all 4 MCP tools (`routine.py`, `handoff.py`).
- [x] **Core 1.3**: Implement tool `log_daily_routine` with confirmation gate and Echo Show card payload.
- [x] **Core 1.4**: Implement tool `get_caregiver_summary` with daily aggregation and Echo Show visual card payload.
- [x] **Core 1.5**: Implement tool `verify_routine_state` with two-step proposal preview and commit flow.
- [x] **Core 1.6**: Implement tool `flag_missed_routine` for passive routine check-in window monitoring.
- [x] **Core 1.7**: Mount FastMCP v2 server over Streamable HTTP (`MCP spec 2025-11-25`) at `http://127.0.0.1:8000/mcp` in `src/janus/server.py`.

---

## 🖥️ Phase 2: Web Simulator & Echo Show Visual Card Renderer
- [x] **Sim 2.1**: Design and build `simulator/index.html` with 768x480px Echo Show card viewport (arm's length dark theme).
- [x] **Sim 2.2**: Implement local deterministic keyword router (<5ms routing, zero external API costs).
- [x] **Sim 2.3**: Integrate Web Speech API (`webkitSpeechRecognition` & `speechSynthesis`) for voice conversation.
- [x] **Sim 2.4**: Add typed text input fallback to bypass iframe `Origin: null` restrictions.
- [x] **Sim 2.5**: Connect simulator to `POST http://127.0.0.1:8000/mcp` and render real-time visual cards.

---

## 🧪 Phase 3: Contract Testing & Latency Benchmarks
- [x] **Test 3.1**: Write automated pytest suite in `tests/test_janus.py` covering all 4 MCP tools with `pytest` and `httpx`.
- [x] **Test 3.2**: Validate confirmation gate: assert zero database writes when `confirm=False`.
- [x] **Test 3.3**: Validate database mutation commit when `confirm=True`.
- [x] **Test 3.4**: Run latency benchmark: assert local execution $< 100\text{ ms}$ (p95) and round-trip $< 500\text{ ms}$ (Achieved: 10.84 ms avg, 13.28 ms p95).
- [x] **Test 3.5**: Validate Streamable HTTP tool discovery (`tools/list`) and invocation (`tools/call`) per MCP spec `2025-11-25`.

---

## 🚀 Phase 4: Submission & Human Checkpoints
- [x] **Doc 4.1**: Finalize documentation and verify all cross-links across `docs/` and root files.
- [HUMAN] **Checkpoint 4.2**: Record a 2.5-minute video demonstration covering:
  - Senior ambient voice logging of hydration/meal.
  - Caregiver visual summary card on simulated Echo Show.
  - Caregiver two-step shift handoff with confirmation gate.
- [HUMAN] **Checkpoint 4.3**: Upload demonstration video to YouTube / Vimeo and copy public link.
- [HUMAN] **Checkpoint 4.4**: Push clean repository to public GitHub with MIT License.
- [HUMAN] **Checkpoint 4.5**: Submit project on Devpost with `FRICTION_LOG.md` (+10% bonus) and `PRODUCT_FEEDBACK.md`.
