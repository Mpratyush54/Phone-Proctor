# Build standalone agent folder (Windows)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$py = if (Test-Path ".\venv\Scripts\python.exe") { ".\venv\Scripts\python.exe" } else { "python" }

Write-Host "==> Ensuring PyInstaller"
& $py -m pip install "pyinstaller>=6.3,<7"

Write-Host "==> Building"
& $py -m PyInstaller --noconfirm --clean packaging\phone_proctor.spec

Write-Host ""
Write-Host "Output: dist\PhoneProctor\PhoneProctor.exe"
Write-Host "This folder is relocatable — zip and ship. No venv required on target."
