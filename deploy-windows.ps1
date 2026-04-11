# ============================================================
# PBX Assistant — Windows Deploy Script (PowerShell)
# Run from the project root in PowerShell:
#   .\deploy-windows.ps1
#   .\deploy-windows.ps1 -Down
#   .\deploy-windows.ps1 -Logs
#   .\deploy-windows.ps1 -Pull
# ============================================================

param(
    [switch]$Down,
    [switch]$Logs,
    [switch]$Pull
)

$ComposeFile = "docker\docker-compose.windows.yml"
$EnvFile     = "agent\.env.windows"
$PjsipFile   = "asterisk\etc\asterisk\pjsip.conf"
$PjsipWin    = "asterisk\etc\asterisk\pjsip.windows.conf"

function Write-Step($msg) { Write-Host "[PBX] $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "[OK]  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!]   $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[ERR] $msg" -ForegroundColor Red }

# ── Flags ─────────────────────────────────────────────────────

if ($Down) {
    Write-Step "Stopping all containers..."
    docker compose -f $ComposeFile down
    Write-OK "Done."
    exit 0
}

if ($Logs) {
    docker compose -f $ComposeFile logs -f --tail=100
    exit 0
}

# ── Detect Windows host IP ─────────────────────────────────────

Write-Step "Detecting Windows host IP..."
$HostIP = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "172.*" } |
    Select-Object -First 1).IPAddress

if (-not $HostIP) {
    Write-Warn "Could not auto-detect host IP. Using 127.0.0.1 (Zoiper must run on same machine)."
    $HostIP = "127.0.0.1"
} else {
    Write-OK "Host IP: $HostIP"
}

# ── Patch pjsip.conf with Windows host IP ─────────────────────

Write-Step "Configuring Asterisk with host IP $HostIP..."
$pjsip = Get-Content $PjsipWin -Raw
$pjsip = $pjsip -replace "external_media_address=YOUR_WINDOWS_IP",  "external_media_address=$HostIP"
$pjsip = $pjsip -replace "external_signaling_address=YOUR_WINDOWS_IP", "external_signaling_address=$HostIP"
$pjsip | Set-Content $PjsipFile -NoNewline
Write-OK "pjsip.conf updated"

# ── Pre-flight checks ─────────────────────────────────────────

Write-Step "Checking Docker Desktop..."
try {
    docker info | Out-Null
    Write-OK "Docker is running"
} catch {
    Write-Err "Docker Desktop is not running. Start it and try again."
    exit 1
}

# ── .env check ───────────────────────────────────────────────

if (-not (Test-Path $EnvFile)) {
    Write-Err "Missing $EnvFile — this should already exist in the project."
    exit 1
}

# ── Pull Ollama model ──────────────────────────────────────────

if ($Pull) {
    Write-Step "Starting Ollama to pull model..."
    docker compose -f $ComposeFile up -d ollama
    Start-Sleep 5
    $model = (Select-String "OLLAMA_MODEL=" $EnvFile | Select-Object -First 1).Line -replace "OLLAMA_MODEL=",""
    Write-Step "Pulling model: $model (this may take a while...)"
    docker exec pbx-ollama ollama pull $model
}

# ── Build and start ────────────────────────────────────────────

Write-Step "Building containers..."
docker compose -f $ComposeFile build

Write-Step "Starting all services..."
docker compose -f $ComposeFile up -d

# ── Wait for services ─────────────────────────────────────────

Write-Step "Waiting for Asterisk..."
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    $result = docker exec pbx-asterisk asterisk -rx "core show version" 2>$null
    if ($result) { $ready = $true; break }
    Start-Sleep 3
    Write-Host "." -NoNewline
}
if ($ready) { Write-OK "Asterisk ready" } else { Write-Warn "Asterisk timeout — check: docker logs pbx-asterisk" }

Write-Step "Waiting for Ollama..."
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null
        $ready = $true; break
    } catch {}
    Start-Sleep 3
    Write-Host "." -NoNewline
}
if ($ready) { Write-OK "Ollama ready" } else { Write-Warn "Ollama timeout" }

# Check model is downloaded
$model = (Select-String "OLLAMA_MODEL=" $EnvFile | Select-Object -First 1).Line -replace "OLLAMA_MODEL=",""
$tags = (Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing).Content
if ($tags -notlike "*$model*") {
    Write-Warn "Model '$model' not found locally. Run: .\deploy-windows.ps1 -Pull"
}

Write-Step "Waiting for Agent..."
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
        $ready = $true; break
    } catch {}
    Start-Sleep 3
    Write-Host "." -NoNewline
}
if ($ready) { Write-OK "Agent ready" } else { Write-Warn "Agent timeout — check: docker logs pbx-agent" }

# ── Summary ────────────────────────────────────────────────────

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  PBX Assistant Running on Windows" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Dashboard   : http://localhost:3000" -ForegroundColor White
Write-Host "  Agent API   : http://localhost:8000" -ForegroundColor White
Write-Host "  ARI         : http://localhost:8088" -ForegroundColor White
Write-Host "  Ollama      : http://localhost:11434" -ForegroundColor White
Write-Host ""
Write-Host "  SIP Server  : $HostIP : 5060 / UDP" -ForegroundColor White
Write-Host "  Extensions  : 1001 (test1001)  1002 (test1002)  1003 (test1003)" -ForegroundColor White
Write-Host "  AI Number   : 9999" -ForegroundColor Green
Write-Host ""
Write-Host "Register Zoiper to $HostIP and dial 9999 to test." -ForegroundColor Cyan
Write-Host "See docs\zoiper-setup.md for step-by-step instructions." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Stop:  .\deploy-windows.ps1 -Down" -ForegroundColor Gray
Write-Host "  Logs:  .\deploy-windows.ps1 -Logs" -ForegroundColor Gray
