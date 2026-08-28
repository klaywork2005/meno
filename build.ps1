<#
.SYNOPSIS
    Build Meno.exe and the Windows installer.

.DESCRIPTION
    Two stages, either of which can be run on its own:

      1. PyInstaller produces dist\Meno\Meno.exe together with the Qt and
         OpenCV libraries it depends on. The resulting directory runs on a
         machine with no Python installed.

      2. Inno Setup packages that directory into
         dist\installer\Meno-0.1.0-Setup.exe, which installs the application,
         creates a Start menu entry and registers an uninstaller.

    Inno Setup is a separate download (https://jrsoftware.org/isdl.php). If it
    is absent, stage 1 still runs and stage 2 is skipped.

.PARAMETER SkipInstaller
    Build the executable only.

.PARAMETER Clean
    Delete build\ and dist\ first. Required after changing the spec file, which
    PyInstaller partially caches.

.EXAMPLE
    .\build.ps1
    .\build.ps1 -Clean
    .\build.ps1 -SkipInstaller
#>
[CmdletBinding()]
param(
    [switch]$SkipInstaller,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

# --- Python -----------------------------------------------------------------
# Prefer the project's virtual environment; building against whatever is on
# PATH can bundle a different PySide6 than the one developed against.
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
Write-Host "Python: $python"

if ($Clean) {
    Step "Cleaning"
    foreach ($dir in @("build", "dist")) {
        if (Test-Path $dir) { Remove-Item $dir -Recurse -Force; Write-Host "  removed $dir" }
    }
}

# --- Stage 0: dependencies --------------------------------------------------
Step "Checking build dependencies"
& $python -m pip install --quiet --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) { throw "could not install PyInstaller" }
& $python -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "could not install runtime dependencies" }

# --- Stage 0.5: icon --------------------------------------------------------
# Regenerated so that it matches the current theme.
Step "Generating the icon"
& $python tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }

# --- Stage 1: the executable ------------------------------------------------
Step "Building the executable (PyInstaller)"
& $python -m PyInstaller meno.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $root "dist\Meno\Meno.exe"
if (-not (Test-Path $exe)) { throw "expected $exe, which was not produced" }

$sizeMb = [math]::Round(((Get-ChildItem "dist\Meno" -Recurse -File |
    Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host "  $exe" -ForegroundColor Green
Write-Host "  app folder: $sizeMb MB"

if ($SkipInstaller) {
    Write-Host "`nDone (installer skipped)." -ForegroundColor Green
    exit 0
}

# --- Stage 2: the installer -------------------------------------------------
Step "Building the installer (Inno Setup)"

# ISCC is normally not on PATH, so check the default install locations.
$iscc = $null
$candidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { $iscc = $candidate; break }
}
if (-not $iscc) {
    $onPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($onPath) { $iscc = $onPath.Source }
}

if (-not $iscc) {
    Write-Warning "Inno Setup not found; no installer was built."
    Write-Host "  The application is complete and runnable: dist\Meno\Meno.exe"
    Write-Host "  To build the installer, install Inno Setup 6 from"
    Write-Host "  https://jrsoftware.org/isdl.php (or: winget install JRSoftware.InnoSetup)"
    Write-Host "  and run this script again."
    exit 0
}

Write-Host "Inno Setup: $iscc"
& $iscc "installer\meno.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$setup = Get-ChildItem "dist\installer\*.exe" | Select-Object -First 1
Write-Host "`nDone." -ForegroundColor Green
Write-Host "  App folder: dist\Meno\"
Write-Host "  Installer:  $($setup.FullName)  ($([math]::Round($setup.Length / 1MB, 1)) MB)"
