"""Tests for device discovery, parsing, and precedence."""

import pytest

from llmadb.adb import Result
from llmadb.device import (
    DeviceInfo,
    list_devices,
    parse_devices_output,
    resolve_device,
    validate_device_state,
)
from llmadb.errors import (
    E_DEVICE_STATE,
    E_MULTI_DEVICE,
    E_NO_DEVICE,
    EXIT_DEVICE_SELECTION,
    EXIT_DEVICE_STATE,
    LlmadbError,
)


SAMPLE_DEVICES_OUTPUT = """
List of devices attached
emulator-5554          device product:sdk_gphone64_arm64 model:sdk_gphone64_arm64 device:emu64a transport_id:1
RF8M10XXXXX            device usb:1-1 product:beyond1qltezc model:SM_G9730 device:beyond1q transport_id:2
192.168.1.50:5555      offline transport_id:3
emulator-5556          unauthorized transport_id:4
0123456789ABCDEF       no permissions (missing udev rules? user in plugdev group); see [http://developer.android.com/tools/device.html] usb:3-2 transport_id:5
"""


def test_parse_devices_output():
    devices = parse_devices_output(SAMPLE_DEVICES_OUTPUT)
    assert len(devices) == 5

    d1 = devices[0]
    assert d1.serial == "emulator-5554"
    assert d1.state == "device"
    assert d1.model == "sdk_gphone64_arm64"
    assert d1.transport == "transport_id:1"
    assert d1.to_tsv() == "emulator-5554\tdevice\tsdk_gphone64_arm64\ttransport_id:1"

    d2 = devices[1]
    assert d2.serial == "RF8M10XXXXX"
    assert d2.state == "device"
    assert d2.model == "SM_G9730"
    assert d2.transport == "usb:1-1"

    d3 = devices[2]
    assert d3.serial == "192.168.1.50:5555"
    assert d3.state == "offline"
    assert d3.model == "-"
    assert d3.transport == "transport_id:3"

    d4 = devices[3]
    assert d4.serial == "emulator-5556"
    assert d4.state == "unauthorized"

    d5 = devices[4]
    assert d5.serial == "0123456789ABCDEF"
    assert d5.state == "no permissions"
    assert d5.transport == "usb:3-2"


class FakeAdb:
    def __init__(self, devices_output: str):
        self.devices_output = devices_output

    def run(self, args, serial=None, timeout=None, binary=True, check=False):
        if args == ["devices", "-l"]:
            return Result(stdout=self.devices_output.encode("utf-8"), stderr=b"", code=0)
        return Result(stdout=b"", stderr=b"", code=0)


def test_resolve_single_device():
    single_output = """
List of devices attached
emulator-5554          device product:sdk model:Pixel_4 transport_id:1
"""
    fake_adb = FakeAdb(single_output)
    resolved = resolve_device(fake_adb)
    assert resolved == "emulator-5554"


def test_resolve_no_devices():
    fake_adb = FakeAdb("List of devices attached\n\n")
    with pytest.raises(LlmadbError) as exc_info:
        resolve_device(fake_adb)
    assert exc_info.value.code == E_NO_DEVICE
    assert exc_info.value.exit_code == EXIT_DEVICE_SELECTION


def test_resolve_multi_devices():
    fake_adb = FakeAdb(SAMPLE_DEVICES_OUTPUT)
    with pytest.raises(LlmadbError) as exc_info:
        resolve_device(fake_adb)
    assert exc_info.value.code == E_MULTI_DEVICE
    assert exc_info.value.exit_code == EXIT_DEVICE_SELECTION
    assert "emulator-5554" in exc_info.value.message


def test_resolve_precedence_explicit():
    fake_adb = FakeAdb(SAMPLE_DEVICES_OUTPUT)
    # Explicit serial takes precedence
    resolved = resolve_device(fake_adb, explicit_serial="emulator-5554")
    assert resolved == "emulator-5554"


def test_resolve_precedence_env(monkeypatch):
    fake_adb = FakeAdb(SAMPLE_DEVICES_OUTPUT)
    monkeypatch.setenv("LLMADB_SERIAL", "RF8M10XXXXX")
    resolved = resolve_device(fake_adb)
    assert resolved == "RF8M10XXXXX"


def test_state_validation():
    offline_dev = DeviceInfo(serial="dev1", state="offline")
    with pytest.raises(LlmadbError) as exc_info:
        validate_device_state(offline_dev)
    assert exc_info.value.code == E_DEVICE_STATE
    assert exc_info.value.exit_code == EXIT_DEVICE_STATE
    assert "kill-server" in exc_info.value.hint

    unauth_dev = DeviceInfo(serial="dev2", state="unauthorized")
    with pytest.raises(LlmadbError) as exc_info:
        validate_device_state(unauth_dev)
    assert exc_info.value.code == E_DEVICE_STATE
    assert "RSA" in exc_info.value.hint
