"""Handler for 'tap' command with target resolution and post-action UI settling."""

import difflib
import sys
import time
from typing import List, Optional, Tuple

from llmadb.adb import Adb
from llmadb.cache import (
    compute_content_hash,
    get_next_snapshot_id,
    load_snapshot,
    save_snapshot,
)
from llmadb.commands.ui import dump_hierarchy_bytes, enrich_snapshot_with_window_state
from llmadb.device import resolve_device
from llmadb.errors import (
    E_AMBIGUOUS,
    E_NOT_FOUND,
    E_USAGE,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    LlmadbError,
)
from llmadb.uitree import Element, Snapshot, format_snapshot_diff, parse_ui_tree


def settle_ui(
    adb: Adb,
    serial: str,
    timeout: float = 2.0,
    interval: float = 0.25,
    wait_settle: bool = False,
) -> Snapshot:
    """Wait for UI to settle. Fast by default (150ms animation pause + single dump)."""
    time.sleep(0.15)
    raw_bytes = dump_hierarchy_bytes(adb, serial=serial)

    if wait_settle and b"could not get idle state" not in raw_bytes:
        start_time = time.time()
        last_hash = compute_content_hash(raw_bytes)
        while time.time() - start_time < timeout:
            time.sleep(interval)
            next_bytes = dump_hierarchy_bytes(adb, serial=serial)
            current_hash = compute_content_hash(next_bytes)
            raw_bytes = next_bytes
            if current_hash == last_hash or b"could not get idle state" in next_bytes:
                break
            last_hash = current_hash

    snap_id = get_next_snapshot_id(serial)
    snapshot = parse_ui_tree(raw_bytes, snapshot_id=snap_id)
    enrich_snapshot_with_window_state(adb, serial=serial, snapshot=snapshot, raw_bytes=raw_bytes)
    save_snapshot(serial, snapshot)
    return snapshot


