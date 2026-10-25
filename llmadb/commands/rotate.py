"""Handler for 'rotate' command: query, toggle, or set screen rotation."""

import sys
from typing import List, Optional, Tuple

from llmadb.adb import Adb
from llmadb.commands.current import parse_rotation
from llmadb.device import resolve_device
from llmadb.errors import E_USAGE, EXIT_USAGE, LlmadbError
from llmadb.shellbatch import run_batch

ROTATION_NAMES = {
    0: "portrait",
    1: "landscape",
    2: "reverse-portrait",
    3: "reverse-landscape",
}

ROTATION_ALIASES = {
    "0": 0, "portrait": 0, "port": 0,
    "1": 1, "landscape": 1, "land": 1,
    "2": 2, "reverse-portrait": 2, "reverse_portrait": 2,
    "3": 3, "reverse-landscape": 3, "reverse_landscape": 3,
}


def parse_target_rotation(arg: str) -> Optional[int]:
    """Parse user rotation argument to int 0-3, or None if not an explicit angle."""
    return ROTATION_ALIASES.get(arg.strip().lower())


def get_rotation_state(adb: Adb, serial: Optional[str] = None) -> Tuple[int, bool]:
    """Query (rotation 0-3, auto_rotate enabled) in one round-trip.

    With auto-rotate off, user_rotation is authoritative (it is what a toggle
    should flip, even if a portrait-locked app keeps the display at 0). With
    auto-rotate on, user_rotation is stale, so the live display rotation is used.
    """
    raw = run_batch(
        adb,
        {
            "auto": "settings get system accelerometer_rotation",
            "user_rot": "settings get system user_rotation",
            "display_rot": "dumpsys window displays | grep -m 1 -E '^ +mRotation='",
        },
        serial=serial,
        timeout=5.0,
    )
    auto = raw.get("auto", "").strip() == "1"
    user_rot = "" if auto else raw.get("user_rot", "")
    return parse_rotation(user_rot, raw.get("display_rot", "")), auto


def _emit(rotation: int, auto: bool) -> int:
    name = ROTATION_NAMES.get(rotation, "unknown")
    sys.stdout.write(f"rot={rotation} ({name}) auto_rotate={'on' if auto else 'off'}\n")
    sys.stdout.flush()
    return 0


def run_rotate(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Execute 'rotate' command.

    No args toggles portrait <-> landscape. Explicit angles lock rotation
    (auto-rotate off) so the sensor cannot revert the change.
    """
    if len(args) > 1:
        raise LlmadbError(
            code=E_USAGE,
            message=f"unexpected extra argument '{args[1]}'",
            hint="run 'llmadb rotate [0|1|2|3|portrait|landscape|auto|off]' or without args to toggle",
            exit_code=EXIT_USAGE,
        )

    arg = args[0].strip().lower() if args else None
    target: Optional[int] = None
    if arg is not None and arg not in ("auto", "on", "off"):
        target = parse_target_rotation(arg)
        if target is None:
            raise LlmadbError(
                code=E_USAGE,
                message=f"invalid rotation '{args[0]}': expected 0-3, portrait, landscape, auto, or off",
                hint="run 'llmadb rotate [0|1|2|3|portrait|landscape|auto|off]' or without args to toggle",
                exit_code=EXIT_USAGE,
            )

    target_serial = resolve_device(adb, explicit_serial=serial)

    if arg in ("auto", "on", "off"):
        enabled = arg != "off"
        adb.run(
            ["shell", f"settings put system accelerometer_rotation {1 if enabled else 0}"],
            serial=target_serial,
        )
        rotation, _ = get_rotation_state(adb, serial=target_serial)
        return _emit(rotation, enabled)

    if target is None:
        current, _ = get_rotation_state(adb, serial=target_serial)
        target = 1 if current == 0 else 0

    adb.run(
        [
            "shell",
            f"settings put system accelerometer_rotation 0; settings put system user_rotation {target}",
        ],
        serial=target_serial,
    )
    return _emit(target, False)
