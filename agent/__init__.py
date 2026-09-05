"""Laptop agent control-plane: supervisor, consent, protocol, WAL."""

from agent.consent import Capability, ConsentRecord, ConsentGate
from agent.product_mode import ProductMode, current_mode
from agent.supervisor import AgentSupervisor, LifecycleState

__all__ = [
    "Capability",
    "ConsentRecord",
    "ConsentGate",
    "ProductMode",
    "current_mode",
    "AgentSupervisor",
    "LifecycleState",
]
