"""Tests for device status reporting command and parsers."""

import json
import pytest
from llmadb.adb import Result as AdbResult
from llmadb.commands.status import (
    DeviceStatus,
    format_status_text,
    parse_battery_info,
    parse_bluetooth_info,
    parse_cellular_info,
    parse_nfc_info,
    parse_wifi_info,
    run_status,
)
from llmadb.errors import E_USAGE, LlmadbError


def test_parse_battery_info():
    raw_charging = """
  AC powered: true
  USB powered: false
  Wireless powered: false
  status: 2
  level: 85
  scale: 100
"""
    level, status = parse_battery_info(raw_charging)
    assert level == 85
    assert status == "charging"

    raw_full = """
  AC powered: true
  status: 5
  level: 100
"""
    level, status = parse_battery_info(raw_full)
    assert level == 100
    assert status == "full"

    raw_discharging = """
  AC powered: false
  USB powered: false
  Wireless powered: false
  status: 3
  level: 42
"""
    level, status = parse_battery_info(raw_discharging)
    assert level == 42
    assert status == "discharging"

    raw_not_charging = """
  AC powered: false
  status: 4
  level: 100
"""
    level, status = parse_battery_info(raw_not_charging)
    assert level == 100
    assert status == "not charging"

    # 'Capacity level: -1' must not shadow real level; plugged but held
    raw_held = "  USB powered: true\n  status: 4\n  level: 80\n  Capacity level: -1\n"
    assert parse_battery_info(raw_held) == (80, "plugged (not charging)")

    assert parse_battery_info("") == (None, "unknown")


def test_parse_wifi_info():
    # Disabled
    enabled, connected, ssid = parse_wifi_info("0", "")
    assert enabled is False
    assert connected is False
    assert ssid is None

    # Connected with SSID
    raw_info = 'mWifiInfo SSID: "Office_5G", BSSID: 00:11:22:33:44:55'
    enabled, connected, ssid = parse_wifi_info("1", raw_info)
    assert enabled is True
    assert connected is True
    assert ssid == "Office_5G"

    # Disconnected
    raw_disconn = 'mWifiInfo SSID: <unknown ssid>, Supplicant state: DISCONNECTED'
    enabled, connected, ssid = parse_wifi_info("1", raw_disconn)
    assert enabled is True
    assert connected is False
    assert ssid is None


def test_parse_cellular_info():
    # Wi-Fi-only tablet: setting absent
    assert parse_cellular_info("null", "") == (False, False)
    # Disabled
    enabled, connected = parse_cellular_info("0", "mDataConnectionState=0")
    assert enabled is False
    assert connected is False

    # Enabled and connected
    enabled, connected = parse_cellular_info("1", "    mDataConnectionState=2")
    assert enabled is True
    assert connected is True

    # Enabled but disconnected
    enabled, connected = parse_cellular_info("1", "    mDataConnectionState=0")
    assert enabled is True
    assert connected is False


def test_parse_bluetooth_info():
    # Off
    enabled, connected = parse_bluetooth_info("0", "")
    assert enabled is False
    assert connected is False

    # On, connected
    enabled, connected = parse_bluetooth_info("1", "ConnectionState: STATE_CONNECTED")
    assert enabled is True
    assert connected is True

    # On, disconnected
    enabled, connected = parse_bluetooth_info("1", "ConnectionState: STATE_DISCONNECTED")
    assert enabled is True
    assert connected is False


def test_parse_nfc_info():
    # Unsupported service
    assert parse_nfc_info("Service nfc: not found", "null") == (False, False)
    assert parse_nfc_info("Can't find service: nfc", "null") == (False, False)

    # Supported and on
    assert parse_nfc_info("Service nfc: found", "1") == (True, True)

    # Supported and off
    assert parse_nfc_info("Service nfc: found", "0") == (True, False)


def test_format_status_text():
    st = DeviceStatus(
        battery_level=90,
        battery_status="charging",
        wifi_enabled=True,
        wifi_connected=True,
        wifi_ssid="MyHome",
        cellular_enabled=True,
        cellular_connected=False,
        bluetooth_enabled=True,
        bluetooth_connected=False,
        nfc_supported=False,
        nfc_enabled=False,
        airplane_mode=False,
    )
    text = format_status_text(st)
    assert "battery: 90% (charging)" in text
    assert "wifi: on (MyHome)" in text
    assert "cellular: on" in text
    assert "bluetooth: on" in text
    assert "nfc: unsupported" in text
    assert "airplane_mode: off" in text


def test_run_status_json(monkeypatch, capsys):
    monkeypatch.setattr("llmadb.commands.status.resolve_device", lambda adb, explicit_serial=None: "emu1")

    class MockStatusAdb:
        def run(self, args, **kwargs):
            out = (
                "___LLMADB_BATCH_battery___\nstatus: 2\nlevel: 80\n"
                "___LLMADB_BATCH_wifi_on___\n1\n"
                "___LLMADB_BATCH_wifi_info___\nmWifiInfo SSID: \"TestWiFi\"\n"
                "___LLMADB_BATCH_mobile_data___\n1\n"
                "___LLMADB_BATCH_cellular_conn___\nmDataConnectionState=2\n"
                "___LLMADB_BATCH_bt_on___\n0\n"
                "___LLMADB_BATCH_bt_conn___\n\n"
                "___LLMADB_BATCH_nfc_service___\nService nfc: not found\n"
                "___LLMADB_BATCH_nfc_on___\nnull\n"
                "___LLMADB_BATCH_airplane___\n0\n"
            )
            return AdbResult(stdout=out.encode("utf-8"), stderr=b"", code=0)

    ret = run_status(["--json"], MockStatusAdb())
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["battery"]["level"] == 80
    assert data["battery"]["status"] == "charging"
    assert data["wifi"]["ssid"] == "TestWiFi"
    assert data["cellular"]["connected"] is True
    assert data["bluetooth"]["enabled"] is False
    assert data["nfc"]["supported"] is False
    assert data["airplane_mode"] is False


def test_run_status_invalid_option():
    with pytest.raises(LlmadbError) as exc:
        run_status(["--bad-flag"], None)
    assert exc.value.code == E_USAGE
