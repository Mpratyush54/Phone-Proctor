"""Product vs local-development mode.

Local development remains the default so ``python main.py`` still works.
Product mode is opt-in via ``PHONE_PROCTOR_MODE=product``.
"""

from __future__ import annotations

import os
from enum import Enum


class ProductMode(str, Enum):
    LOCAL = "local"
    PRODUCT = "product"


def current_mode() -> ProductMode:
    raw = (os.environ.get("PHONE_PROCTOR_MODE") or "local").strip().lower()
    if raw in ("product", "prod", "production"):
        return ProductMode.PRODUCT
    return ProductMode.LOCAL


def require_wss(gateway_url: str) -> None:
    """In product mode the agent may only connect over ``wss://``."""
    if current_mode() is not ProductMode.PRODUCT:
        return
    if not gateway_url.lower().startswith("wss://"):
        raise PermissionError(
            "product mode requires a wss:// gateway URL; "
            f"got {gateway_url!r}"
        )


def lan_bind_host() -> str:
    """Leftover LAN sockets bind to localhost in product mode."""
    if current_mode() is ProductMode.PRODUCT:
        return "127.0.0.1"
    return os.environ.get("PHONE_PROCTOR_BIND", "0.0.0.0")


def google_stt_enabled() -> bool:
    if current_mode() is ProductMode.PRODUCT:
        return False
    return os.environ.get("PHONE_PROCTOR_GOOGLE_STT", "0") == "1"
