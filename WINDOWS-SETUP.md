# Windows Setup Guide

## Prerequisites

```powershell
winget install Python.Python.3.12
winget install Git.Git
winget install nssm
```

Restart PowerShell after install. Verify:
```powershell
py -3.12 --version
git --version
nssm version
```

## Initial Setup

```powershell
cd "C:\My Data\Coding and Related\Projects"
git clone https://github.com/raviraj-mashruwala/trading-bot.git
cd trading-bot

py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

If `Activate.ps1` is blocked:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Configuration

1. Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```

2. Edit `.env` — fill in all API keys (Anthropic, Kite, Telegram, TypeSafe, MotherDuck).

3. Create directories:
```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.tradingbot"
New-Item -ItemType Directory -Force -Path "trade_plans"
New-Item -ItemType Directory -Force -Path "logs"
```

## Verify Setup

```powershell
.venv\Scripts\Activate.ps1

# Python version
python --version

# Dependencies installed
pip show fastapi duckdb kiteconnect

# Config loads
python -c "from tradingbot.core.config import load_config; c=load_config(); print('Mode:', c.general.mode.value)"
```

## Run Manually (for testing)

```powershell
.venv\Scripts\Activate.ps1
python -m tradingbot serve
```

Open http://localhost:8000 in browser.

## Run as Background Services

### Install backend service

Run PowerShell as **Administrator**:
```powershell
nssm install TradingBot "C:\My Data\Coding and Related\Projects\trading-bot\.venv\Scripts\python.exe" "-m tradingbot serve"
nssm set TradingBot AppDirectory "C:\My Data\Coding and Related\Projects\trading-bot"
nssm set TradingBot AppStdout "C:\My Data\Coding and Related\Projects\trading-bot\logs\backend.log"
nssm set TradingBot AppStderr "C:\My Data\Coding and Related\Projects\trading-bot\logs\backend.log"
nssm set TradingBot AppRotateFiles 1
nssm set TradingBot AppRotateBytes 10485760
nssm start TradingBot
```

### Install frontend service

Check Node path first: `where npm`

```powershell
nssm install TradingBotFrontend "C:\Program Files\nodejs\npm.cmd" "run dev"
nssm set TradingBotFrontend AppDirectory "C:\My Data\Coding and Related\Projects\trading-bot\web"
nssm set TradingBotFrontend AppStdout "C:\My Data\Coding and Related\Projects\trading-bot\logs\frontend.log"
nssm set TradingBotFrontend AppStderr "C:\My Data\Coding and Related\Projects\trading-bot\logs\frontend.log"
nssm start TradingBotFrontend
```

### Verify services

```powershell
nssm status TradingBot
nssm status TradingBotFrontend
```

### Check logs

```powershell
Get-Content logs\backend.log -Tail 20
Get-Content logs\frontend.log -Tail 20
```

## Prevent Sleep

Run PowerShell as **Administrator**:
```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /change standby-timeout-dc 0
powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
```

Or: Settings → System → Power & Sleep → set everything to **Never**.

## Deploy Updates

```powershell
nssm stop TradingBot
nssm stop TradingBotFrontend
cd "C:\My Data\Coding and Related\Projects\trading-bot"
git pull
nssm start TradingBot
nssm start TradingBotFrontend
```

## Kite Authentication (daily before 9 AM)

1. Send `/login` on Telegram → get login URL
2. Open URL → login to Zerodha
3. Copy `request_token` from redirect URL
4. Send `/token <request_token>` on Telegram
5. Send `/health` to verify

## Remove Services (if needed)

```powershell
nssm stop TradingBot
nssm remove TradingBot confirm
nssm stop TradingBotFrontend
nssm remove TradingBotFrontend confirm
```

## Kill Stuck Processes

```powershell
# Kill all Python
taskkill /F /IM python.exe

# Kill specific port
netstat -ano | findstr :8000
taskkill /F /PID <PID>
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Activate.ps1` blocked | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `pip install` fails on kiteconnect | `winget install Microsoft.VisualStudio.2022.BuildTools` then retry |
| Telegram duplicate responses | Only one instance should run Telegram polling at a time |
| Port 8000 in use | `netstat -ano \| findstr :8000` then `taskkill /F /PID <PID>` |
| Service won't start | Check `logs\backend.log` for errors |
| PC went to sleep | Run prevent-sleep commands above |
