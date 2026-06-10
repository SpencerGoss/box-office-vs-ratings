@echo off
REM One-click launch for sharing the dashboard over Wi-Fi (LAN).
REM Other people on the SAME Wi-Fi open the URL this script prints — they need
REM nothing installed. Runs entirely on this laptop off the bundled CSV (no DB).
REM
REM What it does that run.bat doesn't:
REM   1. Asks once for admin (UAC) to open Windows Firewall port 8050 for the LAN.
REM   2. Serves on 0.0.0.0 so other devices can reach it (run.bat is local-only).

REM ---- self-elevate so we can add the firewall rule ----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator access (needed once, to open the firewall port)...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

REM ---- open the firewall for port 8050 on private+public, LAN only (idempotent) ----
powershell -NoProfile -Command ^
  "if (-not (Get-NetFirewallRule -DisplayName 'Dash Dashboard 8050' -ErrorAction SilentlyContinue)) {" ^
  "  New-NetFirewallRule -DisplayName 'Dash Dashboard 8050' -Direction Inbound -Action Allow" ^
  "    -Protocol TCP -LocalPort 8050 -Profile Any -RemoteAddress LocalSubnet | Out-Null;" ^
  "  Write-Host 'Firewall: opened port 8050 for the local network.'" ^
  "} else { Write-Host 'Firewall: port 8050 already open.' }"

REM ---- first run: create venv + install deps; later runs skip straight through ----
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
echo Installing dependencies (fast if already installed)...
pip install -r requirements.txt -q || goto :error

REM ---- print the address other laptops should open ----
echo.
for /f "delims=" %%I in ('powershell -NoProfile -Command ^
  "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object { $_.InterfaceAlias -match 'Wi-Fi|Wireless' -and $_.IPAddress -notlike '169.254.*' } ^| Select-Object -First 1 -ExpandProperty IPAddress)"') do set LANIP=%%I
echo ============================================================
echo   Dashboard is starting.
echo.
echo   On THIS laptop:        http://127.0.0.1:8050
if defined LANIP echo   On other Wi-Fi devices: http://%LANIP%:8050
echo.
echo   They must be on the SAME Wi-Fi. Leave this window open;
echo   press Ctrl+C to stop sharing.
echo ============================================================
echo.

set HOST=0.0.0.0
set PORT=8050
python app.py
goto :eof

:error
echo.
echo Setup failed. Check that Python 3.10+ is installed and on PATH.
pause
