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
for ($attempt = 1; $attempt -le 5; $attempt++) {
  try {
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $Root "dist\GestorDeLuces") -DestinationPath $zip -Force
    break
  } catch {
    if ($attempt -eq 5) { throw }
    Write-Warning "Compress-Archive locked by scanner (attempt $attempt/5); retrying in 2s..."
    Start-Sleep -Seconds 2
  }
}
Write-Host "Created $zip (requires the Microsoft Edge WebView2 Runtime)"

if ($SkipInstaller) {
  Write-Host "==> Generating SHA256SUMS.txt"
  $sumsFile = Join-Path $Root "dist\SHA256SUMS.txt"
  $artifacts = Get-ChildItem (Join-Path $Root "dist") -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" }
  $lines = foreach ($item in $artifacts) {
    $hash = (Get-FileHash -Path $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($item.Name)"
  }
  Set-Content -Path $sumsFile -Value $lines -Encoding UTF8
  Write-Host "Wrote $sumsFile"
  return
}

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

$signtool = Get-Command signtool -ErrorAction SilentlyContinue
if ($signtool -and $env:SIGN_CERT_SHA1) {
  Write-Host "==> Authenticode signing (cert SHA1: $($env:SIGN_CERT_SHA1))"
  $targets = @(Join-Path $Root "dist\GestorDeLuces\GestorDeLuces.exe")
  $setupExe = Join-Path $Root "dist\GestorDeLuces-Setup-$Version.exe"
  if (Test-Path $setupExe) { $targets += $setupExe }
  foreach ($bin in $targets) {
    & $signtool.Source sign /sha1 $env:SIGN_CERT_SHA1 /fd SHA256 /tr "http://timestamp.digicert.com" /td SHA256 $bin
    if ($LASTEXITCODE -ne 0) { throw "signtool failed for $bin" }
  }
}

Write-Host "==> Generating SHA256SUMS.txt"
$sumsFile = Join-Path $Root "dist\SHA256SUMS.txt"
$artifacts = Get-ChildItem (Join-Path $Root "dist") -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" }
$lines = foreach ($item in $artifacts) {
  $hash = (Get-FileHash -Path $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  "$hash  $($item.Name)"
}
Set-Content -Path $sumsFile -Value $lines -Encoding UTF8
Write-Host "Wrote $sumsFile"
