# Trading Bot — Windows Setup Script
# Run in PowerShell: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned; .\scripts\setup-windows.ps1
# Requires: Python 3.12+ and Git already installed

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "$ProjectDir\pyproject.toml")) {
    $ProjectDir = Get-Location
}

Write-Host "=== Trading Bot Windows Setup ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectDir"

# --- Step 1: Verify prerequisites ---
Write-Host "`n[1/8] Checking prerequisites..." -ForegroundColor Yellow

$pyVersion = $null
try { $pyVersion = (py -3.12 --version 2>&1) } catch {}
if (-not $pyVersion) {
    try { $pyVersion = (python --version 2>&1) } catch {}
}
if (-not $pyVersion -or $pyVersion -notmatch "3\.(1[2-9]|[2-9]\d)") {
    Write-Host "ERROR: Python 3.12+ required. Install with: winget install Python.Python.3.12" -ForegroundColor Red
    exit 1
}
Write-Host "  Python: $pyVersion" -ForegroundColor Green

$gitVersion = $null
try { $gitVersion = (git --version 2>&1) } catch {}
if (-not $gitVersion) {
    Write-Host "ERROR: Git required. Install with: winget install Git.Git" -ForegroundColor Red
    exit 1
}
Write-Host "  Git: $gitVersion" -ForegroundColor Green

# --- Step 2: Create virtual environment ---
Write-Host "`n[2/8] Creating virtual environment..." -ForegroundColor Yellow

Set-Location $ProjectDir
if (-not (Test-Path ".venv")) {
    try { py -3.12 -m venv .venv } catch { python -m venv .venv }
}
& .venv\Scripts\Activate.ps1
Write-Host "  venv activated: $(python --version)" -ForegroundColor Green

# --- Step 3: Install dependencies ---
Write-Host "`n[3/8] Installing dependencies..." -ForegroundColor Yellow

python -m pip install --upgrade pip setuptools wheel --quiet
python -m pip install -e ".[dev]" --quiet
Write-Host "  Dependencies installed" -ForegroundColor Green

# --- Step 4: Create .env file ---
Write-Host "`n[4/8] Creating .env file..." -ForegroundColor Yellow

if (Test-Path ".env") {
    Write-Host "  .env already exists — skipping (delete it first to regenerate)" -ForegroundColor DarkYellow
} else {
    Copy-Item .env.example .env
    Write-Host "  .env created from .env.example" -ForegroundColor Green
    Write-Host "  ACTION REQUIRED: Edit .env and fill in your API keys before starting!" -ForegroundColor Red
}

# --- Step 5: Create directories ---
Write-Host "`n[5/8] Creating directories..." -ForegroundColor Yellow

New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.tradingbot" | Out-Null
New-Item -ItemType Directory -Force -Path "trade_plans" | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
Write-Host "  Created: ~\.tradingbot, trade_plans, logs" -ForegroundColor Green

# --- Step 6: Verify config loads ---
Write-Host "`n[6/7] Verifying application config..." -ForegroundColor Yellow

$cfgCheck = python -c "
from tradingbot.core.config import load_config
c = load_config()
print(f'OK:{c.general.mode.value}')
" 2>&1

if ($cfgCheck -match "OK:(.+)") {
    Write-Host "  Config loaded — mode: $($Matches[1])" -ForegroundColor Green
} else {
    Write-Host "  WARNING: Config load failed: $cfgCheck" -ForegroundColor Red
}

# --- Step 7: Create startup shortcut ---
Write-Host "`n[7/7] Creating startup script..." -ForegroundColor Yellow

$batContent = @"
@echo off
cd /d $ProjectDir
call .venv\Scripts\activate.bat
python -m tradingbot serve
"@
$batPath = "$ProjectDir\start-tradingbot.bat"
$batContent | Out-File -FilePath $batPath -Encoding ASCII
Write-Host "  Created: $batPath" -ForegroundColor Green
Write-Host "  To auto-start on boot: copy this file to shell:startup folder" -ForegroundColor DarkYellow

# --- Done ---
Write-Host "`n=== SETUP COMPLETE ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "To start the server:" -ForegroundColor White
Write-Host "  cd $ProjectDir" -ForegroundColor White
Write-Host "  .venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  python -m tradingbot serve" -ForegroundColor White
Write-Host ""
Write-Host "Then:" -ForegroundColor White
Write-Host "  1. Open http://localhost:8000 in browser" -ForegroundColor White
Write-Host "  2. Send /login on Telegram to authenticate Kite" -ForegroundColor White
Write-Host "  3. Add your PC's public IP to Kite developer console" -ForegroundColor White
Write-Host "  4. Send /analyze on Telegram to run analysis" -ForegroundColor White
Write-Host ""
