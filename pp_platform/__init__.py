"""
Platform layer: consent, attestation, OS capability probes.
Optional features (packet sniff) degrade gracefully when deps are missing.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.paths import app_root, is_frozen, writable_data_dir

# Package lives at pp_platform/ (not "platform") to avoid shadowing the stdlib.


CONSENT_VERSION = 1


@dataclass
class ConsentRecord:
    version: int
    camera: bool
    microphone: bool
    screen: bool
    keystrokes: bool
    network_monitor: bool  # optional sniff / advanced monitor
    accepted_at: str
    student_id: str = ""
    exam_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def consent_path() -> Path:
    return writable_data_dir("consent") / "latest.json"


def load_consent() -> Optional[ConsentRecord]:
    path = consent_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ConsentRecord(**{k: raw[k] for k in ConsentRecord.__dataclass_fields__ if k in raw})
    except Exception:
        return None


def save_consent(record: ConsentRecord) -> Path:
    path = consent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
    return path


def prompt_console_consent(
    student_id: str = "",
    exam_code: str = "",
    require_network_monitor: bool = False,
) -> ConsentRecord:
    """
    CLI consent gate for early product builds.
    UI consent (Qt) can call the same save_consent() later.
    """
    print("\n=== Phone-Proctor Consent ===")
    print("This exam session may capture webcam, microphone, screen,")
    print("and (if allowed) keystrokes / network integrity signals.")
    print("Data is sent to the proctoring server for live monitoring and audit.\n")

    def ask(label: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        ans = input(f"  Allow {label}? [{hint}]: ").strip().lower()
        if not ans:
            return default
        return ans in ("y", "yes")

    camera = ask("camera")
    microphone = ask("microphone")
    screen = ask("screen capture")
    keystrokes = ask("keystroke logging", default=False)
    network_monitor = ask("advanced network monitoring (optional)", default=False)

    if not camera:
        raise SystemExit("[CONSENT] Camera consent is required to proctor. Aborting.")

    if require_network_monitor and not network_monitor:
        print("[CONSENT] Network monitor declined — sniff features disabled.")

    from datetime import datetime, timezone

    record = ConsentRecord(
        version=CONSENT_VERSION,
        camera=camera,
        microphone=microphone,
        screen=screen,
        keystrokes=keystrokes,
        network_monitor=network_monitor,
        accepted_at=datetime.now(timezone.utc).isoformat(),
        student_id=student_id,
        exam_code=exam_code,
    )
    save_consent(record)
    print(f"[CONSENT] Saved → {consent_path()}\n")
    return record


# ---------------------------------------------------------------------------
# Capability probes
# ---------------------------------------------------------------------------

@dataclass
class CapabilityReport:
    os_name: str
    os_release: str
    arch: str
    frozen: bool
    scapy_available: bool
    npcap_likely: bool
    torch_available: bool
    torch_version: str
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def probe_scapy() -> bool:
    try:
        import scapy  # noqa: F401
        return True
    except Exception:
        return False


def probe_npcap_windows() -> bool:
    if os.name != "nt":
        return True
    # Npcap installs wpcap.dll; absence means sniff will fail
    candidates = [
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "Npcap.dll",
        Path(r"C:\Windows\System32\Npcap.dll"),
        Path(r"C:\Windows\SysWOW64\Npcap.dll"),
    ]
    return any(p.is_file() for p in candidates)


def probe_torch() -> tuple[bool, str]:
    try:
        import torch
        return True, getattr(torch, "__version__", "unknown")
    except Exception:
        return False, ""


def probe_capabilities() -> CapabilityReport:
    torch_ok, torch_ver = probe_torch()
    scapy_ok = probe_scapy()
    npcap_ok = probe_npcap_windows()
    notes: List[str] = []
    if not scapy_ok:
        notes.append("scapy missing — advanced packet sniff disabled")
    if os.name == "nt" and not npcap_ok:
        notes.append("Npcap.dll missing — install Npcap to enable sniff")
    if not torch_ok:
        notes.append("torch missing — audio VAD / some AI features disabled")
    return CapabilityReport(
        os_name=platform.system(),
        os_release=platform.release(),
        arch=platform.machine(),
        frozen=is_frozen(),
        scapy_available=scapy_ok,
        npcap_likely=npcap_ok,
        torch_available=torch_ok,
        torch_version=torch_ver,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Anti-tamper attestation (flag-only)
# ---------------------------------------------------------------------------

MANIFEST_NAME = "integrity_manifest.json"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(paths: Optional[List[Path]] = None) -> Dict[str, Any]:
    root = app_root()
    if paths is None:
        candidates = []
        for rel in (
            "main.py",
            "config/settings.yaml",
            "assets/dashboard.html",
            "yolov8n.pt",
        ):
            p = root / rel
            if p.is_file():
                candidates.append(p)
        # When frozen, hash the executable itself
        if is_frozen():
            candidates.append(Path(sys.executable))
        paths = candidates

    files = {}
    for p in paths:
        try:
            rel = str(p.relative_to(root)) if root in p.parents or p.parent == root else p.name
        except ValueError:
            rel = p.name
        if p.is_file():
            files[rel] = _hash_file(p)

    return {
        "created_at": time.time(),
        "platform": platform.platform(),
        "files": files,
    }


def write_manifest(dest: Optional[Path] = None) -> Path:
    dest = dest or (writable_data_dir("integrity") / MANIFEST_NAME)
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    dest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return dest


def verify_against_manifest(manifest_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Compare current hashes to a build-time or last-known manifest.
    Returns {ok, mismatches[], missing[], attestation}.
    """
    path = manifest_path or (app_root() / MANIFEST_NAME)
    if not path.is_file():
        # Fall back to user data copy written at first run
        path = writable_data_dir("integrity") / MANIFEST_NAME
    if not path.is_file():
        write_manifest(path)
        return {
            "ok": True,
            "status": "BOOTSTRAPPED",
            "mismatches": [],
            "missing": [],
            "attestation": device_fingerprint(),
        }

    expected = json.loads(path.read_text(encoding="utf-8"))
    root = app_root()
    mismatches = []
    missing = []
    for rel, digest in (expected.get("files") or {}).items():
        target = root / rel
        if not target.is_file():
            # Also try basename for frozen exe entries
            alt = Path(sys.executable) if is_frozen() and rel == Path(sys.executable).name else None
            if alt and alt.is_file():
                target = alt
            else:
                missing.append(rel)
                continue
        current = _hash_file(target)
        if current != digest:
            mismatches.append({"file": rel, "expected": digest, "actual": current})

    ok = not mismatches and not missing
    return {
        "ok": ok,
        "status": "OK" if ok else "TAMPERED",
        "mismatches": mismatches,
        "missing": missing,
        "attestation": device_fingerprint(),
    }


def device_fingerprint() -> str:
    raw = "|".join(
        [
            platform.node(),
            platform.system(),
            platform.machine(),
            platform.processor() or "",
            str(uuid.getnode()),
            socket.gethostname(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class Heartbeat:
    """Monotonic heartbeat counter for uplink (5s cadence suggested)."""

    def __init__(self):
        self.counter = 0
        self.started_at = time.monotonic()

    def tick(self) -> Dict[str, Any]:
        self.counter += 1
        return {
            "counter": self.counter,
            "uptime_s": round(time.monotonic() - self.started_at, 3),
            "ts": time.time(),
            "fingerprint": device_fingerprint(),
        }
