"""Handlers for 'log' and 'mark' commands: logcat filtering, PID resolution, and deduplication."""

import re
import sys
from typing import List, Optional, Set, Tuple

from llmadb.adb import Adb
from llmadb.cache import load_mark, save_mark
from llmadb.device import resolve_device
from llmadb.errors import E_USAGE, EXIT_USAGE, LlmadbError

# Standard threadtime format:
# 10-18 02:23:45.123  1234  5678 I ActivityManager: Displayed ...
THREADTIME_RE = re.compile(
    r"^(\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\.\d+\s+(\d+)\s+(\d+)\s+([VDIWEFS])\s+(.*?):\s?(.*)$"
)

LEVEL_ORDER = {"V": 0, "D": 1, "I": 2, "W": 3, "E": 4, "F": 5, "S": 6}


def resolve_package_pids(adb: Adb, pkg: str, serial: str) -> Set[str]:
    """Resolve active PIDs for a package via pidof with ps fallback."""
    res = adb.run(["shell", f"pidof {pkg} 2>/dev/null"], serial=serial, timeout=5.0)
    pids = {p for p in res.text.strip().split() if p.isdigit()}
    if pids:
        return pids

    # Fallback for older Android builds where pidof may not match all processes
    ps_res = adb.run(["shell", f"ps | grep {pkg}"], serial=serial, timeout=5.0)
    for line in ps_res.text.splitlines():
        parts = line.split()
        # Android ps format: USER PID PPID VSIZE RSS WCHAN PC S NAME
        if len(parts) >= 2 and parts[-1].startswith(pkg) and parts[1].isdigit():
            pids.add(parts[1])
    return pids


def format_and_collapse_logs(
    raw_text: str,
    min_level: str = "V",
    full_timestamps: bool = False,
    allowed_pids: Optional[Set[str]] = None,
    pkg_fallback: Optional[str] = None,
) -> List[str]:
    """Filter, strip sub-second timestamps, and collapse consecutive duplicate log lines."""
    min_rank = LEVEL_ORDER.get(min_level.upper(), 0)

    # Entries hold (formatted_line, dedup_key)
    entries: List[Tuple[str, Tuple[str, str, str]]] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip("\r")
        if not line or line.startswith("--------- beginning of"):
            continue

        m = THREADTIME_RE.match(line)
        if not m:
            # Non-threadtime continuation line (e.g. stack trace line)
            if allowed_pids is not None and not allowed_pids:
                if pkg_fallback and pkg_fallback not in line:
                    continue
            entries.append((line, ("RAW", "", line.strip())))
            continue

        date_part, time_part, pid, _tid, level, tag, msg = m.groups()
        tag_clean = tag.strip()

        if LEVEL_ORDER.get(level, 0) < min_rank:
            continue

        if allowed_pids is not None:
            if allowed_pids:
                if pid not in allowed_pids:
                    continue
            elif pkg_fallback:
                # Process no longer running; match package name in tag or message
                if pkg_fallback.lower() not in tag_clean.lower() and pkg_fallback.lower() not in msg.lower():
                    continue

        if full_timestamps:
            formatted = line
        else:
            formatted = f"{date_part} {time_part} {level} {tag_clean}: {msg}"

        dedup_key = (level, tag_clean, msg)
        entries.append((formatted, dedup_key))

    # Collapse consecutive identical (level, tag, msg) lines
    collapsed: List[str] = []
    idx = 0
    while idx < len(entries):
        base_line, base_key = entries[idx]
        count = 1
        while idx + count < len(entries) and entries[idx + count][1] == base_key:
            count += 1
        if count > 1:
            collapsed.append(f"{base_line} ... x{count}")
        else:
            collapsed.append(base_line)
        idx += count

    return collapsed


