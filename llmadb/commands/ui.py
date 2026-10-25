"""Handler for 'ui' command."""

import sys
import time
from typing import List, Optional, Tuple

from llmadb.adb import Adb
from llmadb.cache import get_next_snapshot_id, save_snapshot
from llmadb.device import resolve_device
from llmadb.errors import (
    E_SECURE_OR_EMPTY,
    EXIT_SECURE_OR_EMPTY,
    LlmadbError,
)
from llmadb.uitree import Snapshot, parse_ui_tree, parse_window_state


def detect_window_state(
    adb: Adb,
    serial: Optional[str] = None,
) -> Tuple[str, int, int, List[str]]:
    """Query WindowManager and InputDispatcher for focused package, dimensions, and overlays."""
    try:
        cmd = (
            "dumpsys window displays | grep -E 'cur=|mCurrentFocus='; "
            "dumpsys window windows | grep -E 'InputWindowHandle=|mCurrentFocus='; "
            "dumpsys input | grep -E '^[ ]+[0-9]+: name='"
        )
        res = adb.run(
            ["shell", cmd],
            serial=serial,
            timeout=2.0,
        )
        text = res.stdout.decode("utf-8", errors="replace")
        return parse_window_state(text)
    except Exception:
        return "", 0, 0, []


def enrich_snapshot_with_window_state(
    adb: Adb,
    serial: Optional[str],
    snapshot: Snapshot,
    raw_bytes: bytes,
) -> Snapshot:
    """Attach overlay window warnings and fallback dimensions/package when UI is busy."""
    focus_pkg, win_w, win_h, overlay_warnings = detect_window_state(adb, serial=serial)
    if focus_pkg and not snapshot.app_package:
        snapshot.app_package = focus_pkg
    if win_w > 0 and snapshot.screen_width == 0:
        snapshot.screen_width = win_w
    if win_h > 0 and snapshot.screen_height == 0:
        snapshot.screen_height = win_h

    if b"could not get idle state" in raw_bytes and not snapshot.elements:
        busy_msg = "! ui busy/animating (uiautomator could not get idle state); use 'llmadb screen' to inspect visually"
        if busy_msg not in snapshot.warnings:
            snapshot.warnings.insert(0, busy_msg)

    for ow in overlay_warnings:
        if ow not in snapshot.warnings:
            snapshot.warnings.append(ow)

    return snapshot


def dump_hierarchy_bytes(
    adb: Adb,
    serial: Optional[str] = None,
    compressed: bool = False,
    retries: int = 2,
    delay: float = 0.2,
    timeout: float = 3.5,
) -> bytes:
    """Acquire uiautomator XML dump bytes with fail-fast on non-idle screens."""
    dump_args = ["exec-out", "uiautomator", "dump"]
    if compressed:
        dump_args.append("--compressed")
    dump_args.append("/dev/tty")

    last_out = b""

    for attempt in range(retries):
        t0 = time.monotonic()
        try:
            res = adb.run(dump_args, serial=serial, timeout=timeout)
            data = res.stdout
            if b"</hierarchy>" in data and b"null root node" not in data:
                return data
            last_out = data
            # Fail fast when uiautomator cannot reach idle state (60fps animation/timer)
            if b"could not get idle state" in data or (time.monotonic() - t0) >= 1.5:
                return last_out
        except Exception:
            if (time.monotonic() - t0) >= 1.5:
                return b"ERROR: could not get idle state."

        # Single-call fallback to /sdcard only when /dev/tty failed immediately without idle timeout
        if b"null root node" not in last_out:
            t1 = time.monotonic()
            try:
                comp_flag = "--compressed " if compressed else ""
                sdcard_cmd = (
                    f"uiautomator dump {comp_flag}/sdcard/llmadb.xml >/dev/null 2>&1 "
                    f"&& cat /sdcard/llmadb.xml; rm -f /sdcard/llmadb.xml"
                )
                cat_res = adb.run(["shell", sdcard_cmd], serial=serial, timeout=timeout)
                data = cat_res.stdout
                if b"</hierarchy>" in data and b"null root node" not in data:
                    return data
                if data:
                    last_out = data
                if b"could not get idle state" in last_out or (time.monotonic() - t1) >= 1.5:
                    return last_out
            except Exception:
                if (time.monotonic() - t1) >= 1.5:
                    return b"ERROR: could not get idle state."

        if attempt < retries - 1:
            time.sleep(delay)

    return last_out


def get_ui_snapshot(
    adb: Adb,
    serial: Optional[str] = None,
    compressed: bool = False,
    full_labels: bool = False,
) -> Snapshot:
    """Capture, parse, cache, and return current UI Snapshot."""
    raw_bytes = dump_hierarchy_bytes(adb, serial=serial, compressed=compressed)
    snap_id = get_next_snapshot_id(serial or "default")
    snapshot = parse_ui_tree(raw_bytes, snapshot_id=snap_id, full_labels=full_labels)
    enrich_snapshot_with_window_state(adb, serial=serial, snapshot=snapshot, raw_bytes=raw_bytes)

    if not snapshot.elements and not snapshot.warnings:
        raise LlmadbError(
            code=E_SECURE_OR_EMPTY,
            message="screen is secure or empty",
            hint="FLAG_SECURE screen or non-accessible UI; use `llmadb screen`",
            exit_code=EXIT_SECURE_OR_EMPTY,
        )

    save_snapshot(serial or "default", snapshot)
    return snapshot


def run_ui(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'ui' command."""
    target_serial = resolve_device(adb, explicit_serial=serial)

    full_labels = "--full" in args
    full_bounds = "--bounds" in args
    compressed = "--compressed" in args
    raw_mode = "--raw" in args

    if raw_mode:
        raw_bytes = dump_hierarchy_bytes(adb, serial=target_serial, compressed=compressed)
        sys.stdout.write(raw_bytes.decode("utf-8", errors="replace") + "\n")
        sys.stdout.flush()
        return 0

    snapshot = get_ui_snapshot(
        adb,
        serial=target_serial,
        compressed=compressed,
        full_labels=full_labels,
    )

    output = snapshot.format_tree(full_bounds=full_bounds)
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
