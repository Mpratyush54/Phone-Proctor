"""Product entry: parse config, construct supervisor, wait for EXAM_START.

Does not import OpenCV, sklearn, or ``utils.logger``. Local mode may delegate
to the existing ``main`` module via importlib, but that import is skipped when
it would pull ``cv2`` so ``from agent.bootstrap import main`` stays import-safe.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from agent.config import AgentConfig, MODE_ENV, load_config
from agent.consent import ConsentGate, ConsentRecord
from agent.policy import Policy, apply_gateway_policy
from agent.product_mode import ProductMode, current_mode
from agent.storage.event_wal import EventWal
from agent.supervisor import AgentSupervisor
from screen.student_shell import StudentShell

log = logging.getLogger("agent.bootstrap")

DEFAULT_GATEWAY = "wss://127.0.0.1/agent"


@dataclass
class AgentRuntime:
    supervisor: AgentSupervisor
    wal: EventWal
    consent_gate: ConsentGate
    shell: StudentShell
    config: AgentConfig
    gateway: str
    enroll_token: str | None
    policy: Policy

    def close(self) -> None:
        self.wal.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent.bootstrap")
    parser.add_argument("--enroll-token", default=os.environ.get("PHONE_PROCTOR_ENROLL_TOKEN"))
    parser.add_argument(
        "--gateway",
        default=os.environ.get("PHONE_PROCTOR_GATEWAY", DEFAULT_GATEWAY),
        help="control-plane URL (product mode requires wss://...)",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "product"),
        default=None,
        help="override PHONE_PROCTOR_MODE",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def apply_mode(args: argparse.Namespace) -> None:
    if args.mode:
        os.environ[MODE_ENV] = args.mode


def default_wal_path() -> Path:
    root = os.environ.get("PHONE_PROCTOR_DATA_DIR")
    base = Path(root).expanduser() if root else Path.home() / ".local" / "share" / "phone-proctor"
    return base / "wal" / "agent.sqlite"


def build_runtime(args: argparse.Namespace, *, wal_path: str | Path | None = None) -> AgentRuntime:
    """Construct AgentSupervisor + EventWal + ConsentGate. Do not start AI."""
    apply_mode(args)
    gateway = apply_gateway_policy(args.gateway or DEFAULT_GATEWAY)
    cfg = load_config()
    wal = EventWal(wal_path or default_wal_path())
    consent = ConsentRecord.from_dict(
        {
            "camera": os.environ.get("PHONE_PROCTOR_CONSENT_CAMERA", "1") == "1",
            "microphone": os.environ.get("PHONE_PROCTOR_CONSENT_MIC", "1") == "1",
            "screen": os.environ.get("PHONE_PROCTOR_CONSENT_SCREEN", "0") == "1",
            "keystrokes": os.environ.get("PHONE_PROCTOR_CONSENT_KEYS", "0") == "1",
            "network_monitor": os.environ.get("PHONE_PROCTOR_CONSENT_NET", "1") == "1",
        }
    )
    gate = ConsentGate()
    supervisor = AgentSupervisor(wal=wal, consent=consent, consent_gate=gate)
    # Authoritative EXAM_START is the only path that enables scoring.
    if supervisor.may_start_ai():
        raise RuntimeError("bootstrap must not enable AI before EXAM_START")
    policy = Policy(consent_gate=gate)
    shell = StudentShell()
    shell.set_lifecycle(supervisor.observed_lifecycle_state)
    log.info(
        "agent bootstrap mode=%s wait_exam_start=%s scoring=%s",
        cfg.mode.value,
        cfg.wait_exam_start,
        supervisor.may_start_ai(),
    )
    return AgentRuntime(
        supervisor=supervisor,
        wal=wal,
        consent_gate=gate,
        shell=shell,
        config=cfg,
        gateway=gateway,
        enroll_token=args.enroll_token,
        policy=policy,
    )


def _source_imports_cv2(module_name: str) -> bool:
    spec = importlib.util.find_spec(module_name)
    origin = getattr(spec, "origin", None) if spec is not None else None
    if not origin or origin in {"built-in", "frozen"}:
        return False
    try:
        text = Path(origin).read_text(encoding="utf-8")
    except OSError:
        return True
    return "import cv2" in text or "from cv2" in text


def _try_legacy_main() -> Any:
    """Call existing ``main.py`` only when that import will not pull OpenCV."""
    if _source_imports_cv2("main") and importlib.util.find_spec("cv2") is None:
        log.warning("skipping legacy main path: OpenCV (cv2) is not installed")
        return None
    try:
        mod = importlib.import_module("main")
    except ImportError as exc:
        if "cv2" in str(exc) or "opencv" in str(exc).lower():
            log.warning("skipping legacy main path: %s", exc)
            return None
        raise
    return mod.main()


def main(
    argv: Sequence[str] | None = None,
    *,
    wal_path: str | Path | None = None,
    run_legacy: bool | None = None,
) -> AgentRuntime | Any:
    args = parse_args(argv)
    runtime = build_runtime(args, wal_path=wal_path)
    local = current_mode() is ProductMode.LOCAL
    if run_legacy is None:
        run_legacy = local
    if run_legacy and local:
        launched = _try_legacy_main()
        if launched is not None:
            return launched
    return runtime


if __name__ == "__main__":
    main()
