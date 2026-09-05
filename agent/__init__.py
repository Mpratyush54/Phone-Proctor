"""Laptop agent control-plane: supervisor, consent, protocol, WAL + journal/uplink."""

from agent.consent import Capability, ConsentRecord, ConsentGate
from agent.product_mode import ProductMode, current_mode
from agent.supervisor import AgentSupervisor, LifecycleState

try:
    from agent.journal import WriteAheadJournal
except Exception:  # pragma: no cover - optional legacy path
    WriteAheadJournal = None

try:
    from agent.uplink import AgentUplink
except Exception:  # pragma: no cover - optional legacy path
    AgentUplink = None

__all__ = [
    "Capability",
    "ConsentRecord",
    "ConsentGate",
    "ProductMode",
    "current_mode",
    "AgentSupervisor",
    "LifecycleState",
    "WriteAheadJournal",
    "AgentUplink",
]
