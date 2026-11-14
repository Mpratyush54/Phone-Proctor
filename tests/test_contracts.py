from pathlib import Path
import subprocess
import sys


def test_python_examples_validate():
    r = subprocess.run([sys.executable, "tools/validate_contracts.py"], cwd=str(Path(__file__).resolve().parents[1]))
    assert r.returncode == 0
