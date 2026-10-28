<#
.SYNOPSIS
  Builds the icon, the PyInstaller one-folder app, the portable zip and (if available) the installer.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
#>
[CmdletBinding()]
param(
  [string]$Python = "",
  [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Python) {
  $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
  $Python = if (Test-Path $venvPython) { $venvPython } else { "python" }
}

$pyproject = Get-Content (Join-Path $Root "pyproject.toml") -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') { throw "Version not found in pyproject.toml" }
$Version = $Matches[1]

Write-Host "==> Generating icon"
& $Python assets\icon\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }

Write-Host "==> PyInstaller"
& $Python -m PyInstaller packaging\gestor_luces.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "==> Portable zip"
$zip = Join-Path $Root "dist\GestorDeLuces-portable-$Version.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $Root "dist\GestorDeLuces") -DestinationPath $zip
Write-Host "Created $zip (requires the Microsoft Edge WebView2 Runtime)"

if ($SkipInstaller) { return }

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
  $candidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
  )
  $found = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($found) { $iscc = [pscustomobject]@{ Source = $found } }
}
if ($iscc) {
  Write-Host "==> Inno Setup"
  & $iscc.Source "/DAppVersion=$Version" packaging\installer.iss
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
  Write-Warning "Inno Setup (ISCC.exe) not found; installer skipped."
}
