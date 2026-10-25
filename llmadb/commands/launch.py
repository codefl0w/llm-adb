"""Handlers for app lifecycle commands: launch, stop, and clear."""

import re
import sys
import time
from typing import List, Optional

from llmadb.adb import Adb
from llmadb.commands.current import get_current_state
from llmadb.commands.info import extract_launcher_from_dumpsys
from llmadb.device import resolve_device
from llmadb.errors import (
    E_ADB,
    E_NOT_FOUND,
    E_USAGE,
    EXIT_ADB,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    LlmadbError,
)

COMPONENT_RE = re.compile(r"^([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)$")


def resolve_launcher_component(adb: Adb, pkg: str, serial: str) -> Optional[str]:
    """Resolve launcher component for a package via cmd package or dumpsys fallback."""
    if "/" in pkg:
        return pkg

    # Primary: cmd package resolve-activity --brief
    res = adb.run(
        [
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-c",
            "android.intent.category.LAUNCHER",
            pkg,
        ],
        serial=serial,
        timeout=5.0,
    )
    for line in reversed(res.text.splitlines()):
        line = line.strip()
        m = COMPONENT_RE.match(line)
        if m and not line.startswith("priority="):
            return m.group(1)

    # Fallback: dumpsys package
    dump_res = adb.run(["shell", "dumpsys", "package", pkg], serial=serial, timeout=5.0)
    comp = extract_launcher_from_dumpsys(dump_res.text, pkg)
    if comp:
        return comp

    return None


def run_launch(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'launch <pkg>': resolve launcher activity, start app, and return current state."""
    pkg = ""
    for a in args:
        if not a.startswith("-"):
            pkg = a.strip()
            break

    if not pkg:
        raise LlmadbError(
            code=E_USAGE,
            message="missing package name",
            hint="usage: llmadb launch <package>",
            exit_code=EXIT_USAGE,
        )

    target_serial = resolve_device(adb, explicit_serial=serial)
    component = resolve_launcher_component(adb, pkg, serial=target_serial)

    launched = False
    if component:
        start_res = adb.run(
            ["shell", "am", "start", "-n", component],
            serial=target_serial,
            timeout=10.0,
        )
        out_combined = start_res.text + "\n" + start_res.stderr_text
        if start_res.code == 0 and "Error:" not in out_combined and "Exception" not in out_combined:
            launched = True

    if not launched:
        # Fallback: monkey launcher intent
        monkey_res = adb.run(
            [
                "shell",
                "monkey",
                "-p",
                pkg,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            serial=target_serial,
            timeout=10.0,
        )
        monkey_out = monkey_res.text + "\n" + monkey_res.stderr_text
        if "No activities found" in monkey_out or monkey_res.code != 0:
            raise LlmadbError(
                code=E_NOT_FOUND,
                message=f"could not launch package '{pkg}'",
                hint="verify package is installed and has a LAUNCHER activity ('llmadb info <pkg>')",
                exit_code=EXIT_NOT_FOUND,
            )

    time.sleep(0.3)
    state = get_current_state(adb, serial=target_serial)
    sys.stdout.write(state + "\n")
    sys.stdout.flush()
    return 0


def run_stop(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'stop <pkg>': force-stop application."""
    pkg = ""
    for a in args:
        if not a.startswith("-"):
            pkg = a.strip()
            break

    if not pkg:
        raise LlmadbError(
            code=E_USAGE,
            message="missing package name",
            hint="usage: llmadb stop <package>",
            exit_code=EXIT_USAGE,
        )

    target_serial = resolve_device(adb, explicit_serial=serial)
    adb.run(["shell", "am", "force-stop", pkg], serial=target_serial, timeout=5.0, check=True)
    sys.stdout.write(f"stopped {pkg}\n")
    sys.stdout.flush()
    return 0


def run_clear(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'clear <pkg>': clear application data and cache via pm clear."""
    pkg = ""
    for a in args:
        if not a.startswith("-"):
            pkg = a.strip()
            break

    if not pkg:
        raise LlmadbError(
            code=E_USAGE,
            message="missing package name",
            hint="usage: llmadb clear <package>",
            exit_code=EXIT_USAGE,
        )

    target_serial = resolve_device(adb, explicit_serial=serial)
    res = adb.run(["shell", "pm", "clear", pkg], serial=target_serial, timeout=10.0)
    out = res.text.strip()
    if "Success" not in out:
        raise LlmadbError(
            code=E_ADB,
            message=f"failed to clear package '{pkg}': {out or res.stderr_text.strip() or 'Failed'}",
            hint="check that package exists and is not protected",
            exit_code=EXIT_ADB,
        )

    sys.stdout.write(f"cleared {pkg}\n")
    sys.stdout.flush()
    return 0
