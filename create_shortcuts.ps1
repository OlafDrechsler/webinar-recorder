# Creates Desktop and Start-Menu shortcuts so the recorder and player can be
# launched by double-click (no PowerShell, no console window).
# Run:  powershell -ExecutionPolicy Bypass -File .\create_shortcuts.ps1
#
# install.ps1 passes the resolved interpreter via -PythonExe so the shortcuts
# never point at the Microsoft-Store stub. When run standalone we resolve it the
# same Store-alias-aware way.
param([string]$PythonExe)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-PythonExe {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $p = (& py -3 -c "import sys; print(sys.executable)" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $p -and (Test-Path $p.Trim())) { return $p.Trim() }
        } catch {}
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch 'WindowsApps')) {
        try {
            $v = (& $cmd.Source --version 2>&1)
            if ("$v" -match 'Python 3\.') { return $cmd.Source }
        } catch {}
    }
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

# Use the interpreter passed in, else resolve one ourselves.
if (-not $PythonExe -or -not (Test-Path $PythonExe)) {
    $PythonExe = Resolve-PythonExe
}
if (-not $PythonExe) {
    Write-Host "Python nicht gefunden - bitte zuerst install.ps1 ausfuehren." -ForegroundColor Red
    return
}

# Prefer pythonw.exe (no console window) next to python.exe.
$pyw = Join-Path (Split-Path $PythonExe -Parent) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $PythonExe }  # fallback to python.exe

function New-Shortcut {
    param($LinkPath, $Arguments, $Description)
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($LinkPath)
    $sc.TargetPath = $pyw
    $sc.Arguments = $Arguments
    $sc.WorkingDirectory = $here
    $sc.Description = $Description
    $sc.IconLocation = "$pyw,0"
    $sc.Save()
    Write-Host "Erstellt: $LinkPath"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Webinar Recorder"
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null

$quote = [char]34
$appArg    = $quote + (Join-Path $here "app.py") + $quote
$playerArg = $quote + (Join-Path $here "player\play.py") + $quote
$sortArg   = $quote + (Join-Path $here "sortout.py") + $quote

foreach ($dir in @($desktop, $startMenu)) {
    New-Shortcut (Join-Path $dir "Webinar Aufnahme.lnk")  $appArg    "Webinar aufnehmen"
    New-Shortcut (Join-Path $dir "Webinar Player.lnk")    $playerArg "Webinar-Aufnahme abspielen"
    New-Shortcut (Join-Path $dir "Folien aussortieren.lnk") $sortArg "Doppelte Folienbilder aussortieren"
}

Write-Host ""
Write-Host "Fertig. Verknuepfungen liegen auf dem Desktop und im Startmenue (Ordner Webinar Recorder)." -ForegroundColor Green
