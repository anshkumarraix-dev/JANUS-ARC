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
- [x] **Core 1.8**: Implement true two-step proposal gate in `src/janus/storage.py` and `server.py` (`proposals` table, injectable clock, category validation, atomic single-writer commit).
- [x] **Core 1.9**: Implement schedule slot windows (`routine_schedule` table, senior `tz` IANA, +/- 30m grace completion, statuses `upcoming|due|completed|overdue`, `scan_missed_routines` escalation ladder, deduplication, and dynamic DB names).

---

## 🖥️ Phase 2: Web Simulator & Echo Show Visual Card Renderer
- [x] **Sim 2.1**: Design and build `simulator/index.html` with dual split-screen view: Echo Show 8 (768x480) senior smart screen + off-site caregiver dashboard (zero external CDN/font calls, 100% system fonts).
- [x] **Sim 2.2**: Implement local deterministic keyword router (<5ms routing, zero external API costs) with `pendingTx` state machine, "yes/confirm" gating, and clarifying fallback prompt.
- [x] **Sim 2.3**: Integrate Web Speech API (`webkitSpeechRecognition` & `speechSynthesis`) for voice conversation with typed text fallback.
- [x] **Sim 2.4**: Connect simulator to `POST http://127.0.0.1:8000/mcp` with Bearer auth token input and dual-metric latency HUD (Router ms + HTTP RTT ms).
- [x] **Sim 2.5**: Off-site caregiver dashboard with 3s auto-sync polling loop and live green sync pulse indicator on confirmed events.
- [x] **Sim 2.6**: Interactive "Try to break it" refusal test row demonstrating server-side invariants (unconfirmed commit refusal, expired ID, wrong senior, clinical scope violation).
- [x] **Sim 2.7**: Comprehensive manual demonstration script and verification guide in [`docs/DEMO.md`](docs/DEMO.md).

---

## 🧪 Phase 3: Contract Testing & Latency Benchmarks
- [x] **Test 3.1**: Write automated pytest suite in `tests/test_janus.py` covering all 4 MCP tools with `pytest` and `httpx`.
- [x] **Test 3.2**: Validate confirmation gate: assert zero database writes when `confirm=False`.
- [x] **Test 3.3**: Validate database mutation commit when `confirm=True`.
- [x] **Test 3.4**: Run latency benchmark: assert local execution $< 100\text{ ms}$ (p95) and round-trip $< 500\text{ ms}$ (Achieved: 10.84 ms avg, 13.28 ms p95).
- [x] **Test 3.5**: Validate Streamable HTTP tool discovery (`tools/list`) and invocation (`tools/call`) per MCP spec `2025-11-25`.
- [x] **Test 3.6**: Add `tests/test_gate.py` covering no-preview commit rejection, expired proposals, replay idempotency, 0-write invariant, non-clinical category enum rejection, and thread concurrency.
- [x] **Test 3.7**: Add `tests/test_schedule.py` covering schedule slot isolation (breakfast doesn't clear dinner, morning water doesn't clear afternoon slot), IST timezone boundary, alert dedupe, and unconfirmed events isolation.
- [x] **Test 3.8**: Add contract tests per tool verifying published `outputSchema` and validating response conformance using `jsonschema.validate`.
- [x] **Test 3.9**: Add real-network latency test in `tests/test_real_network_latency.py`: starts uvicorn in an independent OS subprocess on an ephemeral port, executes 50 HTTP POST calls per tool via `httpx`, asserts p95 < 100ms per call, and prints evaluation table (zero TestClient).
- [x] **Test 3.10**: Non-clinical wording sanitization: eradicate all clinical phrases ("vitals normal") across tests and schemas.
- [x] **Test 3.11**: Add `pytest --cov` targeting `gate`, `auth`, and `audit` modules, achieving 97% total coverage (auth: 100%, gate: 98%, audit: 93%).

---

## 🚀 Phase 4: Submission & Human Checkpoints
- [x] **Doc 4.1**: Finalize documentation and verify all cross-links across `docs/` and root files.
- [x] **Rel 4.2**: 3-command reviewer quickstart scripts (`scripts/smoke.sh`, `scripts/smoke.ps1`) probing `/health` and MCP `tools/list`.
- [x] **CI 4.3**: GitHub Actions CI workflow on Python 3.12 (`.github/workflows/ci.yml`).
- [x] **Doc 4.4**: Rewrite README with only test-proven claims, accurate SDK names, quickstart, architecture diagram, and explicit known limitations.
- [HUMAN] **Checkpoint 4.5**: Record a 2.5-minute video demonstration covering:
  - Senior ambient voice logging of hydration/meal.
  - Caregiver visual summary card on simulated Echo Show.
  - Caregiver two-step shift handoff with confirmation gate.
- [HUMAN] **Checkpoint 4.6**: Upload demonstration video to YouTube / Vimeo and copy public link.
- [HUMAN] **Checkpoint 4.7**: Push clean repository to public GitHub with MIT License.
- [HUMAN] **Checkpoint 4.8**: Submit project on Devpost with `FRICTION_LOG.md` (+10% bonus) and `PRODUCT_FEEDBACK.md`.
