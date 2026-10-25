"""Handler for 'devices' command."""

import sys
from typing import List, Optional

from llmadb.adb import Adb
from llmadb.device import list_devices
from llmadb.errors import E_NO_DEVICE, EXIT_DEVICE_SELECTION, LlmadbError


def run_devices(
    args: List[str],
    adb: Adb,
    max_lines: Optional[int] = None,
) -> int:
    """List connected devices in TSV format."""
    devices = list_devices(adb)
    if not devices:
        raise LlmadbError(
            code=E_NO_DEVICE,
            message="no devices",
            hint="check USB, enable USB debugging",
            exit_code=EXIT_DEVICE_SELECTION,
        )

    lines = [dev.to_tsv() for dev in devices]
    if max_lines is not None and max_lines >= 0 and len(lines) > max_lines:
        truncated = len(lines) - max_lines
        for line in lines[:max_lines]:
            sys.stdout.write(line + "\n")
        sys.stdout.write(f"[truncated: {truncated} more lines]\n")
    else:
        for line in lines:
            sys.stdout.write(line + "\n")
    sys.stdout.flush()
    return 0

