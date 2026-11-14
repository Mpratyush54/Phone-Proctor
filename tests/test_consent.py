"""A2 consent fail-closed tests."""

import pytest

from agent.consent import Capability, ConsentGate, ConsentRecord, Readiness


def test_required_camera_declined_blocks():
    gate = ConsentGate()
    decision = gate.evaluate(ConsentRecord(camera=False))
    assert decision.readiness is Readiness.BLOCKED
    assert not decision.may_start(Capability.CAMERA)
    with pytest.raises(PermissionError):
        gate.assert_may_start(decision, Capability.CAMERA)


def test_optional_declined_degrades_and_never_starts():
    gate = ConsentGate()
    consent = ConsentRecord(camera=True, microphone=False, screen=False, keystrokes=False, network_monitor=False)
    decision = gate.evaluate(consent)
    assert decision.readiness is Readiness.DEGRADED
    assert decision.may_start(Capability.CAMERA)
    assert not decision.may_start(Capability.MICROPHONE)
    assert not decision.may_start(Capability.SCREEN)
    assert not decision.may_start(Capability.KEYSTROKES)
    assert not decision.may_start(Capability.NETWORK_MONITOR)


def test_happy_path_all_granted_ready():
    gate = ConsentGate()
    consent = ConsentRecord(
        camera=True, microphone=True, screen=True, keystrokes=True, network_monitor=True
    )
    decision = gate.evaluate(consent)
    assert decision.readiness is Readiness.READY
    for cap in Capability:
        assert decision.may_start(cap)


def test_policy_cannot_enable_declined_capability():
    gate = ConsentGate()
    consent = ConsentRecord(camera=True, microphone=False)
    decision = gate.evaluate(consent, policy_enabled=[Capability.CAMERA, Capability.MICROPHONE])
    assert not decision.may_start(Capability.MICROPHONE)


def test_duplicate_evaluate_is_stable():
    gate = ConsentGate()
    consent = ConsentRecord(camera=True, microphone=True)
    a = gate.evaluate(consent)
    b = gate.evaluate(consent)
    assert a.readiness == b.readiness
    assert a.allowed == b.allowed


def test_timeout_retry_from_dict_defaults_fail_closed():
    rec = ConsentRecord.from_dict({})
    assert rec.camera is False
    assert ConsentGate().evaluate(rec).readiness is Readiness.BLOCKED
