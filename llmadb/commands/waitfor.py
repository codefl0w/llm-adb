"""Handler for 'wait-for' command: poll UI until target appears or disappears."""

import sys
import time
from typing import List, Optional

from llmadb.adb import Adb
from llmadb.commands.ui import get_ui_snapshot
from llmadb.device import resolve_device
from llmadb.errors import (
    E_TIMEOUT,
    E_USAGE,
    EXIT_TIMEOUT,
    EXIT_USAGE,
    LlmadbError,
)
from llmadb.uitree import Snapshot


def run_waitfor(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Execute wait-for command polling at 500 ms intervals."""
    target_serial = resolve_device(adb, explicit_serial=serial)

    text_target: Optional[str] = None
    id_target: Optional[str] = None
    gone_target: Optional[str] = None
    timeout = 10.0

    idx = 0
    while idx < len(args):
        a = args[idx]
        if a == "--text":
            if idx + 1 < len(args):
                text_target = args[idx + 1]
                idx += 2
            else:
                idx += 1
        elif a.startswith("--text="):
            text_target = a.split("=", 1)[1]
            idx += 1
        elif a == "--id":
            if idx + 1 < len(args):
                id_target = args[idx + 1]
                idx += 2
            else:
                idx += 1
        elif a.startswith("--id="):
            id_target = a.split("=", 1)[1]
            idx += 1
        elif a == "--gone":
            if idx + 1 < len(args):
                gone_target = args[idx + 1]
                idx += 2
            else:
                idx += 1
        elif a.startswith("--gone="):
            gone_target = a.split("=", 1)[1]
            idx += 1
        elif a == "--timeout":
            if idx + 1 < len(args):
                timeout = float(args[idx + 1])
                idx += 2
            else:
                idx += 1
        elif a.startswith("--timeout="):
            timeout = float(a.split("=", 1)[1])
            idx += 1
        else:
            idx += 1

    if not text_target and not id_target and not gone_target:
        raise LlmadbError(
            code=E_USAGE,
            message="missing wait-for target condition",
            hint="specify --text 'X', --id 'Y', or --gone 'X'",
            exit_code=EXIT_USAGE,
        )

    start_time = time.time()
    last_snap: Optional[Snapshot] = None

    while time.time() - start_time < timeout:
        try:
            last_snap = get_ui_snapshot(adb, serial=target_serial)
        except Exception:
            last_snap = None

        if last_snap and last_snap.elements:
            if text_target:
                # Check if text target exists
                q = text_target.lower()
                if any(q in el.label.lower() for el in last_snap.elements):
                    output = last_snap.format_tree()
                    sys.stdout.write(output + "\n")
                    sys.stdout.flush()
                    return 0
            elif id_target:
                # Check if id target exists
                if any(el.short_id == id_target or el.resource_id.endswith(f"/{id_target}") for el in last_snap.elements):
                    output = last_snap.format_tree()
                    sys.stdout.write(output + "\n")
                    sys.stdout.flush()
                    return 0
            elif gone_target:
                # Check if target is gone
                q = gone_target.lower()
                found = any(
                    q in el.label.lower() or el.short_id == gone_target or el.resource_id.endswith(f"/{gone_target}")
                    for el in last_snap.elements
                )
                if not found:
                    output = last_snap.format_tree()
                    sys.stdout.write(output + "\n")
                    sys.stdout.flush()
                    return 0

        time.sleep(0.5)

    condition = f"text '{text_target}'" if text_target else (f"id '{id_target}'" if id_target else f"gone '{gone_target}'")
    raise LlmadbError(
        code=E_TIMEOUT,
        message=f"wait-for condition ({condition}) timed out after {timeout}s",
        hint="verify target condition or increase --timeout",
        exit_code=EXIT_TIMEOUT,
    )
