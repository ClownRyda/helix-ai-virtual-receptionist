#Requires -Version 5.1
<#
.SYNOPSIS
    Helix AI Virtual Receptionist — Windows First-Time Setup (Docker Desktop)

.DESCRIPTION
    Interactive onboarding wizard for Windows users running Helix AI via
    Docker Desktop. Prompts for all required configuration, writes agent/.env
    and Asterisk config files, then guides you through launching the stack.

.NOTES
    Run from the repository root:
        Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
        .\scripts\onboard-windows.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$EnvFile    = Join-Path $RepoRoot "agent\.env"
$EnvExample = Join-Path $RepoRoot "agent\.env.example"
$AriConf    = Join-Path $RepoRoot "asterisk\etc\asterisk\ari.conf"
$PjsipConf  = Join-Path $RepoRoot "asterisk\etc\asterisk\pjsip.conf"
$PjsipWin   = Join-Path $RepoRoot "asterisk\etc\asterisk\pjsip.windows.conf"

# ── Colors via Write-Host ─────────────────────────────────────────────────────
function Log   { param($msg) Write-Host "[✓] $msg" -ForegroundColor Green }
function Info  { param($msg) Write-Host "[→] $msg" -ForegroundColor Cyan }
function Warn  { param($msg) Write-Host "[!] $msg" -ForegroundColor Yellow }
function Err   { param($msg) Write-Host "[✗] $msg" -ForegroundColor Red }
function Header { param($msg) Write-Host "`n══════════════════════════════════════════════" -ForegroundColor Cyan; Write-Host "  $msg" -ForegroundColor Cyan; Write-Host "══════════════════════════════════════════════`n" -ForegroundColor Cyan }
function Section { param($msg) Write-Host "`n▸ $msg" -ForegroundColor White }

# ── Helper: prompt with optional default ─────────────────────────────────────
function Prompt-Value {
    param(
        [string]$PromptText,
        [string]$Default = "",
        [switch]$Secret
    )
    $display = if ($Default) { "${PromptText} [$Default]" } else { $PromptText }
    do {
        Write-Host "  $display`: " -NoNewline -ForegroundColor White
        if ($Secret) {
            $secure = Read-Host -AsSecureString
            $bstr   = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            $val    = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        } else {
            $val = Read-Host
        }
        if ([string]::IsNullOrWhiteSpace($val) -and $Default) { $val = $Default }
        if ([string]::IsNullOrWhiteSpace($val)) { Warn "This value is required." }
    } while ([string]::IsNullOrWhiteSpace($val))
    return $val
}

# ── Helper: yes/no prompt ─────────────────────────────────────────────────────
function Prompt-YN {
    param(
        [string]$PromptText,
        [string]$Default = "y"
    )
    do {
        Write-Host "  $PromptText [y/n, default: $Default]: " -NoNewline -ForegroundColor White
        $ans = Read-Host
        if ([string]::IsNullOrWhiteSpace($ans)) { $ans = $Default }
        $ans = $ans.ToLower()
    } while ($ans -notin @("y","n","yes","no"))
    return ($ans -in @("y","yes"))
}

# ── Helper: set or update a key in the .env file ─────────────────────────────
function Set-Env {
    param([string]$Key, [string]$Value)
    $content = Get-Content $EnvFile -Raw
    if ($content -match "(?m)^${Key}=") {
        $content = $content -replace "(?m)^${Key}=.*", "${Key}=${Value}"
    } else {
        $content += "`n${Key}=${Value}"
    }
    Set-Content -Path $EnvFile -Value $content -Encoding UTF8 -NoNewline
}

# ═════════════════════════════════════════════════════════════════════════════
# WELCOME
# ═════════════════════════════════════════════════════════════════════════════
Clear-Host
Write-Host ""
Write-Host @"
  ██╗  ██╗███████╗██╗     ██╗██╗  ██╗     █████╗ ██╗
  ██║  ██║██╔════╝██║     ██║╚██╗██╔╝    ██╔══██╗██║
  ███████║█████╗  ██║     ██║ ╚███╔╝     ███████║██║
  ██╔══██║██╔══╝  ██║     ██║ ██╔██╗     ██╔══██║██║
  ██║  ██║███████╗███████╗██║██╔╝ ██╗    ██║  ██║██║
  ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝
"@ -ForegroundColor Cyan
Write-Host "  Virtual Receptionist — Windows Setup (Docker Desktop)`n" -ForegroundColor White
Write-Host "  Press Enter to accept a default shown in [brackets].`n"
Warn "Note: No secrets or IP addresses are ever sent off-device."
Write-Host ""