def run_mark(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'mark': record current device timestamp for subsequent 'log --since-mark'."""
    target_serial = resolve_device(adb, explicit_serial=serial)
    res = adb.run(
        ["shell", 'date +"%m-%d %H:%M:%S.000"'],
        serial=target_serial,
        timeout=5.0,
        check=True,
    )
    mark_str = res.text.strip()
    save_mark(target_serial, mark_str)
    sys.stdout.write(f"mark={mark_str}\n")
    sys.stdout.flush()
    return 0


def run_log(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'log [--pkg P] [--level W] [-n 200] [--since-mark] [--crash] [--full]'."""
    pkg: Optional[str] = None
    level = "V"
    tail_count = 200
    since_mark = False
    crash_only = False
    full_mode = False

    idx = 0
    while idx < len(args):
        a = args[idx]
        if a == "--pkg":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "option --pkg requires package name", "specify --pkg <package>", EXIT_USAGE)
            pkg = args[idx + 1]
            idx += 2
        elif a.startswith("--pkg="):
            pkg = a.split("=", 1)[1]
            idx += 1
        elif a == "--level":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "option --level requires level (V/D/I/W/E/F)", "e.g. --level W", EXIT_USAGE)
            level = args[idx + 1].upper()
            idx += 2
        elif a.startswith("--level="):
            level = a.split("=", 1)[1].upper()
            idx += 1
        elif a in ("-n", "--lines"):
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, f"option {a} requires integer", "e.g. -n 200", EXIT_USAGE)
            try:
                tail_count = int(args[idx + 1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid line count: {args[idx + 1]}", "specify integer for -n", EXIT_USAGE)
            idx += 2
        elif a.startswith("-n") and len(a) > 2:
            try:
                tail_count = int(a[2:])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid line count: {a}", "specify integer for -n", EXIT_USAGE)
            idx += 1
        elif a == "--since-mark":
            since_mark = True
            idx += 1
        elif a == "--crash":
            crash_only = True
            idx += 1
        elif a == "--full":
            full_mode = True
            idx += 1
        else:
            raise LlmadbError(
                code=E_USAGE,
                message=f"unknown log option '{a}'",
                hint="usage: llmadb log [--pkg P] [--level W] [-n 200] [--since-mark] [--crash] [--full]",
                exit_code=EXIT_USAGE,
            )

    if level not in LEVEL_ORDER:
        raise LlmadbError(
            code=E_USAGE,
            message=f"invalid log level '{level}'",
            hint="supported levels: V, D, I, W, E, F",
            exit_code=EXIT_USAGE,
        )

    target_serial = resolve_device(adb, explicit_serial=serial)

    allowed_pids: Optional[Set[str]] = None
    if pkg:
        allowed_pids = resolve_package_pids(adb, pkg, serial=target_serial)

    log_cmd = ["logcat", "-d", "-v", "threadtime"]
    if crash_only:
        log_cmd.extend(["-b", "crash"])

    if since_mark:
        mark_val = load_mark(target_serial)
        if not mark_val:
            raise LlmadbError(
                code=E_USAGE,
                message="no log mark found for device",
                hint="run 'llmadb mark' before 'llmadb log --since-mark'",
                exit_code=EXIT_USAGE,
            )
        log_cmd.extend(["-T", f"'{mark_val}'"])

    if level != "V":
        log_cmd.append(f"*:{level}")

    # Try native --pid if single PID resolved; fall back if logcat rejects --pid
    raw_text = ""
    if allowed_pids and len(allowed_pids) == 1:
        single_pid = next(iter(allowed_pids))
        pid_cmd = list(log_cmd) + ["--pid", single_pid]
        res = adb.run(["shell", *pid_cmd], serial=target_serial, timeout=10.0)
        if res.code == 0 and "invalid option" not in res.stderr_text.lower() and "unrecognized option" not in res.stderr_text.lower():
            raw_text = res.text

    if not raw_text:
        res = adb.run(["shell", *log_cmd], serial=target_serial, timeout=10.0)
        raw_text = res.text

    lines = format_and_collapse_logs(
        raw_text=raw_text,
        min_level=level,
        full_timestamps=full_mode,
        allowed_pids=allowed_pids,
        pkg_fallback=pkg,
    )

    if tail_count > 0 and len(lines) > tail_count:
        lines = lines[-tail_count:]

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
