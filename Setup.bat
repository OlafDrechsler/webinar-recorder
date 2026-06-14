@echo off
REM ============================================================
REM  Webinar Recorder - Setup (Doppelklick zum Installieren)
REM  Startet install.ps1 mit passender Ausfuehrungsrichtlinie.
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Setup wurde mit einem Fehler beendet. Siehe install_log_*.txt
  pause
)
