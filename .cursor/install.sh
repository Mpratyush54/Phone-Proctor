#!/usr/bin/env bash
# Idempotent dependency setup for Phone-Proctor.
# Runs after the repository is checked out. Safe to run repeatedly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV=".venv"
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

python -m pip install --upgrade pip wheel setuptools

# CPU-only PyTorch: Cloud Agent VMs have no GPU, so this avoids the multi-GB
# CUDA wheels while satisfying the "torch"/"torchaudio" requirements.
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# Project runtime dependencies.
python -m pip install -r requirements.txt

# Test runner (used by pytest.ini / the tests/ suite).
python -m pip install pytest

echo "[install] Phone-Proctor environment ready. Activate with: source $VENV/bin/activate"
