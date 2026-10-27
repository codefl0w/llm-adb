"""Handlers for input primitives: type, swipe, and key."""

import sys
from typing import List, Optional, Tuple

from llmadb.adb import Adb
from llmadb.cache import load_snapshot
from llmadb.commands.tap import settle_ui
from llmadb.device import resolve_device
from llmadb.errors import (
    E_UNSUPPORTED,
    E_USAGE,
    EXIT_USAGE,
    LlmadbError,
)
from llmadb.uitree import Snapshot, format_snapshot_diff

KEY_MAP = {
    "home": 3,
    "back": 4,
    "enter": 66,
    "tab": 61,
    "menu": 82,
    "power": 26,
    "volup": 24,
    "voldown": 25,
    "recents": 187,
    "app_switch": 187,
    "delete": 67,
    "del": 67,
}


def escape_input_text(text: str) -> str:
    """Escape text for Android input text command."""
    escaped = []
    for c in text:
        if c == " ":
            escaped.append("%s")
        elif c in r"""\"'&;()|<>*?$`~#[]{}""":
            escaped.append("\\" + c)
        else:
            escaped.append(c)
    return "".join(escaped)


def post_action_output(
    adb: Adb,
    serial: str,
    prev_snapshot: Optional[Snapshot],
    no_ui: bool,
    diff_mode: bool,
    settle_timeout: float = 2.0,
    wait_settle: bool = False,
    max_lines: Optional[int] = None,
    action_desc: str = "",
) -> int:
    """Handle standard post-action settling and output."""
    if no_ui:
        if action_desc:
            sys.stdout.write(f"ok {action_desc}\n")
            sys.stdout.flush()
        return 0

    new_snapshot = settle_ui(adb, serial=serial, timeout=settle_timeout, wait_settle=wait_settle)
    if diff_mode:
        output = format_snapshot_diff(prev_snapshot, new_snapshot)
    else:
        output = new_snapshot.format_tree()

    lines = output.splitlines()
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


def clear_focused_field(
    adb: Adb,
    serial: str,
    prev_snapshot: Optional[Snapshot] = None,
) -> None:
    """Clear text in the currently focused input field.

    Uses Ctrl+A (input keycombination 113 29) + Delete (67) where supported,
    followed by move-to-end (123) + backspace sequence sized to clear fields
    longer than 40 characters on legacy devices or custom views.
    """
    max_existing_len = 0
    if prev_snapshot and prev_snapshot.elements:
        for el in prev_snapshot.elements:
            if "focused" in el.flags or el.node_type == "input":
                if len(el.label) > max_existing_len:
                    max_existing_len = len(el.label)

    del_count = max(100, max_existing_len + 10)
    del_keys = ["67"] * del_count

    combo_res = adb.run(
        ["shell", "input", "keycombination", "113", "29"],
        serial=serial,
        timeout=5.0,
    )
    combo_out = f"{combo_res.text}\n{combo_res.stderr_text}".lower()
    combo_ok = (
        combo_res.code == 0
        and "unknown command" not in combo_out
        and "error" not in combo_out
        and "exception" not in combo_out
    )

    if combo_ok:
        # First 67 deletes the Ctrl+A selection; 123 + del_keys guarantees clear if view ignored Ctrl+A
        adb.run(
            ["shell", "input", "keyevent", "67", "123", *del_keys],
            serial=serial,
            timeout=5.0,
        )
    else:
        adb.run(
            ["shell", "input", "keyevent", "123", *del_keys],
            serial=serial,
            timeout=5.0,
        )


