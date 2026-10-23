# scripts/tunnel.ps1 -- Quick-tunnel wrapper using Cloudflare Tunnels (cloudflared) for PowerShell
$ErrorActionPreference = "Stop"

$port = if ($env:JANUS_PORT) { $env:JANUS_PORT } else { "8000" }
$targetUrl = "http://127.0.0.1:$port"

Write-Host "===================================================================" -ForegroundColor Cyan
Write-Host "JANUS-ARC -- Cloudflare Quick-Tunnel Launcher (PowerShell)" -ForegroundColor Cyan
Write-Host "===================================================================" -ForegroundColor Cyan

# 1. Verify cloudflared installation
$cfExe = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cfExe) {
    Write-Host "ERROR: 'cloudflared' CLI tool is not installed or not in PATH." -ForegroundColor Red
    Write-Host ""
    Write-Host "To install cloudflared on Windows:"
    Write-Host "  winget install --id Cloudflare.cloudflared"
    Write-Host ""
    exit 1
}

Write-Host "Targeting local Janus server at: $targetUrl" -ForegroundColor Green
Write-Host ""
Write-Host "Starting Cloudflare quick-tunnel..." -ForegroundColor Yellow
Write-Host "NOTE: Ephemeral trycloudflare.com URLs change on every restart." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop the tunnel." -ForegroundColor Yellow
Write-Host "===================================================================" -ForegroundColor Cyan

$tempLog = [System.IO.Path]::GetTempFileName()
$tunnelProc = Start-Process -FilePath $cfExe -ArgumentList "tunnel --url $targetUrl" -RedirectStandardError $tempLog -PassThru -NoNewWindow

try {
    $url = ""
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Path $tempLog) {
            $content = Get-Content $tempLog -Raw -ErrorAction SilentlyContinue
            if ($content -match '(https://[-a-zA-Z0-9\.]+\.trycloudflare\.com)') {
                $url = $matches[1]
                break
            }
        }
    }

    if (-not $url) {
        Write-Error "Could not retrieve tunnel URL from cloudflared within 15 seconds."
        exit 1
    }

    Write-Host ""
    Write-Host "===================================================================" -ForegroundColor Green
    Write-Host "TUNNEL ESTABLISHED!" -ForegroundColor Green
    Write-Host "Public Base URL:   $url" -ForegroundColor Green
    Write-Host "Public MCP URL:    $url/mcp" -ForegroundColor Green
    Write-Host "Public Health URL: $url/health" -ForegroundColor Green
    Write-Host "===================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Paste the following into your .agents/mcp_config.json:" -ForegroundColor Cyan
    Write-Host ""
    $cfg = @{
        mcpServers = @{
            janus = @{
                serverUrl = "$url/mcp"
            }
        }
    }
    $cfgJson = $cfg | ConvertTo-Json -Depth 5
    Write-Host $cfgJson
    Write-Host ''
    Write-Host 'Tunnel is active. Keeping process alive (Ctrl+C to terminate)...' -ForegroundColor Yellow

    # Keep script open until process exits or user interrupts
    $tunnelProc.WaitForExit()
}
finally {
    if ($tunnelProc -and -not $tunnelProc.HasExited) {
        Write-Host 'Stopping cloudflared tunnel...' -ForegroundColor Gray
        Stop-Process -Id $tunnelProc.Id -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $tempLog) {
        Remove-Item -Force $tempLog -ErrorAction SilentlyContinue
    }
}
