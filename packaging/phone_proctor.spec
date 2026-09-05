# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for standalone Laptop Agent.
Build:
  pyinstaller packaging/phone_proctor.spec
Output:
  dist/PhoneProctor/PhoneProctor[.exe]
"""

import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # packaging/ -> repo? SPECPATH is spec dir
# When spec lives in packaging/, parent is repo root
ROOT = Path(SPECPATH).resolve().parent

datas = []
for rel in (
    "config/settings.yaml",
    "assets/dashboard.html",
    "yolov8n.pt",
):
    src = ROOT / rel
    if src.is_file():
        dest = str(Path(rel).parent).replace("\\", "/")
        if dest == ".":
            dest = "."
        datas.append((str(src), dest if dest != "." else "."))

# Bundle models directory if present
models_dir = ROOT / "models"
if models_dir.is_dir():
    for p in models_dir.glob("*.pkl"):
        datas.append((str(p), "models"))

hiddenimports = [
    "pp_platform",
    "agent",
    "agent.journal",
    "agent.uplink",
    "utils.paths",
    "websockets",
    "cv2",
    "numpy",
    "yaml",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "scapy",  # optional — keep out of default standalone build
        "tkinter",
        "matplotlib",
        "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PhoneProctor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # consent prompts + diagnostics
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PhoneProctor",
)