def run_type(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'type' command."""
    target_serial = resolve_device(adb, explicit_serial=serial)

    text_to_type = ""
    press_enter = "--enter" in args
    clear_field = "--clear" in args
    no_ui = "--no-ui" in args
    diff_mode = "--diff" in args
    wait_settle = "--wait-settle" in args
    settle_timeout = 2.0

    idx = 0
    while idx < len(args):
        a = args[idx]
        if a in ("--enter", "--clear", "--no-ui", "--diff"):
            idx += 1
        elif a == "--settle-timeout":
            if idx + 1 < len(args):
                settle_timeout = float(args[idx + 1])
                idx += 2
            else:
                idx += 1
        elif not text_to_type and not a.startswith("-"):
            text_to_type = a
            idx += 1
        else:
            idx += 1

    prev_snapshot = load_snapshot(target_serial)

    # Optional clear
    if clear_field:
        clear_focused_field(adb, serial=target_serial, prev_snapshot=prev_snapshot)

    if text_to_type:
        if not text_to_type.isascii():
            raise LlmadbError(
                code=E_UNSUPPORTED,
                message=f"non-ASCII characters in '{text_to_type}' are not supported by Android input text",
                hint="use ASCII characters only; Android KeyCharacterMap drops or crashes on non-ASCII input",
                exit_code=EXIT_USAGE,
            )
        escaped = escape_input_text(text_to_type)
        res = adb.run(["shell", "input", "text", escaped], serial=target_serial)
        combined = f"{res.text}\n{res.stderr_text}"
        if res.code != 0 or "Exception occurred" in combined or "NullPointerException" in combined:
            err_line = next((l.strip() for l in combined.splitlines() if l.strip()), "input text command failed")
            raise LlmadbError(
                code=E_UNSUPPORTED,
                message=f"input text failed: {err_line}",
                hint="ensure an input field is focused and text contains only standard ASCII characters",
                exit_code=EXIT_USAGE,
            )

    if press_enter:
        adb.run(["shell", "input", "keyevent", "66"], serial=target_serial)

    return post_action_output(
        adb=adb,
        serial=target_serial,
        prev_snapshot=prev_snapshot,
        no_ui=no_ui,
        diff_mode=diff_mode,
        settle_timeout=settle_timeout,
        wait_settle=wait_settle,
        max_lines=max_lines,
        action_desc=f'typed "{text_to_type}"',
    )


def compute_swipe_coords(
    direction: str,
    dist: float,
    width: int,
    height: int,
) -> Tuple[int, int, int, int]:
    """Compute (x1, y1, x2, y2) from direction and screen dimensions."""
    cx = width // 2
    cy = height // 2
    margin_x = int(width * 0.1)
    margin_y = int(height * 0.1)

    dx = int(width * dist)
    dy = int(height * dist)

    direction = direction.lower()
    if direction == "up":
        # Scroll down content: finger moves up
        x1 = cx
        x2 = cx
        y1 = min(height - margin_y, int(height * 0.75))
        y2 = max(margin_y, y1 - dy)
    elif direction == "down":
        # Scroll up content: finger moves down
        x1 = cx
        x2 = cx
        y1 = max(margin_y, int(height * 0.25))
        y2 = min(height - margin_y, y1 + dy)
    elif direction == "left":
        y1 = cy
        y2 = cy
        x1 = min(width - margin_x, int(width * 0.8))
        x2 = max(margin_x, x1 - dx)
    elif direction == "right":
        y1 = cy
        y2 = cy
        x1 = max(margin_x, int(width * 0.2))
        x2 = min(width - margin_x, x1 + dx)
    else:
        raise LlmadbError(
            code=E_USAGE,
            message=f"unknown swipe direction '{direction}'",
            hint="supported directions: up, down, left, right or explicit 'x1,y1 x2,y2'",
            exit_code=EXIT_USAGE,
        )

    return x1, y1, x2, y2


def run_swipe(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'swipe' command."""
    target_serial = resolve_device(adb, explicit_serial=serial)

    direction: Optional[str] = None
    dist = 0.5
    dur = 300
    explicit_coords: Optional[Tuple[int, int, int, int]] = None
    no_ui = "--no-ui" in args
    diff_mode = "--diff" in args
    wait_settle = "--wait-settle" in args
    settle_timeout = 2.0

    idx = 0
    non_option_args: List[str] = []
    while idx < len(args):
        a = args[idx]
        if a == "--dist":
            if idx + 1 < len(args):
                dist = float(args[idx + 1])
                idx += 2
            else:
                idx += 1
        elif a.startswith("--dist="):
            dist = float(a.split("=", 1)[1])
            idx += 1
        elif a == "--dur":
            if idx + 1 < len(args):
                dur = int(args[idx + 1])
                idx += 2
            else:
                idx += 1
        elif a.startswith("--dur="):
            dur = int(a.split("=", 1)[1])
            idx += 1
        elif a == "--settle-timeout":
            if idx + 1 < len(args):
                settle_timeout = float(args[idx + 1])
                idx += 2
            else:
                idx += 1
        elif a in ("--no-ui", "--diff", "--wait-settle"):
            idx += 1
        elif not a.startswith("-"):
            non_option_args.append(a)
            idx += 1
        else:
            idx += 1

    if not non_option_args:
        raise LlmadbError(
            code=E_USAGE,
            message="missing swipe target",
            hint="usage: 'swipe up|down|left|right' or 'swipe x1,y1 x2,y2'",
            exit_code=EXIT_USAGE,
        )

    prev_snapshot = load_snapshot(target_serial)

    if len(non_option_args) >= 2 and "," in non_option_args[0] and "," in non_option_args[1]:
        p1 = [int(v.strip()) for v in non_option_args[0].split(",")]
        p2 = [int(v.strip()) for v in non_option_args[1].split(",")]
        x1, y1, x2, y2 = p1[0], p1[1], p2[0], p2[1]
    else:
        direction = non_option_args[0]
        width = prev_snapshot.screen_width if prev_snapshot and prev_snapshot.screen_width > 0 else 1080
        height = prev_snapshot.screen_height if prev_snapshot and prev_snapshot.screen_height > 0 else 1920
        x1, y1, x2, y2 = compute_swipe_coords(direction, dist, width, height)

    adb.run(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(dur)], serial=target_serial)

    return post_action_output(
        adb=adb,
        serial=target_serial,
        prev_snapshot=prev_snapshot,
        no_ui=no_ui,
        diff_mode=diff_mode,
        settle_timeout=settle_timeout,
        wait_settle=wait_settle,
        max_lines=max_lines,
        action_desc=f"swiped {x1},{y1} -> {x2},{y2}",
    )


