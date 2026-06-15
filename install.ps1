# install.ps1 - put `superclean` on your PATH.
#
# Creates a small shim (superclean.cmd) in a directory that is already on the
# user PATH, so you can run `superclean ...` from anywhere. Re-run any time to
# repoint the shim at this copy. Uninstall with: install.ps1 -Uninstall

[CmdletBinding()]
param(
    [string]$ShimDir = (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps'),
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$entry = Join-Path $repo 'superclean.ps1'
$shim = Join-Path $ShimDir 'superclean.cmd'

if ($Uninstall) {
    if (Test-Path $shim) {
        Remove-Item $shim -Force
        Write-Host "Removed shim: $shim" -ForegroundColor Green
    } else {
        Write-Host "No shim found at $shim" -ForegroundColor Yellow
    }
    return
}

if (-not (Test-Path $entry)) {
    throw "Cannot find superclean.ps1 next to install.ps1 ($entry)."
}
if (-not (Test-Path $ShimDir)) {
    New-Item -ItemType Directory -Path $ShimDir -Force | Out-Null
}

# The shim forwards all arguments to the real script via Windows PowerShell.
$cmd = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$entry" %*
"@
Set-Content -Path $shim -Value $cmd -Encoding ASCII -Force

Write-Host "Installed shim: $shim" -ForegroundColor Green
Write-Host "Points at:      $entry"

if (($env:PATH -split ';') -notcontains $ShimDir) {
    Write-Host ""
    Write-Host "NOTE: $ShimDir is not on your PATH." -ForegroundColor Yellow
    Write-Host "Add it, or pass -ShimDir <a folder already on PATH>." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Open a new terminal, then run:  superclean --report"
}
