"""Tests for network/integrity_monitor.py using an injected network stub."""

import pytest

from network.integrity_monitor import NetworkIntegrityMonitor
from rules.thresholds import Thresholds


class FakeNet:
    """Stub NetworkMonitor with controllable readings and a captured ARP table."""

    def __init__(self, ssid="PHONE_HOTSPOT", local_ip="192.168.1.10", traffic=(0, 0), arp_table=""):
        self._ssid = ssid
        self._local_ip = local_ip
        self._traffic = traffic
        self._arp_table = arp_table

    def get_wifi_ssid(self):
        return self._ssid

    def get_local_ip(self):
        return self._local_ip

    def get_traffic_stats(self):
        return self._traffic

    @property
    def arp_table(self):
        return self._arp_table

    @arp_table.setter
    def arp_table(self, value):
        self._arp_table = value


def _thresholds(**net_overrides):
    config = Thresholds().config
    cfg = {**config}
    cfg["network_integrity"] = {**config["network_integrity"], **net_overrides}
    return Thresholds(cfg)


def test_hotspot_ok_when_on_allowed_ssid():
    net = FakeNet(ssid="PHONE_HOTSPOT")
    monitor = NetworkIntegrityMonitor(_thresholds(allowed_ssids=["PHONE_HOTSPOT"]), network_monitor=net)
    ok, ssid, msg = monitor.check_hotspot()
    assert ok is True
    assert ssid == "PHONE_HOTSPOT"
    assert "OK" in msg


def test_hotspot_violation_when_not_allowed():
    net = FakeNet(ssid="STARBUCKS_WIFI")
    monitor = NetworkIntegrityMonitor(_thresholds(allowed_ssids=["PHONE_HOTSPOT"]), network_monitor=net)
    ok, _, msg = monitor.check_hotspot()
    assert ok is False
    assert "Not on allowed" in msg


def test_hotspot_skipped_when_enforcement_disabled():
    net = FakeNet(ssid="ANYTHING")
    monitor = NetworkIntegrityMonitor(
        _thresholds(allowed_ssids=["PHONE_HOTSPOT"], enforce_hotspot=False), network_monitor=net
    )
    ok, _, _ = monitor.check_hotspot()
    assert ok is True


def test_hotspot_ok_no_whitelist():
    net = FakeNet(ssid="SOMETHING")
    monitor = NetworkIntegrityMonitor(_thresholds(allowed_ssids=[]), network_monitor=net)
    ok, _, msg = monitor.check_hotspot()
    assert ok is True
    assert "No whitelist" in msg


ARP_OK = """Interface: 192.168.1.10 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.1            aa-bb-cc-dd-ee-01     dynamic
  192.168.1.5            aa-bb-cc-dd-ee-02     dynamic
"""


def test_device_count_parses_arp():
    net = FakeNet(arp_table=ARP_OK)
    monitor = NetworkIntegrityMonitor(_thresholds(), network_monitor=net)
    # Patch the subprocess wrapper so no real `arp` call happens.
    monitor._run_command = lambda cmd: ARP_OK
    ok, count, msg = monitor.check_device_count()
    assert ok is True
    assert count == 2
    assert "OK" in msg


def test_device_count_violation_when_too_many(tmp_path):
    many = ARP_OK + "  192.168.1.99            aa-bb-cc-dd-ee-03     dynamic\n"
    net = FakeNet(arp_table=many)
    monitor = NetworkIntegrityMonitor(
        _thresholds(expected_devices_min=1, expected_devices_max=2), network_monitor=net
    )
    monitor._run_command = lambda cmd: many
    ok, count, msg = monitor.check_device_count()
    assert ok is False
    assert count == 3
    assert "Unexpected device count" in msg


def test_data_spike_sustained_flagged():
    net = FakeNet(traffic=(2000, 0))  # upload above 80 KB/s
    monitor = NetworkIntegrityMonitor(_thresholds(data_spike_window_sec=0.0), network_monitor=net)
    assert monitor.check_data_spike() == []  # establishes start time
    msgs = monitor.check_data_spike()       # sustained => flagged
    assert len(msgs) == 1
    assert "Data spike" in msgs[0]


def test_data_spike_clears_when_traffic_normal():
    net = FakeNet(traffic=(2000, 0))
    monitor = NetworkIntegrityMonitor(_thresholds(data_spike_window_sec=0.0), network_monitor=net)
    monitor.check_data_spike()
    net._traffic = (5, 5)
    assert monitor.check_data_spike() == []


def test_evaluate_aggregates_violations():
    net = FakeNet(ssid="WRONG_NET", traffic=(2000, 0), arp_table=ARP_OK)
    monitor = NetworkIntegrityMonitor(
        _thresholds(allowed_ssids=["PHONE_HOTSPOT"], data_spike_window_sec=0.0), network_monitor=net
    )
    monitor._run_command = lambda cmd: ARP_OK
    monitor.check_data_spike()  # establish spike start
    violations, health = monitor.evaluate()
    assert len(violations) >= 2
    assert health["hotspot"] is False
    assert health["data_spike"] is True


def test_no_net_monitor_returns_failures_gracefully(monkeypatch):
    # Force the "no platform monitor" code path even though the real
    # NetworkMonitor import succeeds in this environment.
    monkeypatch.setattr("network.integrity_monitor._NETWORK_MONITOR_AVAILABLE", False)
    monitor = NetworkIntegrityMonitor(_thresholds(allowed_ssids=["X"]), network_monitor=None)
    assert monitor.net is None
    ok, _, msg = monitor.check_hotspot()
    assert ok is False
    assert "unavailable" in msg
    assert monitor.get_device_count() == 0
    assert monitor.check_data_spike() == []