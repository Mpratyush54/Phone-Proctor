# Phone-Proctor Agent — install minimal deps (Windows PowerShell)
# Handles flaky networks by downloading wheels with curl (resume) then pip install --no-index.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_agent_deps.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "==> Creating venv (if missing)"
if (-not (Test-Path ".\venv")) {
  python -m venv venv
}

$pip = ".\venv\Scripts\pip.exe"
$py = ".\venv\Scripts\python.exe"
$wheelhouse = Join-Path (Get-Location) ".wheelhouse"
New-Item -ItemType Directory -Force -Path $wheelhouse | Out-Null

# Clean half-uninstalled packages that break pip (e.g. ~ympy)
Get-ChildItem ".\venv\Lib\site-packages" -Directory -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like "~*" } |
  ForEach-Object { Write-Host "Removing broken $($_.Name)"; Remove-Item -Recurse -Force $_.FullName }

Write-Host "==> Upgrading pip"
& $py -m pip install --upgrade "pip>=24" wheel setuptools typing_extensions

function Get-Wheel($name, $url) {
  $out = Join-Path $wheelhouse $name
  Write-Host "==> Downloading $name (resumable)"
  & curl.exe -L --retry 10 --retry-all-errors --continue-at - -o $out $url
  if ($LASTEXITCODE -ne 0) { throw "curl failed for $name (exit $LASTEXITCODE)" }
  $len = (Get-Item $out).Length
  if ($len -lt 1MB) { throw "Download too small for $name ($len bytes) — retry" }
  Write-Host "    OK ($([math]::Round($len/1MB,1)) MB)"
}

# Matched CPU set for cp310 win_amd64 — keep in sync with requirements-torch-cpu.txt
Get-Wheel "torch-2.5.1+cpu-cp310-cp310-win_amd64.whl" `
  "https://download.pytorch.org/whl/cpu/torch-2.5.1%2Bcpu-cp310-cp310-win_amd64.whl"
Get-Wheel "torchvision-0.20.1+cpu-cp310-cp310-win_amd64.whl" `
  "https://download.pytorch.org/whl/cpu/torchvision-0.20.1%2Bcpu-cp310-cp310-win_amd64.whl"
Get-Wheel "torchaudio-2.5.1+cpu-cp310-cp310-win_amd64.whl" `
  "https://download.pytorch.org/whl/cpu/torchaudio-2.5.1%2Bcpu-cp310-cp310-win_amd64.whl"

Write-Host "==> Removing any mismatched torch stack"
& $pip uninstall -y torch torchvision torchaudio 2>$null

Write-Host "==> Installing torch stack from local wheels"
& $pip install --no-cache-dir `
  (Join-Path $wheelhouse "torch-2.5.1+cpu-cp310-cp310-win_amd64.whl") `
  (Join-Path $wheelhouse "torchvision-0.20.1+cpu-cp310-cp310-win_amd64.whl") `
  (Join-Path $wheelhouse "torchaudio-2.5.1+cpu-cp310-cp310-win_amd64.whl")

Write-Host "==> Installing agent core requirements"
& $pip install -r requirements.txt

Write-Host "==> Re-pinning torch stack from wheelhouse (guards ultralytics upgrades)"
& $pip install --no-cache-dir --force-reinstall --no-deps `
  (Join-Path $wheelhouse "torch-2.5.1+cpu-cp310-cp310-win_amd64.whl") `
  (Join-Path $wheelhouse "torchvision-0.20.1+cpu-cp310-cp310-win_amd64.whl") `
  (Join-Path $wheelhouse "torchaudio-2.5.1+cpu-cp310-cp310-win_amd64.whl")

Write-Host ""
Write-Host "Verify:"
& $py -c "import torch,torchvision,torchaudio; print(torch.__version__, torchvision.__version__, torchaudio.__version__, 'cuda=', torch.cuda.is_available())"
Write-Host ""
Write-Host "Done. Run: python main.py --skip-consent --dev"