# ── Pre-flight: Docker ────────────────────────────────────────────────────────
Header "Pre-flight: Docker Desktop"
try {
    $null = & docker version 2>&1
    Log "Docker Desktop is running"
} catch {
    Err "Docker is not running. Start Docker Desktop and re-run this script."
    exit 1
}
try {
    $null = & docker compose version 2>&1
    Log "Docker Compose v2 found"
} catch {
    Err "Docker Compose v2 not found. Update Docker Desktop."
    exit 1
}

# ═════════════════════════════════════════════════════════════════════════════
# STEP 1 — Business Identity
# ═════════════════════════════════════════════════════════════════════════════
Header "Step 1 of 7 — Business Identity"
Info "These values are spoken by the AI receptionist in every greeting."
Write-Host ""

$BusinessName     = Prompt-Value "Business name (spoken aloud)"  "My Business"
$AgentName        = Prompt-Value "Receptionist name"             "Alex"

Write-Host ""
Info "Timezone must be a valid tz database string."
Info "Examples: America/Chicago, America/New_York, America/Los_Angeles"
Write-Host ""
$BusinessTimezone = Prompt-Value "Timezone"        "America/Chicago"

Section "Business Hours"
Info "Use 24-hour integers (9 = 9 AM, 17 = 5 PM)."
Write-Host ""

do {
    $HoursStart = Prompt-Value "Business hours start (0-23)" "9"
} while (-not ($HoursStart -match '^\d+$') -or [int]$HoursStart -gt 23)

do {
    $HoursEnd = Prompt-Value "Business hours end (0-23)" "17"
} while (-not ($HoursEnd -match '^\d+$') -or [int]$HoursEnd -gt 23)

# ═════════════════════════════════════════════════════════════════════════════
# STEP 2 — Passwords
# ═════════════════════════════════════════════════════════════════════════════
Header "Step 2 of 7 — Passwords & Security"

Section "ARI Password"
Info "Secures the Asterisk REST Interface. Must match ari.conf."
Write-Host ""

do {
    $AriPassword = Prompt-Value "ARI password (min 8 chars)" -Secret
    if ($AriPassword.Length -lt 8) { Warn "Password must be at least 8 characters." }
} while ($AriPassword.Length -lt 8)

Section "SIP Extension Passwords"
Info "Used by softphones to register."
Write-Host ""
$Ext1001Pass = Prompt-Value "Extension 1001 password (Operator)" -Secret
$Ext1002Pass = Prompt-Value "Extension 1002 password (Sales)"    -Secret
$Ext1003Pass = Prompt-Value "Extension 1003 password (Support)"  -Secret

# ═════════════════════════════════════════════════════════════════════════════
# STEP 3 — Network
# ═════════════════════════════════════════════════════════════════════════════
Header "Step 3 of 7 — Network Configuration"
Info "These values configure PJSIP so softphones can find Asterisk."
Write-Host ""

do {
    $ServerIP = Prompt-Value "Server LAN IP address (e.g. 192.168.1.100)"
    if ($ServerIP -notmatch '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$') {
        Warn "Please enter a valid IP address."
    }
} while ($ServerIP -notmatch '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')

do {
    $LanSubnet = Prompt-Value "LAN subnet CIDR (e.g. 192.168.1.0/24)"
    if ($LanSubnet -notmatch '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$') {
        Warn "Please enter a valid CIDR (e.g. 192.168.1.0/24)."
    }
} while ($LanSubnet -notmatch '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$')

# ═════════════════════════════════════════════════════════════════════════════
# STEP 4 — Extensions & After-Hours
# ═════════════════════════════════════════════════════════════════════════════
Header "Step 4 of 7 — Extensions & After-Hours"

$OperatorExtension  = Prompt-Value "Operator / main desk extension"  "1001"
$EmergencyExtension = Prompt-Value "Emergency after-hours extension" "1001"

Write-Host ""
Info "What should happen when a caller reaches Helix outside business hours?"
Write-Host ""
Write-Host "  1) callback   — Tell caller to call back during hours"
Write-Host "  2) voicemail  — Record a voicemail"
Write-Host "  3) schedule   — Let caller book a callback via Calendar"
Write-Host "  4) emergency  — Transfer to emergency extension"
Write-Host ""
Write-Host "  Choose after-hours mode [1-4, default: 1]: " -NoNewline
$AhChoice = Read-Host
$AhChoice = if ([string]::IsNullOrWhiteSpace($AhChoice)) { "1" } else { $AhChoice }
$AfterHoursMode = switch ($AhChoice) {
    "2" { "voicemail"  }
    "3" { "schedule"   }
    "4" { "emergency"  }
    default { "callback" }
}
Log "After-hours mode: $AfterHoursMode"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 5 — Optional Features
# ═════════════════════════════════════════════════════════════════════════════
Header "Step 5 of 7 — Optional Features"

