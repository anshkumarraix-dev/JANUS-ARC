# JANUS-ARC — Project Glossary (GLOSSARY.md)

This glossary defines the canonical domain terminology for **JANUS-ARC**, a self-hosted Model Context Protocol (MCP) server for Alexa+ built for the *Build, Ship, Shape: Amazon Developer Hackathon*. All developers, documentation, and AI coding agents must use these exact terms and definitions.

---

## Canonical Domain Terms

### 1. Senior Household Member
An aging individual living at home (e.g., Margaret) who interacts with Alexa+ primarily via ambient voice to log daily non-clinical wellness routines without touching screens.

### 2. Shift Handoff
The formal synchronization and operational transfer of caregiving responsibility between caregivers (family members, visiting relatives, or aides). Requires an explicit, auditable state check and caregiver confirmation before recording handoff notes in the persistent ledger.

### 3. Confirmation Gate
A mandatory two-step safety design pattern enforced across all state-mutating MCP write tools (`confirm: bool = False`). When `confirm=False`, the tool executes zero database writes and returns a human-readable *Read-Only Proposal Preview*. The server commits changes to the database only when the host explicitly re-invokes the tool with `confirm=True` following user verbal or touch consent.

### 4. Streamable HTTP
The standardized HTTP transport mechanism defined in MCP spec version `2025-11-25` operating over `POST /mcp`. It replaces legacy server-sent events (SSE) and stdio transports for web-accessible voice assistants, providing high-performance, stateless JSON-RPC request-response cycles with sub-100 ms local execution.

### 5. Web Simulator
A lightweight browser-based web application (`simulator/index.html`) running HTML5, CSS3, and JavaScript that mimics the Alexa+ smart screen host environment. It features Web Speech API integration, visual Echo Show card rendering, a deterministic keyword router, and direct `POST /mcp` tool execution.

---

## Auxiliary Domain Terms

* **Family Caregiver**: Off-site relatives or adult children (e.g., David, Sarah) who monitor daily routine timelines and review handoff summaries on smart displays or mobile devices.
* **Visiting Caregiver**: An in-person family member or home helper present on-site executing shift check-ins, routine verification, and handoff closures.
* **Non-Clinical Routine**: Daily lifestyle and wellness actions conforming strictly to the five supported categories (`meal`, `hydration`, `vitamins`, `activity`, `wellness`) explicitly bounded away from medical diagnosis, clinical triage, or prescription changes.
* **Echo Show Visual Card**: A glanceable visual UI payload returned within tool results designed for arm's-length viewing on 8-inch and 15-inch smart display viewports.
* **Read-Only Proposal Preview**: The structured response emitted by a confirmation-gated write tool when `confirm=False`, summarizing proposed mutations, affected records, and a human confirmation prompt.
