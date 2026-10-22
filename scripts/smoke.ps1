# scripts/smoke.ps1 -- End-to-end smoke test for Janus (ElderSync) FastMCP Server (PowerShell)
$ErrorActionPreference = "Stop"

Write-Host "===================================================================" -ForegroundColor Cyan
Write-Host "Janus (ElderSync) -- 3-Command Reviewer Smoke Test (PowerShell)" -ForegroundColor Cyan
Write-Host "===================================================================" -ForegroundColor Cyan

# 1. Determine Python executable
$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    $pythonExe = (Get-Command py -ErrorAction SilentlyContinue).Source
}
if (-not $pythonExe) {
    Write-Error "Python is not installed or not in PATH."
    exit 1
}

$pyVer = & $pythonExe --version
Write-Host "[1/6] Using Python: $pyVer" -ForegroundColor Green

# 2. Create fresh virtual environment
$smokeVenv = ".smoke_venv"
Write-Host "[2/6] Creating fresh virtual environment at $smokeVenv..." -ForegroundColor Green
if (Test-Path $smokeVenv) {
    Remove-Item -Recurse -Force $smokeVenv
}
& $pythonExe -m venv $smokeVenv

$venvPython = Join-Path $smokeVenv "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Could not find python.exe in $smokeVenv"
    exit 1
}

# 3. Install project in editable mode with dev dependencies
Write-Host '[3/6] Installing dependencies...' -ForegroundColor Green
& $venvPython -m pip install --quiet -e ".[dev]"

# 4. Run pytest suite
Write-Host '[4/6] Running pytest suite...' -ForegroundColor Green
& $venvPython -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pytest suite failed."
    exit $LASTEXITCODE
}

# 5. Start Janus FastMCP server in background
$port = if ($env:JANUS_PORT) { $env:JANUS_PORT } else { "8000" }
$hostName = if ($env:JANUS_HOST) { $env:JANUS_HOST } else { "127.0.0.1" }
$env:JANUS_PORT = $port
$env:JANUS_HOST = $hostName
$env:JANUS_LOG_LEVEL = "warning"
$env:JANUS_DEMO_MODE = "1"

Write-Host "[5/6] Starting Janus server in background on http://${hostName}:${port}..." -ForegroundColor Green
$serverProc = Start-Process -FilePath $venvPython -ArgumentList "-m janus.server" -PassThru -NoNewWindow

try {
    # Wait for server readiness
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $resp = Invoke-RestMethod -Uri "http://${hostName}:${port}/health" -Method Get -TimeoutSec 1 -ErrorAction SilentlyContinue
            if ($resp.status -eq "healthy") {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $ready) {
        Write-Error "Server failed to respond on http://${hostName}:${port}/health within 15 seconds."
        exit 1
    }

    # 6. Verify /health and MCP tools/list
    Write-Host "[6/6] Probing endpoints..." -ForegroundColor Green

    Write-Host "-> Probing GET http://${hostName}:${port}/health" -ForegroundColor Yellow
    $health = Invoke-RestMethod -Uri "http://${hostName}:${port}/health" -Method Get
    $healthJson = $health | ConvertTo-Json -Compress
    Write-Host "   Response: $healthJson"
    if ($health.status -ne "healthy") {
        Write-Error "/health did not return healthy status."
        exit 1
    }

    Write-Host "-> Probing POST http://${hostName}:${port}/mcp (tools/list)" -ForegroundColor Yellow
    $body = @{
        jsonrpc = "2.0"
        id = 1
        method = "tools/list"
        params = @{}
    } | ConvertTo-Json

    $headers = @{
        "Content-Type" = "application/json"
        "Accept" = "application/json, text/event-stream"
        "MCP-Protocol-Version" = "2025-11-25"
        "Authorization" = "Bearer janus-demo-caregiver-sarah"
    }

    $toolsResp = Invoke-RestMethod -Uri "http://${hostName}:${port}/mcp" -Method Post -Body $body -Headers $headers
    $toolNames = $toolsResp.result.tools | ForEach-Object { $_.name }

    $expectedTools = @("log_daily_routine", "get_caregiver_summary", "verify_routine_state", "flag_missed_routine")
    foreach ($tool in $expectedTools) {
        if ($toolNames -notcontains $tool) {
            Write-Error "Expected tool '$tool' not found in tools/list response."
            exit 1
        }
        Write-Host "   [OK] Found tool: $tool" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "===================================================================" -ForegroundColor Cyan
    Write-Host "SMOKE TEST PASSED! All endpoints, contracts, and tests succeeded." -ForegroundColor Cyan
    Write-Host "===================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "To activate this virtual environment and run Janus in PowerShell:" -ForegroundColor White
    Write-Host ""
    Write-Host "  .smoke_venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "  `$env:JANUS_DEMO_MODE = '1'" -ForegroundColor Yellow
    Write-Host "  python -m janus.server" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Then open simulator/index.html in your browser." -ForegroundColor White
    Write-Host "===================================================================" -ForegroundColor Cyan
}
finally {
    if ($serverProc -and -not $serverProc.HasExited) {
        Write-Host 'Stopping Janus server process...' -ForegroundColor Gray
        Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue
    }
}