def run_key(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'key' command."""
    target_serial = resolve_device(adb, explicit_serial=serial)

    key_name: Optional[str] = None
    no_ui = "--no-ui" in args
    diff_mode = "--diff" in args
    wait_settle = "--wait-settle" in args
    settle_timeout = 2.0

    idx = 0
    while idx < len(args):
        a = args[idx]
        if a in ("--no-ui", "--diff", "--wait-settle"):
            idx += 1
        elif a == "--settle-timeout":
            if idx + 1 < len(args):
                settle_timeout = float(args[idx + 1])
                idx += 2
            else:
                idx += 1
        elif not key_name and not a.startswith("-"):
            key_name = a
            idx += 1
        else:
            idx += 1

    if not key_name:
        raise LlmadbError(
            code=E_USAGE,
            message="missing key argument",
            hint=f"supported keys: {', '.join(sorted(KEY_MAP.keys()))} or numeric code",
            exit_code=EXIT_USAGE,
        )

    if key_name.isdigit():
        keycode = int(key_name)
    elif key_name.lower() in KEY_MAP:
        keycode = KEY_MAP[key_name.lower()]
    else:
        raise LlmadbError(
            code=E_USAGE,
            message=f"unknown key '{key_name}'",
            hint=f"supported keys: {', '.join(sorted(KEY_MAP.keys()))} or numeric keycode",
            exit_code=EXIT_USAGE,
        )

    prev_snapshot = load_snapshot(target_serial)
    adb.run(["shell", "input", "keyevent", str(keycode)], serial=target_serial)

    return post_action_output(
        adb=adb,
        serial=target_serial,
        prev_snapshot=prev_snapshot,
        no_ui=no_ui,
        diff_mode=diff_mode,
        settle_timeout=settle_timeout,
        wait_settle=wait_settle,
        max_lines=max_lines,
        action_desc=f"key {key_name} ({keycode})",
    )