$VoicemailEnabled    = if (Prompt-YN "Enable voicemail recording?"               "y") { "true" } else { "false" }
$CallSummaryEnabled  = if (Prompt-YN "Enable AI post-call summaries?"             "n") { "true" } else { "false" }
$FaqEnabled          = if (Prompt-YN "Enable FAQ / knowledge-base lookup?"        "n") { "true" } else { "false" }
$FaqFile             = "faq.txt"
if ($FaqEnabled -eq "true") {
    $FaqFile = Prompt-Value "Path to FAQ file" "faq.txt"
}

Section "DTMF Keypress Fallback"
$DtmfEnabled = if (Prompt-YN "Enable DTMF keypress menu?" "n") { "true" } else { "false" }
$DtmfMap     = '{"1":"1002","2":"1003","0":"1001"}'
if ($DtmfEnabled -eq "true") {
    Info "Default DTMF map: 1→Sales(1002), 2→Support(1003), 0→Operator(1001)"
    Write-Host "  Custom DTMF JSON map (press Enter to use default): " -NoNewline
    $DtmfInput = Read-Host
    if (-not [string]::IsNullOrWhiteSpace($DtmfInput)) { $DtmfMap = $DtmfInput }
}

Section "VIP Callers (optional)"
Info "Phone numbers that bypass the AI and go straight to your operator."
Write-Host "  VIP caller numbers (press Enter to skip): " -NoNewline
$VipCallers = Read-Host

# ═════════════════════════════════════════════════════════════════════════════
# STEP 6 — Write configuration files
# ═════════════════════════════════════════════════════════════════════════════
Header "Step 6 of 7 — Writing Configuration"

# ── .env ─────────────────────────────────────────────────────────────────────
Section "Writing agent/.env"

if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile
    Log "Created agent/.env from template"
}

Set-Env "BUSINESS_NAME"        $BusinessName
Set-Env "AGENT_NAME"           $AgentName
Set-Env "BUSINESS_TIMEZONE"    $BusinessTimezone
Set-Env "BUSINESS_HOURS_START" $HoursStart
Set-Env "BUSINESS_HOURS_END"   $HoursEnd
Set-Env "ASTERISK_ARI_PASSWORD" $AriPassword
Set-Env "AFTER_HOURS_MODE"     $AfterHoursMode
Set-Env "OPERATOR_EXTENSION"   $OperatorExtension
Set-Env "EMERGENCY_EXTENSION"  $EmergencyExtension
Set-Env "WHISPER_DEVICE"       "cpu"
Set-Env "WHISPER_COMPUTE_TYPE" "int8"
Set-Env "VOICEMAIL_ENABLED"    $VoicemailEnabled
Set-Env "CALL_SUMMARY_ENABLED" $CallSummaryEnabled
Set-Env "FAQ_ENABLED"          $FaqEnabled
Set-Env "FAQ_FILE"             $FaqFile
Set-Env "DTMF_ENABLED"        $DtmfEnabled
Set-Env "DTMF_MAP"            $DtmfMap
Set-Env "VIP_CALLERS"         $VipCallers
Log "agent/.env written"

# ── ari.conf ─────────────────────────────────────────────────────────────────
Section "Writing asterisk/etc/asterisk/ari.conf"
$ariContent = Get-Content $AriConf -Raw
$ariContent = $ariContent -replace 'password=CHANGE_ME_ARI_PASSWORD', "password=$AriPassword"
$ariContent = $ariContent -replace '(?m)^password=.*', "password=$AriPassword"
Set-Content -Path $AriConf -Value $ariContent -Encoding UTF8 -NoNewline
Log "ari.conf password updated"

# ── pjsip.conf ────────────────────────────────────────────────────────────────
Section "Writing asterisk/etc/asterisk/pjsip.conf"
foreach ($confFile in @($PjsipConf, $PjsipWin)) {
    if (Test-Path $confFile) {
        $content = Get-Content $confFile -Raw
        $content = $content -replace 'external_media_address=YOUR_SERVER_IP',      "external_media_address=$ServerIP"
        $content = $content -replace 'external_signaling_address=YOUR_SERVER_IP',  "external_signaling_address=$ServerIP"
        $content = $content -replace '(?m)local_net=192\.168\.0\.0/16.*',          "local_net=$LanSubnet"
        $content = $content -replace 'password=CHANGE_ME_EXT_1001_PASSWORD',       "password=$Ext1001Pass"
        $content = $content -replace 'password=CHANGE_ME_EXT_1002_PASSWORD',       "password=$Ext1002Pass"
        $content = $content -replace 'password=CHANGE_ME_EXT_1003_PASSWORD',       "password=$Ext1003Pass"
        Set-Content -Path $confFile -Value $content -Encoding UTF8 -NoNewline
        Log "$(Split-Path -Leaf $confFile) updated"
    }
}

