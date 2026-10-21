# Janus (ElderSync) — Deployment & Infrastructure Guide

This guide details deployment procedures for **Janus (ElderSync)** across containerized Docker environments, Cloudflare tunnels, and third-party container hosts.

---

## 📋 Table of Contents
1. [Deployment Architecture](#1-deployment-architecture)
2. [Docker Deployment](#2-docker-deployment)
   - [Building the Image](#building-the-image)
   - [Running with `docker run`](#running-with-docker-run)
   - [Running with `docker compose`](#running-with-docker-compose)
   - [Container Healthcheck & Verification](#container-healthcheck--verification)
3. [Cloudflare Quick-Tunnels](#3-cloudflare-quick-tunnels)
   - [Automated Tunnel Script](#automated-tunnel-script)
   - [Critical Caveat: Ephemeral URL Lifecycle](#critical-caveat-ephemeral-url-lifecycle)
   - [Permanent Named Tunnels for Production](#permanent-named-tunnels-for-production)
4. [Evaluating Free Container Hosts](#4-evaluating-free-container-hosts)
   - [Candidate Platforms](#candidate-platforms)
   - [Verification Checklist (Do Not Assume Pricing or Availability)](#verification-checklist-do-not-assume-pricing-or-availability)

---

## 1. Deployment Architecture

```mermaid
flowchart TD
    subgraph Clients ["Voice & Web Clients"]
        AlexaVoice["Alexa+ Device / Echo Show"]
        BrowserSim["Web Simulator / Caregiver Dashboard"]
    end

    subgraph Tunnel ["Ingress Layer"]
        CF["Cloudflare Edge (HTTPS)\n*.trycloudflare.com OR Custom Domain"]
    end

    subgraph Container ["Janus Docker Container"]
        Server["Starlette / Uvicorn (:8000)\nNon-Root appuser (UID 10001)"]
        HealthCheck["Healthcheck Probe\nGET /health every 30s"]
    end

    subgraph Storage ["Persistent Volume"]
        Vol[("Named Volume: janus-data\nMounted at /app/data\nSQLite WAL + Audit Log")]
    end

    AlexaVoice <-->|HTTPS JSON-RPC 2.0| CF
    BrowserSim <-->|HTTPS Polling 3s| CF
    CF <-->|Reverse Proxy /mcp| Server
    Server --> Vol
    HealthCheck -.->|Probes| Server
```

---

## 2. Docker Deployment

The Janus server includes a production-ready, security-hardened `Dockerfile` built on `python:3.12-slim`:
* **Non-Root Execution**: Runs under a dedicated `appuser` (UID 10001, GID 10001).
* **Automated Healthcheck**: Periodic probe executing `curl -f http://localhost:8000/health`.
* **Isolated Data Mount**: Stores SQLite state at `/app/data/janus.db`.

### Building the Image
From the repository root:
```bash
docker build -t janus-mcp:latest .
```

### Running with `docker run`
To run Janus as a background container with a named persistent volume:
```bash
# 1. Create a named volume for SQLite persistence
docker volume create janus-db-data

# 2. Run container
docker run -d \
  --name janus-server \
  -p 8000:8000 \
  -v janus-db-data:/app/data \
  --restart unless-stopped \
  janus-mcp:latest
```

### Running with `docker compose`
A complete `docker-compose.yml` is provided at the workspace root:

```yaml
services:
  janus:
    build:
      context: .
      dockerfile: Dockerfile
    image: janus-mcp:latest
    container_name: janus-server
    ports:
      - "8000:8000"
    environment:
      - JANUS_HOST=0.0.0.0
      - JANUS_PORT=8000
      - JANUS_DB_PATH=/app/data/janus.db
      - JANUS_LOG_LEVEL=info
    volumes:
      - janus-data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 5s

volumes:
  janus-data:
    name: janus-db-data
```

**Commands:**
```bash
# Start container in detached mode
docker compose up -d

# Inspect health status and logs
docker compose ps
docker compose logs -f

# Stop container while preserving SQLite database volume
docker compose down
```

### Container Healthcheck & Verification
Once started, verify that the container is healthy:
```bash
# Probe health endpoint
curl -s http://127.0.0.1:8000/health

# Expected response:
# {"status":"healthy","service":"janus-mcp","version":"0.1.0","protocol":"2025-11-25"}
```

---

## 3. Cloudflare Quick-Tunnels

Alexa+ requires a publicly reachable, TLS-secured endpoint (`https://...`). Cloudflare quick-tunnels allow exposing local and containerized instances without public IP addresses or router port forwarding.

### Automated Tunnel Script
Run the helper script while Janus is running on port 8000:

* **Linux / macOS / Git Bash**:
  ```bash
  bash scripts/tunnel.sh
  ```
* **Windows PowerShell**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts/tunnel.ps1
  ```

The script monitors `cloudflared`, extracts the public HTTPS URL, and prints the exact JSON configuration to paste into `.agents/mcp_config.json`:
```json
{
  "mcpServers": {
    "janus": {
      "serverUrl": "https://<random-subdomain>.trycloudflare.com/mcp"
    }
  }
}
```

### Critical Caveat: Ephemeral URL Lifecycle
> [!WARNING]
> **Ephemeral URL Invalidation on Restart**: Quick-tunnels (`cloudflared tunnel --url`) are designed exclusively for development and testing. They generate an unauthenticated `*.trycloudflare.com` domain that **changes on every single process restart or network reconnection**.
>
> If the tunnel process terminates, computer sleeps, or connection resets:
> 1. The old URL immediately returns HTTP 404 / connection refused.
> 2. Any active `.agents/mcp_config.json`, Alexa Developer Console Skill Endpoint, or remote Caregiver Dashboard configured with the old URL will immediately break.
> 3. You must re-run the script and paste the newly generated URL into your configuration.

### Permanent Named Tunnels for Production
For a persistent public URL that survives restarts:
1. Register a domain on Cloudflare.
2. Create a named tunnel: `cloudflared tunnel create janus-prod`.
3. Route DNS: `cloudflared tunnel route dns janus-prod janus.yourdomain.com`.
4. Run the tunnel service: `cloudflared tunnel run janus-prod`.

---

## 4. Evaluating Free Container Hosts

If deploying beyond a local machine or edge gateway, several cloud platforms offer container hosting with free-tier or trial credits.

### Candidate Platforms
* **Render**: Free web services with custom Dockerfiles.
* **Fly.io**: Micro-VMs running Docker containers close to users.
* **Railway**: Trial credit-based container deployment.
* **Koyeb**: Free-tier micro apps deployed via Docker.
* **Hugging Face Spaces (Docker)**: Free 2-vCPU Docker hosting.
* **Oracle Cloud Always Free**: 2 AMD compute VMs or 4 ARM Ampere cores with perpetual free tier.

---

### Verification Checklist (Do Not Assume Pricing or Availability)

> [!IMPORTANT]
> **Cloud Provider Terms Evolve Continuously**: Never assume pricing tiers, free allowances, or feature availability remain unchanged. Before selecting any container hosting provider for Janus, you **MUST manually verify** the following 6 technical constraints:

#### 1. Cold-Start Sleep & Inactivity Scale-to-Zero
* **What to verify**: Does the provider shut down or sleep free containers after 15–30 minutes of inactivity?
* **Why it matters for Janus**: Alexa+ has a strict round-trip voice latency budget ($< 500\text{ ms}$). If an elder speaks to Alexa and the underlying container must cold-start from disk (often taking 20 to 60 seconds on free platforms), Alexa will immediately timeout and state: *"There was a problem communicating with the requested skill."*
* **Verification action**: Check whether continuous background execution or custom healthcheck pings are permitted without violation of terms of service.

#### 2. Persistent Storage (Volume) Support
* **What to verify**: Does the free tier include persistent volume mounts, or is the container filesystem ephemeral?
* **Why it matters for Janus**: Janus persists routine timelines, shift handoffs, schedule windows, and cryptographic SHA-256 audit logs inside SQLite (`data/janus.db`). On an ephemeral filesystem, every automatic redeploy, restart, or host migration **permanently destroys all senior wellness history and audit records**.
* **Verification action**: Confirm that the provider allows mounting a persistent storage volume (at least 1 GB) attached to `/app/data` under the free tier.

#### 3. Streamable HTTP / Chunked Transfer Proxying
* **What to verify**: Does the provider's reverse proxy / load balancer support HTTP streaming (chunked transfer encoding) without buffering?
* **Why it matters for Janus**: Janus implements FastMCP over Streamable HTTP (`MCP spec 2025-11-25`). Proxies that aggressively buffer HTTP responses or terminate connections after 30 seconds of inactivity will disrupt client MCP sessions.
* **Verification action**: Review provider documentation regarding HTTP streaming and long-lived HTTP connections.

#### 4. Automated HTTPS / TLS Termination
* **What to verify**: Does the platform provide free, automatic SSL/TLS termination with valid CA certificates on the public endpoint?
* **Why it matters for Janus**: Both the Alexa+ Skill service and browser Web Speech APIs (used in the Web Simulator) strictly refuse non-HTTPS or self-signed endpoints.
* **Verification action**: Ensure the public URL provided by the host uses a valid HTTPS certificate recognized by major trust stores.

#### 5. Bandwidth & Background Polling Quotas
* **What to verify**: What are the monthly inbound/outbound bandwidth and request quotas?
* **Why it matters for Janus**: The off-site Caregiver Dashboard in `simulator/index.html` polls `get_caregiver_summary` every 3 seconds while active ($~28{,}800$ requests per 24 hours of dashboard monitoring).
* **Verification action**: Calculate total monthly requests ($28{,}800 \times 30 \approx 864{,}000$ requests/month) against provider rate limits and free bandwidth quotas.

#### 6. Perpetual Free Tier vs. Expiring Promotional Credits
* **What to verify**: Is the account tier a perpetual free allocation (e.g. Always Free compute) or a promotional credit grant that expires after 30–90 days?
* **Why it matters for Janus**: Expiring credits result in unexpected service termination, leaving seniors without voice routine logging.
* **Verification action**: Confirm the expiration date and renewal rules for the account tier before long-term caregiver deployment.
