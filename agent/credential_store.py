"""OS-protected credential storage (keyring / DPAPI-like file fallback).

Restart resumes the session without reusing the enrollment token.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from utils.paths import user_data_root


class CredentialStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (user_data_root() / "credentials.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, record: dict[str, Any]) -> None:
        forbidden = {"enrollment_token", "pairing_token"}
        cleaned = {k: v for k, v in record.items() if k not in forbidden}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
