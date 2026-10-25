"""Handler for 'status' command: connectivity and battery status report."""

import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from llmadb.adb import Adb
from llmadb.device import resolve_device
from llmadb.errors import E_USAGE, EXIT_USAGE, LlmadbError
from llmadb.shellbatch import run_batch

SSID_RE = re.compile(r'SSID:\s*(?:"([^"]+)"|([^\s,]+))')
BATTERY_LEVEL_RE = re.compile(r"^\s*level:\s*(\d+)", re.MULTILINE)
BATTERY_STATUS_RE = re.compile(r"^\s*status:\s*(\d+)", re.MULTILINE)
BATTERY_POWERED_RE = re.compile(r"^\s*(?:AC|USB|Wireless|Dock) powered:\s*true", re.MULTILINE | re.IGNORECASE)
CELLULAR_STATE_RE = re.compile(r"mDataConnectionState=(\d+)")

# android.os.BatteryManager.BATTERY_STATUS_*
BATTERY_STATUS_CHARGING = 2
BATTERY_STATUS_DISCHARGING = 3
BATTERY_STATUS_NOT_CHARGING = 4
BATTERY_STATUS_FULL = 5

# TelephonyManager.DATA_CONNECTED
DATA_CONNECTED = "2"

STATUS_BATCH = {
    "battery": "dumpsys battery",
    "wifi_on": "settings get global wifi_on",
    "wifi_info": "dumpsys wifi | grep -m 1 mWifiInfo",
    "mobile_data": "settings get global mobile_data",
    "cellular_conn": "dumpsys telephony.registry | grep -m 1 mDataConnectionState",
    "bt_on": "settings get global bluetooth_on",
    "bt_conn": "dumpsys bluetooth_manager | grep -m 1 ConnectionState:",
    "nfc_service": "service check nfc",
    "nfc_on": "settings get secure nfc_on",
    "airplane": "settings get global airplane_mode_on",
}


@dataclass
class DeviceStatus:
    battery_level: Optional[int]
    battery_status: str
    wifi_enabled: bool
    wifi_connected: bool
    wifi_ssid: Optional[str]
    cellular_enabled: bool
    cellular_connected: bool
    bluetooth_enabled: bool
    bluetooth_connected: bool
    nfc_supported: bool
    nfc_enabled: bool
    airplane_mode: bool


def _setting_on(raw: str) -> bool:
    """Interpret a settings value; '0', 'null', or empty mean off/absent.

    wifi_on / bluetooth_on use 2 for 'on while airplane mode', so any other
    value counts as on.
    """
    return raw.strip() not in ("", "0", "null")


def parse_battery_info(raw: str) -> Tuple[Optional[int], str]:
    """Return (level percent, human-readable charge status)."""
    m_lvl = BATTERY_LEVEL_RE.search(raw)
    m_st = BATTERY_STATUS_RE.search(raw)
    level = int(m_lvl.group(1)) if m_lvl else None
    status_code = int(m_st.group(1)) if m_st else None
    powered = bool(BATTERY_POWERED_RE.search(raw))

    if status_code == BATTERY_STATUS_FULL or (level == 100 and powered):
        return level, "full"
    if status_code == BATTERY_STATUS_CHARGING or (powered and status_code != BATTERY_STATUS_NOT_CHARGING):
        return level, "charging"
    if status_code == BATTERY_STATUS_NOT_CHARGING:
        return level, "plugged (not charging)" if powered else "not charging"
    if status_code == BATTERY_STATUS_DISCHARGING:
        return level, "discharging"
    return level, "unknown"


def parse_wifi_info(wifi_on_raw: str, wifi_info_raw: str) -> Tuple[bool, bool, Optional[str]]:
    """Return (enabled, connected, ssid)."""
    if not _setting_on(wifi_on_raw):
        return False, False, None

    ssid = None
    m = SSID_RE.search(wifi_info_raw)
    if m:
        ssid = m.group(1) or m.group(2)
        if ssid in ("<unknown", "<unknown ssid>", "null", "<none>"):
            ssid = None

    connected = ssid is not None and "DISCONNECTED" not in wifi_info_raw
    return True, connected, ssid if connected else None


def parse_cellular_info(mobile_data_raw: str, cellular_conn_raw: str) -> Tuple[bool, bool]:
    """Return (mobile data enabled, data connected)."""
    m = CELLULAR_STATE_RE.search(cellular_conn_raw)
    return _setting_on(mobile_data_raw), bool(m and m.group(1) == DATA_CONNECTED)


