$env:JANUS_DEMO_MODE = "1"
Write-Host "JANUS_DEMO_MODE set to $($env:JANUS_DEMO_MODE)"
.venv\Scripts\python.exe -m janus.server