def _safe_element_tap_point(el: Element, snapshot: Snapshot) -> Tuple[int, int]:
    """Return tap (x, y) for element, clamping away from bottom gesture navigation inset."""
    cx, cy = el.center
    screen_h = snapshot.screen_height
    if screen_h > 0:
        gesture_cutoff = screen_h - 66
        y1 = el.bounds[1]
        if cy >= gesture_cutoff and y1 < gesture_cutoff:
            safe_y = min(gesture_cutoff - 4, (y1 + gesture_cutoff) // 2)
            cy = max(y1 + 2, safe_y)
    return cx, cy


def resolve_tap_target(
    target_arg: str,
    text_query: Optional[str],
    id_query: Optional[str],
    snapshot: Optional[Snapshot],
    expected_snap_id: Optional[int],
) -> Tuple[int, int, str]:
    """Resolve target to (x, y, description)."""
    # Case 1: Explicit coordinates "x,y"
    if target_arg and "," in target_arg:
        parts = target_arg.split(",", 1)
        try:
            x, y = int(parts[0].strip()), int(parts[1].strip())
            desc = f"coords @{x},{y}"
            if snapshot and snapshot.elements:
                containing = [
                    el for el in snapshot.elements
                    if el.bounds[0] <= x <= el.bounds[2] and el.bounds[1] <= y <= el.bounds[3]
                ]
                if containing:
                    best = min(
                        containing,
                        key=lambda e: (e.bounds[2] - e.bounds[0]) * (e.bounds[3] - e.bounds[1]),
                    )
                    desc = f'coords @{x},{y} (hits #{best.idx} [{best.node_type}] "{best.label}")'
            return x, y, desc
        except ValueError:
            pass

    if snapshot is None:
        raise LlmadbError(
            code=E_NOT_FOUND,
            message="no UI snapshot available to resolve target",
            hint="run `llmadb ui` before tapping by index, id, or text",
            exit_code=EXIT_NOT_FOUND,
        )

    if expected_snap_id is not None and snapshot.id != expected_snap_id:
        raise LlmadbError(
            code=E_NOT_FOUND,
            message=f"stale snapshot: requested snap={expected_snap_id} but latest is snap={snapshot.id}",
            hint="run `llmadb ui` to refresh UI snapshot",
            exit_code=EXIT_NOT_FOUND,
        )

    # Case 2: Target by index (numeric string)
    if target_arg and target_arg.isdigit():
        target_idx = int(target_arg)
        match = next((el for el in snapshot.elements if el.idx == target_idx), None)
        if not match:
            raise LlmadbError(
                code=E_NOT_FOUND,
                message=f"element index #{target_idx} not found in snap={snapshot.id}",
                hint="run `llmadb ui` to inspect available indices",
                exit_code=EXIT_NOT_FOUND,
            )
        tx, ty = _safe_element_tap_point(match, snapshot)
        return tx, ty, f"#{match.idx} [{match.node_type}] \"{match.label}\""

    # Case 3: Target by --id
    if id_query:
        matches = [
            el for el in snapshot.elements
            if el.short_id == id_query or el.resource_id.endswith(f"/{id_query}") or el.resource_id == id_query
        ]
        if not matches:
            available_ids = [el.short_id for el in snapshot.elements if el.short_id]
            hint = f"available ids: {', '.join(available_ids[:5])}" if available_ids else "run `llmadb ui`"
            raise LlmadbError(
                code=E_NOT_FOUND,
                message=f"no element with id '{id_query}' found",
                hint=hint,
                exit_code=EXIT_NOT_FOUND,
            )
        if len(matches) > 1:
            candidates = [f"#{m.idx} @{m.center[0]},{m.center[1]}" for m in matches]
            raise LlmadbError(
                code=E_AMBIGUOUS,
                message=f"id '{id_query}' matches {len(matches)} elements: {', '.join(candidates)}",
                hint="target specific element index (e.g. tap 3)",
                exit_code=EXIT_NOT_FOUND,
            )
        m = matches[0]
        tx, ty = _safe_element_tap_point(m, snapshot)
        return tx, ty, f"id={id_query} (#{m.idx})"

    # Case 4: Target by --text
    if text_query:
        # Exact match first
        exact_matches = [el for el in snapshot.elements if el.label == text_query]
        if len(exact_matches) == 1:
            m = exact_matches[0]
            tx, ty = _safe_element_tap_point(m, snapshot)
            return tx, ty, f"#{m.idx} \"{m.label}\""
        if len(exact_matches) > 1:
            candidates = [f"#{m.idx} @{m.center[0]},{m.center[1]}" for m in exact_matches]
            raise LlmadbError(
                code=E_AMBIGUOUS,
                message=f"text '{text_query}' matches {len(exact_matches)} elements: {', '.join(candidates)}",
                hint="target specific element index (e.g. tap 2)",
                exit_code=EXIT_NOT_FOUND,
            )

        # Case-insensitive substring match
        query_lower = text_query.lower()
        sub_matches = [el for el in snapshot.elements if query_lower in el.label.lower()]
        if len(sub_matches) == 1:
            m = sub_matches[0]
            tx, ty = _safe_element_tap_point(m, snapshot)
            return tx, ty, f"#{m.idx} \"{m.label}\""
        if len(sub_matches) > 1:
            candidates = [f"#{m.idx} \"{m.label}\"" for m in sub_matches]
            raise LlmadbError(
                code=E_AMBIGUOUS,
                message=f"text query '{text_query}' matches {len(sub_matches)} elements: {', '.join(candidates)}",
                hint="target specific element index (e.g. tap 4)",
                exit_code=EXIT_NOT_FOUND,
            )

        # No match found, find closest
        labels = [el.label for el in snapshot.elements if el.label]
        closest = difflib.get_close_matches(text_query, labels, n=3, cutoff=0.3)
        hint = f"closest labels: {', '.join(repr(c) for c in closest)}" if closest else "run `llmadb ui` to inspect labels"
        raise LlmadbError(
            code=E_NOT_FOUND,
            message=f"element with text '{text_query}' not found",
            hint=hint,
            exit_code=EXIT_NOT_FOUND,
        )

    raise LlmadbError(
        code=E_USAGE,
        message="missing tap target",
        hint="provide index ('tap 5'), text ('tap --text \"Submit\"'), id ('tap --id btn'), or coords ('tap 100,200')",
        exit_code=EXIT_USAGE,
    )


DEFAULT_HOLD_MS = 500
VALUE_FLAGS = {"--text", "--id", "--snap", "--settle-timeout"}


def _parse_hold_ms(raw: str) -> int:
    try:
        val = int(raw)
    except ValueError:
        raise LlmadbError(
            code=E_USAGE,
            message=f"invalid hold duration: {raw}",
            hint="hold duration must be positive integer in milliseconds (e.g. --hold 500)",
            exit_code=EXIT_USAGE,
        )
    if val <= 0:
        raise LlmadbError(
            code=E_USAGE,
            message=f"invalid hold duration: {raw}",
            hint="hold duration must be positive integer in milliseconds (e.g. --hold 500)",
            exit_code=EXIT_USAGE,
        )
    return val


def _has_positional_after(args: List[str], start_idx: int) -> bool:
    """Return True if another non-option target token exists at or after start_idx."""
    i = start_idx
    while i < len(args):
        tok = args[i]
        if tok in VALUE_FLAGS:
            i += 2
        elif tok.startswith("-"):
            i += 1
        else:
            return True
    return False


def run_tap(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Execute tap (or hold) and optionally output settled UI."""
    # Parse arguments
    target_arg = ""
    text_query: Optional[str] = None
    id_query: Optional[str] = None
    expected_snap_id: Optional[int] = None
    hold_ms: Optional[int] = None
    no_ui = "--no-ui" in args
    diff_mode = "--diff" in args
    wait_settle = "--wait-settle" in args
    settle_timeout = 2.0

    has_query_target = any(
        a in ("--text", "--id") or a.startswith("--text=") or a.startswith("--id=")
        for a in args
    )

    idx = 0
    while idx < len(args):
        a = args[idx]
        if a == "--text":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "option --text requires argument", "specify text query", EXIT_USAGE)
            text_query = args[idx + 1]
            idx += 2
        elif a.startswith("--text="):
            text_query = a.split("=", 1)[1]
            idx += 1
        elif a == "--id":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "option --id requires argument", "specify short resource id", EXIT_USAGE)
            id_query = args[idx + 1]
            idx += 2
        elif a.startswith("--id="):
            id_query = a.split("=", 1)[1]
            idx += 1
        elif a == "--snap":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "option --snap requires integer", "specify snapshot id", EXIT_USAGE)
            try:
                expected_snap_id = int(args[idx + 1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid snap id: {args[idx + 1]}", "snap must be integer", EXIT_USAGE)
            idx += 2
        elif a.startswith("--snap="):
            try:
                expected_snap_id = int(a.split("=", 1)[1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid snap id: {a}", "snap must be integer", EXIT_USAGE)
            idx += 1
        elif a == "--hold":
            if idx + 1 < len(args):
                next_arg = args[idx + 1]
                is_flag = next_arg.startswith("--") or (
                    next_arg.startswith("-") and not next_arg[1:].isdigit()
                )
                has_other_target = (
                    bool(target_arg)
                    or has_query_target
                    or _has_positional_after(args, idx + 2)
                )
                if not is_flag and "," not in next_arg and has_other_target:
                    hold_ms = _parse_hold_ms(next_arg)
                    idx += 2
                    continue
            hold_ms = DEFAULT_HOLD_MS
            idx += 1
        elif a.startswith("--hold="):
            hold_ms = _parse_hold_ms(a.split("=", 1)[1])
            idx += 1
        elif a == "--settle-timeout":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "option --settle-timeout requires float", "specify timeout in seconds", EXIT_USAGE)
            try:
                settle_timeout = float(args[idx + 1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid settle timeout: {args[idx + 1]}", "must be number", EXIT_USAGE)
            idx += 2
        elif a.startswith("--settle-timeout="):
            try:
                settle_timeout = float(a.split("=", 1)[1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid settle timeout: {a}", "must be number", EXIT_USAGE)
            idx += 1
        elif a in ("--no-ui", "--diff", "--wait-settle"):
            idx += 1
        elif not target_arg and not a.startswith("-"):
            target_arg = a
            idx += 1
        else:
            raise LlmadbError(
                code=E_USAGE,
                message=f"unknown tap option or extra argument '{a}'",
                hint="usage: llmadb tap <idx|--text X|--id Y|x,y> [--hold [MS]] [--snap N] [--diff] [--no-ui] [--wait-settle]",
                exit_code=EXIT_USAGE,
            )

    target_serial = resolve_device(adb, explicit_serial=serial)
    latest_snapshot = load_snapshot(target_serial)
    cx, cy, desc = resolve_tap_target(
        target_arg=target_arg,
        text_query=text_query,
        id_query=id_query,
        snapshot=latest_snapshot,
        expected_snap_id=expected_snap_id,
    )

    if hold_ms is not None:
        cmd_timeout = max(5.0, hold_ms / 1000.0 + 5.0)
        adb.run(
            ["shell", "input", "swipe", str(cx), str(cy), str(cx), str(cy), str(hold_ms)],
            serial=target_serial,
            timeout=cmd_timeout,
        )
    else:
        adb.run(["shell", "input", "tap", str(cx), str(cy)], serial=target_serial, timeout=5.0)

    if no_ui:
        suffix = f" (hold {hold_ms}ms)" if hold_ms is not None else ""
        sys.stdout.write(f"tapped {desc} @{cx},{cy}{suffix}\n")
        sys.stdout.flush()
        return 0

    # Wait for UI to settle and print updated UI
    new_snapshot = settle_ui(adb, serial=target_serial, timeout=settle_timeout, wait_settle=wait_settle)
    if diff_mode:
        output = format_snapshot_diff(latest_snapshot, new_snapshot)
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
