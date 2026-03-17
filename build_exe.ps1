[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'

$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRoot = (Resolve-Path $SourceRoot).Path
$TempRoot = Join-Path $env:TEMP 'snet_tester_build_ws'
$BuildVenv = Join-Path $TempRoot '.buildvenv'
$OutputDir = Join-Path $SourceRoot 'dist'
$OutputExe = Join-Path $OutputDir 'snet-tester.exe'

Write-Host "[1/6] Preparing temp workspace: $TempRoot"
if (Test-Path $TempRoot) {
    Remove-Item $TempRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $TempRoot | Out-Null

$robocopyArgs = @(
    $SourceRoot,
    $TempRoot,
    '/MIR',
    '/XD', '.git', '.venv', 'build', 'dist', '__pycache__', '.pytest_cache',
    '/XF', '*.pyc', '*.pyo'
)
robocopy @robocopyArgs | Out-Host
if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}

if (-not $SkipTests) {
    Write-Host "[2/6] Running tests in source workspace"
    & (Join-Path $SourceRoot '.venv\Scripts\python.exe') -m pytest -q
}
else {
    Write-Host "[2/6] Skipping tests"
}

Write-Host "[3/6] Creating build venv"
uv venv $BuildVenv --python 3.14

Write-Host "[4/6] Installing project + PyInstaller into build venv"
uv pip install --python (Join-Path $BuildVenv 'Scripts\python.exe') -e $TempRoot pyinstaller

Write-Host "[5/6] Building exe"
Push-Location $TempRoot
try {
    & (Join-Path $BuildVenv 'Scripts\pyinstaller.exe') --noconfirm --clean snet-tester.spec
}
finally {
    Pop-Location
}

Write-Host "[6/6] Copying exe back to project dist"
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}
Copy-Item (Join-Path $TempRoot 'dist\snet-tester.exe') $OutputExe -Force

$builtExe = Get-Item $OutputExe
Write-Host ""
Write-Host "Build complete:"
Write-Host "  $($builtExe.FullName)"
Write-Host "  Size: $([Math]::Round($builtExe.Length / 1MB, 2)) MB"
Write-Host "  Modified: $($builtExe.LastWriteTime)"
