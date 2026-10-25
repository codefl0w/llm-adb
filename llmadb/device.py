"""Device discovery, listing, state validation, and resolution."""

import os
import re
from dataclasses import dataclass
from typing import List, Optional

from llmadb.adb import Adb
from llmadb.errors import (
    E_DEVICE_STATE,
    E_MULTI_DEVICE,
    E_NO_DEVICE,
    EXIT_DEVICE_SELECTION,
    EXIT_DEVICE_STATE,
    LlmadbError,
)


@dataclass
class DeviceInfo:
    serial: str
    state: str
    model: str = "-"
    transport: str = "-"
    raw: str = ""

    def to_tsv(self) -> str:
        return f"{self.serial}\t{self.state}\t{self.model}\t{self.transport}"


def parse_devices_output(output: str) -> List[DeviceInfo]:
    """Parse output of 'adb devices -l' into structured DeviceInfo list."""
    devices = []
    lines = output.strip().splitlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("List of devices attached") or line.startswith("* daemon "):
            continue

        parts = line.split()
        if not parts:
            continue

        serial = parts[0]
        # Parse state and remaining properties
        # Note: 'no permissions (...)' can span multiple tokens
        remainder = parts[1:]
        state = "-"
        model = "-"
        transport = "-"

        if remainder:
            if remainder[0] == "no" and len(remainder) > 1 and remainder[1].startswith("permission"):
                state = "no permissions"
            else:
                state = remainder[0]

        # Extract model and transport from remainder tokens
        for token in remainder:
            if token.startswith("model:"):
                model = token.split(":", 1)[1]
            elif token.startswith("usb:"):
                transport = token
            elif token.startswith("transport_id:") and transport == "-":
                transport = token

        devices.append(
            DeviceInfo(
                serial=serial,
                state=state,
                model=model,
                transport=transport,
                raw=line,
            )
        )

    return devices


def list_devices(adb: Adb) -> List[DeviceInfo]:
    """List all connected devices via adb devices -l."""
    res = adb.run(["devices", "-l"])
    return parse_devices_output(res.text)


def validate_device_state(device: DeviceInfo) -> None:
    """Validate that device is in 'device' state, otherwise raise E_DEVICE_STATE."""
    if device.state == "device":
        return

    if device.state == "unauthorized":
        hint = "accept RSA prompt on device"
    elif device.state == "offline":
        hint = "replug or `adb kill-server`"
    elif device.state == "no permissions":
        hint = "check udev rules or USB permissions"
    else:
        hint = f"device is in state '{device.state}'"

    raise LlmadbError(
        code=E_DEVICE_STATE,
        message=f"device {device.serial} is {device.state}",
        hint=hint,
        exit_code=EXIT_DEVICE_STATE,
    )


def resolve_device(
    adb: Adb,
    explicit_serial: Optional[str] = None,
    validate_state: bool = True,
) -> str:
    """Resolve target device serial following precedence rules.
    
    Precedence:
    1. explicit_serial (--device / -s)
    2. LLMADB_SERIAL
    3. ANDROID_SERIAL
    4. Single connected device
    
    Raises:
      E_NO_DEVICE: No devices connected or explicit serial not found.
      E_MULTI_DEVICE: Multiple devices connected and none specified.
      E_DEVICE_STATE: Device is unauthorized, offline, etc.
    """
    candidate = (
        explicit_serial
        or os.environ.get("LLMADB_SERIAL")
        or os.environ.get("ANDROID_SERIAL")
    )

    devices = list_devices(adb)

    if candidate:
        matching = [d for d in devices if d.serial == candidate]
        if not matching:
            # Device might still exist if adb devices is sluggish, but check if any devices exist
            if not devices:
                raise LlmadbError(
                    code=E_NO_DEVICE,
                    message=f"device '{candidate}' not found (no devices connected)",
                    hint="check USB, enable USB debugging",
                    exit_code=EXIT_DEVICE_SELECTION,
                )
            raise LlmadbError(
                code=E_NO_DEVICE,
                message=f"device '{candidate}' not found",
                hint="run 'llmadb devices' to inspect connected devices",
                exit_code=EXIT_DEVICE_SELECTION,
            )
        dev = matching[0]
        if validate_state:
            validate_device_state(dev)
        return dev.serial

    if not devices:
        raise LlmadbError(
            code=E_NO_DEVICE,
            message="no devices connected",
            hint="check USB, enable USB debugging",
            exit_code=EXIT_DEVICE_SELECTION,
        )

    if len(devices) > 1:
        serials_str = ", ".join(d.serial for d in devices)
        raise LlmadbError(
            code=E_MULTI_DEVICE,
            message=f"multiple devices connected: {serials_str}",
            hint="specify with -s/--device or set LLMADB_SERIAL",
            exit_code=EXIT_DEVICE_SELECTION,
        )

    dev = devices[0]
    if validate_state:
        validate_device_state(dev)
    return dev.serial
