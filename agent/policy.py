"""Policy overlay: consent gate plus product-mode transport rules."""

from __future__ import annotations

from typing import Iterable

from agent.consent import Capability, ConsentDecision, ConsentGate, ConsentRecord
from agent.product_mode import ProductMode, current_mode, require_wss


def apply_gateway_policy(gateway_url: str) -> str:
    """Reject plaintext ``ws://`` when ``PHONE_PROCTOR_MODE=product``."""
    require_wss(gateway_url)
    return gateway_url


def evaluate_consent(
    consent: ConsentRecord,
    policy_enabled: Iterable[Capability] | None = None,
    gate: ConsentGate | None = None,
) -> ConsentDecision:
    """Server policy cannot enable a capability the student declined."""
    return (gate or ConsentGate()).evaluate(consent, policy_enabled)


class Policy:
    """Thin wrapper around consent evaluation and product WSS enforcement."""

    def __init__(self, consent_gate: ConsentGate | None = None) -> None:
        self.gate = consent_gate or ConsentGate()

    def evaluate(
        self,
        consent: ConsentRecord,
        policy_enabled: Iterable[Capability] | None = None,
    ) -> ConsentDecision:
        return evaluate_consent(consent, policy_enabled, gate=self.gate)

    def require_wss(self, gateway_url: str) -> str:
        return apply_gateway_policy(gateway_url)

    @property
    def product_mode(self) -> ProductMode:
        return current_mode()
