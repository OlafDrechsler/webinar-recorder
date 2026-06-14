# Setup for the Webinar Recorder.
# Installs Python (if missing), the Python dependencies, FFmpeg, and creates the
# Desktop/Start-menu shortcuts. Run once on each computer after copying the
# WebinarRecorder folder there.
#
# Easiest: double-click Setup.bat (it launches this with the right policy).
# Manual:  powershell -ExecutionPolicy Bypass -File .\install.ps1

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- Logging: everything shown on screen is also written to a log file ---
$logFile = Join-Path $here ("install_log_{0}.txt" -f (Get-Date -Format "yyyy-MM-dd_HH-mm-ss"))
try { Start-Transcript -Path $logFile -Force | Out-Null } catch {}

function Pause-AtEnd {
    if (Get-Command Stop-Transcript -ErrorAction SilentlyContinue) {
        try { Stop-Transcript | Out-Null } catch {}
    }
    Write-Host ""
    Write-Host ("Log gespeichert: {0}" -f $logFile) -ForegroundColor DarkGray
    Write-Host "Eine Taste druecken zum Beenden..." -ForegroundColor Cyan
    [void][System.Console]::ReadKey($true)
}

# Reload PATH from the registry so software installed in THIS run (Python,
# FFmpeg) becomes usable without opening a new terminal.
function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = ($machine, $user | Where-Object { $_ }) -join ";"
}

# Find a REAL python.exe. The catch on Windows: a "python.exe" under WindowsApps
# is the Microsoft Store *alias stub* — it is on PATH but only prints "install
# from the Store" and exits, so a naive Get-Command check is fooled into thinking
# Python is installed. We therefore validate the version and skip the stub, and
# also probe the standard install locations. Returns a full path or $null.
function Resolve-PythonExe {
    # 1) The py launcher knows where the real interpreter is.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $p = (& py -3 -c "import sys; print(sys.executable)" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $p -and (Test-Path $p.Trim())) { return $p.Trim() }
        } catch {}
    }
    # 2) A 'python' on PATH that is NOT the Store stub and reports a 3.x version.
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch 'WindowsApps')) {
        try {
            $v = (& $cmd.Source --version 2>&1)
            if ("$v" -match 'Python 3\.') { return $cmd.Source }
        } catch {}
    }
    # 3) Standard per-user / per-machine install locations.
    $globs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "${env:ProgramFiles(x86)}\Python3*\python.exe"
    )
    foreach ($g in $globs) {
        $hit = Get-ChildItem -Path $g -ErrorAction SilentlyContinue |
               Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

Write-Host "== Webinar Recorder Setup ==" -ForegroundColor Cyan

# 1. Python (auto-install via winget if missing)
$python = Resolve-PythonExe
if (-not $python) {
    Write-Host "Python wurde nicht gefunden (oder nur der Microsoft-Store-Platzhalter)." -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "Installiere Python via winget..." -ForegroundColor Cyan
        & winget install --id Python.Python.3.12 -e --source winget --scope user `
            --accept-source-agreements --accept-package-agreements --disable-interactivity
        Refresh-Path
        $python = Resolve-PythonExe
    }
    if (-not $python) {
        Write-Host "Python konnte nicht automatisch installiert werden." -ForegroundColor Red
        Write-Host "Bitte Python 3.10+ von https://www.python.org/downloads/ installieren"
        Write-Host "und bei der Installation 'Add python.exe to PATH' anhaken,"
        Write-Host "danach dieses Setup erneut starten."
        Write-Host "Tipp: Den Store-Platzhalter abschalten unter"
        Write-Host "  Einstellungen > Apps > Erweiterte App-Einstellungen > App-Ausfuehrungsaliase."
        Pause-AtEnd
        exit 1
    }
}
$pyver = (& $python --version) 2>&1
Write-Host "Python gefunden: $pyver"
Write-Host "  ($python)"

# 2. Python-Pakete
Write-Host "`nInstalliere Python-Pakete..." -ForegroundColor Cyan
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $here "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Paketinstallation fehlgeschlagen." -ForegroundColor Red
    Pause-AtEnd
    exit 1
}

# 3. FFmpeg (for MP3 + loudness matching; without it audio stays as WAV)
Write-Host "`nPruefe FFmpeg..." -ForegroundColor Cyan
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ff) {
    Write-Host "FFmpeg gefunden: $($ff.Source)"
} else {
    Write-Host "FFmpeg nicht gefunden." -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "Installiere FFmpeg via winget..."
        # --source winget + --disable-interactivity verhindern die msstore-Rueckfrage,
        # an der die Installation sonst haengen bleibt.
        & winget install --id Gyan.FFmpeg -e --source winget `
            --accept-source-agreements --accept-package-agreements --disable-interactivity
        Refresh-Path
    } else {
        Write-Host "winget ist nicht verfuegbar. FFmpeg manuell installieren:" -ForegroundColor Yellow
        Write-Host "  https://www.gyan.dev/ffmpeg/builds/ (ffmpeg-release-essentials.zip)"
        Write-Host "  Entpacken und den bin-Ordner zum PATH hinzufuegen."
        Write-Host "  Ohne FFmpeg werden Aufnahmen als grosse WAV-Dateien gespeichert."
    }
}

# 4. Smoke check
Write-Host "`nPruefe Importe..." -ForegroundColor Cyan
& $python -c "import mss, numpy, PIL, soundfile, pyaudiowpatch, PySide6, keyboard; print('Alle Pakete importierbar.')"

# 5. Verknuepfungen (pass the resolved interpreter so the shortcuts never point
#    at the Store stub).
Write-Host "`nErstelle Verknuepfungen (Desktop + Startmenue)..." -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File (Join-Path $here "create_shortcuts.ps1") -PythonExe $python

Write-Host "`nFertig." -ForegroundColor Green
Write-Host "Start per Doppelklick auf 'Webinar Aufnahme' (Desktop/Startmenue)"
Write-Host "oder:  python app.py  /  python player\play.py"

Pause-AtEnd