# ═════════════════════════════════════════════════════════════════════════════
# STEP 7 — Launch & Validate
# ═════════════════════════════════════════════════════════════════════════════
Header "Step 7 of 7 — Launch & Validate"

# ── Voice model note for Windows users ──────────────────────────────────────
Write-Host ""
Info "Kokoro TTS model weights download automatically from Hugging Face on first use."
Info "Kokoro natively supports: English, Spanish, French, Italian."
Info "German, Romanian, and Hebrew use espeak-ng (pre-installed in the Docker image)."
Write-Host ""

$LaunchNow = Prompt-YN "Start Helix AI now with Docker Compose?" "y"
if ($LaunchNow) {
    Info "Building and starting containers (first run may take several minutes)..."
    $composeFile = Join-Path $RepoRoot "docker-compose.yml"
    & docker compose -f $composeFile build
    & docker compose -f $composeFile up -d

    Info "Waiting for services..."
    Start-Sleep -Seconds 8

    # Ollama model pull
    Info "Pulling Ollama model llama3.1:8b into container..."
    & docker exec pbx-ollama ollama pull llama3.1:8b

    # Health checks
    Write-Host ""
    Write-Host "  Service health:" -ForegroundColor White

    Write-Host "  Asterisk: " -NoNewline
    $ast = & docker exec pbx-asterisk asterisk -rx "core show version" 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Host "ready" -ForegroundColor Green } else { Write-Host "starting up" -ForegroundColor Yellow }

    Write-Host "  Ollama:   " -NoNewline
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 5
        Write-Host "ready" -ForegroundColor Green
    } catch {
        Write-Host "not ready yet (wait a moment and check docker logs)" -ForegroundColor Yellow
    }

    Write-Host "  Agent:    " -NoNewline
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 5
        Write-Host "ready" -ForegroundColor Green
    } catch {
        Write-Host "starting up" -ForegroundColor Yellow
    }
}

# ── Google Calendar reminder ──────────────────────────────────────────────────
$CredsFile = Join-Path $RepoRoot "agent\credentials.json"
if (-not (Test-Path $CredsFile)) {
    Write-Host ""
    Warn "No credentials.json found in agent/."
    Info "To enable Google Calendar scheduling:"
    Write-Host "  1. Go to: https://console.cloud.google.com"
    Write-Host "  2. Create a project and enable the Google Calendar API"
    Write-Host "  3. Create OAuth 2.0 Desktop credentials"
    Write-Host "  4. Download as credentials.json -> place it in agent/"
    Write-Host "  5. Run: docker exec -it pbx-agent python -c `"from calendar.gcal import _get_service; _get_service()`""
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Setup Complete" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Configuration Summary" -ForegroundColor White
Write-Host "  ─────────────────────────────────────────"
Write-Host "  Business name:     " -NoNewline; Write-Host $BusinessName     -ForegroundColor Cyan
Write-Host "  Receptionist name: " -NoNewline; Write-Host $AgentName        -ForegroundColor Cyan
Write-Host "  Timezone:          " -NoNewline; Write-Host $BusinessTimezone  -ForegroundColor Cyan
Write-Host "  Business hours:    " -NoNewline; Write-Host "${HoursStart}:00 – ${HoursEnd}:00" -ForegroundColor Cyan
Write-Host "  After-hours mode:  " -NoNewline; Write-Host $AfterHoursMode   -ForegroundColor Cyan
Write-Host "  Server IP:         " -NoNewline; Write-Host $ServerIP         -ForegroundColor Cyan
Write-Host "  LAN subnet:        " -NoNewline; Write-Host $LanSubnet        -ForegroundColor Cyan
Write-Host "  Whisper device:    " -NoNewline; Write-Host "cpu (int8)"       -ForegroundColor Cyan
Write-Host "  TTS engine:        " -NoNewline; Write-Host "Kokoro (EN/ES/FR/IT) + espeak-ng (DE/RO/HE)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Files written:"
Write-Host "    [✓] agent\.env"                                               -ForegroundColor Green
Write-Host "    [✓] asterisk\etc\asterisk\ari.conf"                           -ForegroundColor Green
Write-Host "    [✓] asterisk\etc\asterisk\pjsip.conf"                         -ForegroundColor Green
if (Test-Path $PjsipWin) {
    Write-Host "    [✓] asterisk\etc\asterisk\pjsip.windows.conf"             -ForegroundColor Green
}
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "  1. Register Zoiper softphone: ${ServerIP}:5060  ext 1001"
Write-Host "  2. Dial 9999 to test your AI receptionist"
Write-Host "  3. Dashboard: http://${ServerIP}:3000"
Write-Host "  4. Agent API: http://${ServerIP}:8000"
Write-Host ""
Write-Host "  See README.md for full documentation." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Helix AI is configured and ready to go." -ForegroundColor Green
Write-Host ""