def parse_bluetooth_info(bt_on_raw: str, bt_conn_raw: str) -> Tuple[bool, bool]:
    """Return (enabled, any device connected)."""
    return _setting_on(bt_on_raw), "STATE_CONNECTED" in bt_conn_raw


def parse_nfc_info(nfc_service_raw: str, nfc_on_raw: str) -> Tuple[bool, bool]:
    """Return (hardware/service present, enabled)."""
    service = nfc_service_raw.lower()
    if not service or "not found" in service or "can't find" in service:
        return False, False
    return True, nfc_on_raw.strip() == "1"


def query_device_status(adb: Adb, serial: Optional[str] = None) -> DeviceStatus:
    """Collect all status fields in a single adb shell round-trip."""
    raw = run_batch(adb, STATUS_BATCH, serial=serial, timeout=8.0)

    bat_level, bat_status = parse_battery_info(raw.get("battery", ""))
    wifi_enabled, wifi_connected, wifi_ssid = parse_wifi_info(raw.get("wifi_on", ""), raw.get("wifi_info", ""))
    cell_enabled, cell_connected = parse_cellular_info(raw.get("mobile_data", ""), raw.get("cellular_conn", ""))
    bt_enabled, bt_connected = parse_bluetooth_info(raw.get("bt_on", ""), raw.get("bt_conn", ""))
    nfc_supported, nfc_enabled = parse_nfc_info(raw.get("nfc_service", ""), raw.get("nfc_on", ""))

    return DeviceStatus(
        battery_level=bat_level,
        battery_status=bat_status,
        wifi_enabled=wifi_enabled,
        wifi_connected=wifi_connected,
        wifi_ssid=wifi_ssid,
        cellular_enabled=cell_enabled,
        cellular_connected=cell_connected,
        bluetooth_enabled=bt_enabled,
        bluetooth_connected=bt_connected,
        nfc_supported=nfc_supported,
        nfc_enabled=nfc_enabled,
        airplane_mode=raw.get("airplane", "").strip() == "1",
    )


def _radio_line(name: str, enabled: bool, connected: bool, detail: str = "") -> str:
    if not enabled:
        return f"{name}: off"
    if detail:
        return f"{name}: on ({detail})"
    return f"{name}: on (connected)" if connected else f"{name}: on"


def format_status_text(status: DeviceStatus) -> str:
    """Render compact key-value status lines."""
    level = f"{status.battery_level}%" if status.battery_level is not None else "unknown"
    wifi_detail = status.wifi_ssid or ("" if status.wifi_connected else "disconnected")
    if status.nfc_supported:
        nfc = "on" if status.nfc_enabled else "off"
    else:
        nfc = "unsupported"

    return "\n".join([
        f"battery: {level} ({status.battery_status})",
        _radio_line("wifi", status.wifi_enabled, status.wifi_connected, wifi_detail),
        _radio_line("cellular", status.cellular_enabled, status.cellular_connected),
        _radio_line("bluetooth", status.bluetooth_enabled, status.bluetooth_connected),
        f"nfc: {nfc}",
        f"airplane_mode: {'on' if status.airplane_mode else 'off'}",
    ])


def status_to_dict(status: DeviceStatus) -> Dict[str, Any]:
    """Group flat status fields into nested JSON structure."""
    return {
        "battery": {"level": status.battery_level, "status": status.battery_status},
        "wifi": {"enabled": status.wifi_enabled, "connected": status.wifi_connected, "ssid": status.wifi_ssid},
        "cellular": {"enabled": status.cellular_enabled, "connected": status.cellular_connected},
        "bluetooth": {"enabled": status.bluetooth_enabled, "connected": status.bluetooth_connected},
        "nfc": {"supported": status.nfc_supported, "enabled": status.nfc_enabled},
        "airplane_mode": status.airplane_mode,
    }


def run_status(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Execute 'status' command."""
    json_mode = False
    for a in args:
        if a == "--json":
            json_mode = True
        else:
            raise LlmadbError(
                code=E_USAGE,
                message=f"unknown status option '{a}'",
                hint="usage: llmadb status [--json]",
                exit_code=EXIT_USAGE,
            )

    target_serial = resolve_device(adb, explicit_serial=serial)
    status = query_device_status(adb, serial=target_serial)
    out = json.dumps(status_to_dict(status), indent=2) if json_mode else format_status_text(status)

    lines = out.splitlines()
    if max_lines is not None and max_lines >= 0 and len(lines) > max_lines:
        truncated = len(lines) - max_lines
        for line in lines[:max_lines]:
            sys.stdout.write(line + "\n")
        sys.stdout.write(f"[truncated: {truncated} more lines]\n")
    else:
        sys.stdout.write(out + "\n")
    sys.stdout.flush()
    return 0
