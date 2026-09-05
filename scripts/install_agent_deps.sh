#!/usr/bin/env bash
# Phone-Proctor Agent — install minimal deps (Linux/macOS)
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install --upgrade "pip>=24" wheel setuptools typing_extensions
pip uninstall -y torch torchvision torchaudio || true
pip install --no-cache-dir -r requirements-torch-cpu.txt
pip install -r requirements.txt
# Guard against ultralytics pulling a mismatched torchvision
pip install --no-cache-dir -r requirements-torch-cpu.txt

echo ""
echo "Verify: python -c 'import torch,torchvision,torchaudio; print(torch.__version__, torchvision.__version__, torchaudio.__version__)'"
echo "Optional sniff: pip install -r requirements-optional.txt"
echo "Run: python main.py --server ws://127.0.0.1:8080/agent"
