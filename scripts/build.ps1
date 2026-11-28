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

function Invoke-CodeSign {
  param([Parameter(Mandatory = $true)][string]$TargetPath)
  $signtool = Get-Command signtool -ErrorAction SilentlyContinue
  if (-not ($signtool -and $env:SIGN_CERT_SHA1 -and (Test-Path $TargetPath))) {
    return
  }
  Write-Host "==> Authenticode signing $TargetPath (cert SHA1: $($env:SIGN_CERT_SHA1))"
  & $signtool.Source sign /sha1 $env:SIGN_CERT_SHA1 /fd SHA256 /tr "https://timestamp.digicert.com" /td SHA256 $TargetPath
  if ($LASTEXITCODE -ne 0) { throw "signtool failed for $TargetPath" }
}

Write-Host "==> Generating icon"
& $Python assets\icon\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }

Write-Host "==> PyInstaller"
& $Python -m PyInstaller packaging\wiz_console.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Sign the frozen executable BEFORE packaging the portable zip and Inno Setup installer
# so every distributed copy carries the Authenticode signature.
Invoke-CodeSign -TargetPath (Join-Path $Root "dist\WizConsole\WizConsole.exe")

Write-Host "==> Portable zip"
$zip = Join-Path $Root "dist\WizConsole-portable-$Version.zip"
for ($attempt = 1; $attempt -le 5; $attempt++) {
  try {
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $Root "dist\WizConsole") -DestinationPath $zip -Force
    break
  } catch {
    if ($attempt -eq 5) { throw }
    Write-Warning "Compress-Archive locked by scanner (attempt $attempt/5); retrying in 2s..."
    Start-Sleep -Seconds 2
  }
}
Write-Host "Created $zip (requires the Microsoft Edge WebView2 Runtime)"

if (-not $SkipInstaller) {
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
    Invoke-CodeSign -TargetPath (Join-Path $Root "dist\WizConsole-Setup-$Version.exe")
  } else {
    Write-Warning "Inno Setup (ISCC.exe) not found; installer skipped."
  }
}

Write-Host "==> Generating SHA256SUMS.txt"
$sumsFile = Join-Path $Root "dist\SHA256SUMS.txt"
$artifacts = Get-ChildItem (Join-Path $Root "dist") -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" }
$lines = foreach ($item in $artifacts) {
  $hash = (Get-FileHash -Path $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  "$hash  $($item.Name)"
}
# LF sin BOM: `Set-Content -Encoding UTF8` escribe BOM + CRLF, y en Linux/macOS
# `sha256sum -c` toma el CR como parte del nombre ("FAILED open or read").
[System.IO.File]::WriteAllText($sumsFile, (($lines -join "`n") + "`n"),
  (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Wrote $sumsFile"
