"""Control-plane protocol package (re-exports existing client)."""

from agent.protocol.client import ConnectionManager, OrderedSender, ProtocolError
from agent.protocol.commands import CommandReceiver

__all__ = [
    "ConnectionManager",
    "OrderedSender",
    "ProtocolError",
    "CommandReceiver",
]
