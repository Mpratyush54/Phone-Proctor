"""Heartbeat samples: disk free space, WAL depth, media-spool occupancy."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def _disk_status(root: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(root)
    return {
        "path": str(root),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": int(usage.free),
    }


def _wal_status(wal: Any | None) -> dict[str, Any]:
    if wal is None:
        return {"present": False, "pending": 0, "bytes": 0, "acked_through": None, "path": ""}
    pending = list(wal.pending(limit=10_000))
    path = Path(getattr(wal, "path", "") or "")
    size = path.stat().st_size if path.exists() else 0
    acked: int | None = None
    conn = getattr(wal, "_conn", None)
    if conn is not None:
        try:
            row = conn.execute("SELECT v FROM wal_meta WHERE k='acked_through'").fetchone()
            acked = int(row[0]) if row else None
        except Exception:  # noqa: BLE001
            acked = None
    return {
        "present": True,
        "pending": len(pending),
        "bytes": int(size),
        "acked_through": acked,
        "path": str(path),
    }


def _spool_status(spool: Any | None) -> dict[str, Any]:
    if spool is None:
        return {"present": False, "used_bytes": 0, "snapshots_paused": False, "path": ""}
    root = Path(getattr(spool, "root", "") or "")
    used = 0
    if root.exists():
        used = sum(p.stat().st_size for p in root.glob("*") if p.is_file())
    return {
        "present": True,
        "used_bytes": int(used),
        "snapshots_paused": bool(getattr(spool, "snapshots_paused", False)),
        "path": str(root),
    }


def health_status(
    *,
    wal: Any | None = None,
    spool: Any | None = None,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return a bounded status dict suitable for heartbeats (no per-frame metrics)."""
    root = Path(data_root) if data_root is not None else Path.cwd()
    return {
        "disk": _disk_status(root),
        "wal": _wal_status(wal),
        "spool": _spool_status(spool),
    }
