"""Command-line interface and argument dispatcher for llm-adb (llmadb CLI)."""

import os
import sys
from typing import List, Optional, Tuple

from llmadb import __version__
from llmadb.adb import Adb
from llmadb.commands.apps import run_list_apps
from llmadb.commands.cache_cmd import run_clear_cache
from llmadb.commands.current import run_current
from llmadb.commands.devices import run_devices
from llmadb.commands.hardware import run_hardware
from llmadb.commands.info import run_info
from llmadb.commands.input import run_key, run_swipe, run_type
from llmadb.commands.launch import run_clear, run_launch, run_stop
from llmadb.commands.log import run_log, run_mark
from llmadb.commands.rotate import run_rotate
from llmadb.commands.screen import run_screen
from llmadb.commands.status import run_status
from llmadb.commands.tap import run_tap
from llmadb.commands.ui import run_ui
from llmadb.commands.waitfor import run_waitfor
from llmadb.errors import (
    E_USAGE,
    EXIT_USAGE,
    LlmadbError,
)

# Server-level adb commands that never take a device serial (-s)
SERVER_COMMANDS = {
    "start-server",
    "kill-server",
    "version",
    "connect",
    "disconnect",
    "pair",
    "help",
}

# Subcommands owned and handled by llmadb
OWNED_COMMANDS = {
    "devices",
    "hardware",
    "ui",
    "screen",
    "tap",
    "type",
    "swipe",
    "key",
    "wait-for",
    "current",
    "rotate",
    "status",
    "clear-cache",
    "list",
    "info",
    "launch",
    "stop",
    "clear",
    "log",
    "mark",
}

HELP_LLM_TEXT = """llm-adb: Token-efficient ADB wrapper for LLM agents.
Rules:
- Call llmadb instead of adb for device inspection and control.
- Output is compact line-based text; errors follow 'error: <code> <message> | hint: <hint>'.
Commands:
- devices: TSV listing (serial, state, model, transport).
- hardware [--json]: System/display/memory specs.
- status [--json]: Device battery, Wi-Fi, cellular, bluetooth, NFC, and airplane mode status.
- ui [--full] [--bounds] [--compressed] [--raw]: Reduced accessibility hierarchy with indexed elements and overlay/webview warnings.
- screen [--grid N] [--no-grid] [--max-edge 960] [--element N] [--region x1,y1,x2,y2] [--raw] [--no-ui]: Annotated screenshot with 100px device coordinate grid by default.
- tap <idx|--text X|--id Y|x,y> [--hold [MS]] [--snap N] [--diff] [--no-ui] [--wait-settle]: Tap or long-press target; dumps settled UI.
- type "<text>" [--clear] [--enter] [--diff] [--no-ui]: Type ASCII text.
- swipe <up|down|left|right|x1,y1 x2,y2> [--dist F] [--dur MS] [--diff] [--no-ui]: Swipe gesture.
- key <home|back|enter|tab|menu|power|volup|voldown|recents|delete|CODE> [--diff] [--no-ui]: Send keyevent.
- wait-for <--text X|--id Y|--gone X> [--timeout S]: Poll UI at 500ms until condition met.
- current: Foreground app/activity, orientation, keyboard state.
- rotate [0|1|portrait|landscape|auto]: Toggle or set screen orientation, return current rotation.
- clear-cache [--all]: Clear cached screenshots and snapshots.
- list apps [user|system|vendor|product|all] [--grep S] [--disabled] [--enabled]: Filtered package list.
- info <pkg>: Condensed package metadata, launcher activity, PID, and permissions.
- launch <pkg> | stop <pkg> | clear <pkg>: App lifecycle management.
- mark | log [--pkg P] [--level W] [-n 200] [--since-mark] [--crash] [--full]: Deduplicated logcat.
- passthrough: Any raw adb command ('llmadb shell ...', 'llmadb -- devices').
"""

USAGE_TEXT = f"""llm-adb v{__version__} - Token-efficient ADB wrapper for LLM agents

Usage:
  llmadb [--device SERIAL] [--timeout SECONDS] [--max-lines N] <command> [args...]
  llmadb -- <adb-command> [args...]

Global Options:
  -s, --device SERIAL   Target device serial (env: LLMADB_SERIAL, ANDROID_SERIAL)
  --timeout SECONDS     Command timeout in seconds
  --max-lines N         Truncate output to N lines (appends '[truncated: M more lines]')
  --help-llm            Print short usage block for LLM instructions
  -h, --help            Show this help message
  -v, --version         Show version

Commands:
  devices               List connected devices (TSV: serial, state, model, transport)
  hardware              Device specs, display resolution/DPI, memory, storage, root
  status                Connectivity and battery status report
  ui                    Dump reduced UI hierarchy with element indices
  screen                Capture annotated screenshot or coordinate grid
  tap                   Tap or long-press (--hold [MS]) element by index, --text, --id, or x,y coordinates
  type                  Enter text (--clear, --enter)
  swipe                 Swipe up/down/left/right or x1,y1 x2,y2
  key                   Press hardware/navigation key
  wait-for              Poll UI until --text, --id, or --gone matches
  current               Foreground package/activity, rotation, and keyboard state
  rotate                Toggle or set orientation (0/1/portrait/landscape/auto)
  clear-cache           Purge host-side screenshot and snapshot cache
  list apps             List packages by scope (user, system, vendor, product, all)
  info                  Condensed package info, permissions, launcher, and PID
  launch / stop / clear Start, force-stop, or clear app data
  mark / log            Save device timestamp mark and query deduplicated logcat
  (Other commands passthrough directly to adb)
"""


def init_console() -> None:
    """Ensure UTF-8 encoding on standard streams, especially on Windows."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


def parse_global_args(
    argv: List[str],
) -> Tuple[Optional[str], Optional[float], Optional[int], bool, bool, bool, bool, List[str]]:
    """Parse global options from argv.
    
    Returns:
      (serial, timeout, max_lines, help_llm, show_help, show_version, escape_passthrough, remaining_args)
    """
    serial: Optional[str] = None
    timeout: Optional[float] = None
    max_lines: Optional[int] = None
    help_llm = False
    show_help = False
    show_version = False
    escape_passthrough = False

    remaining: List[str] = []
    idx = 0

    while idx < len(argv):
        arg = argv[idx]

        if escape_passthrough:
            remaining.append(arg)
            idx += 1
            continue

        if arg == "--":
            escape_passthrough = True
            # Remaining args are raw passthrough
            idx += 1
            continue

        if arg in ("-s", "--device"):
            if idx + 1 >= len(argv):
                raise LlmadbError(
                    code=E_USAGE,
                    message="option requires an argument: -s / --device",
                    hint="provide device serial after -s / --device",
                    exit_code=EXIT_USAGE,
                )
            serial = argv[idx + 1]
            idx += 2
        elif arg.startswith("-s") and len(arg) > 2:
            serial = arg[2:]
            idx += 1
        elif arg.startswith("--device="):
            serial = arg.split("=", 1)[1]
            idx += 1
        elif arg == "--timeout":
            if idx + 1 >= len(argv):
                raise LlmadbError(
                    code=E_USAGE,
                    message="option requires an argument: --timeout",
                    hint="specify timeout in seconds (e.g. --timeout 10)",
                    exit_code=EXIT_USAGE,
                )
            try:
                timeout = float(argv[idx + 1])
            except ValueError:
                raise LlmadbError(
                    code=E_USAGE,
                    message=f"invalid timeout value: {argv[idx + 1]}",
                    hint="specify timeout as a number in seconds",
                    exit_code=EXIT_USAGE,
                )
            idx += 2
        elif arg.startswith("--timeout="):
            try:
                timeout = float(arg.split("=", 1)[1])
            except ValueError:
                raise LlmadbError(
                    code=E_USAGE,
                    message=f"invalid timeout value: {arg.split('=', 1)[1]}",
                    hint="specify timeout as a number in seconds",
                    exit_code=EXIT_USAGE,
                )
            idx += 1
        elif arg == "--max-lines":
            if idx + 1 >= len(argv):
                raise LlmadbError(
                    code=E_USAGE,
                    message="option requires an argument: --max-lines",
                    hint="specify line limit as integer (e.g. --max-lines 50)",
                    exit_code=EXIT_USAGE,
                )
            try:
                max_lines = int(argv[idx + 1])
            except ValueError:
                raise LlmadbError(
                    code=E_USAGE,
                    message=f"invalid max-lines value: {argv[idx + 1]}",
                    hint="specify max-lines as an integer",
                    exit_code=EXIT_USAGE,
                )
            idx += 2
        elif arg.startswith("--max-lines="):
            try:
                max_lines = int(arg.split("=", 1)[1])
            except ValueError:
                raise LlmadbError(
                    code=E_USAGE,
                    message=f"invalid max-lines value: {arg.split('=', 1)[1]}",
                    hint="specify max-lines as an integer",
                    exit_code=EXIT_USAGE,
                )
            idx += 1
        elif arg == "--help-llm":
            help_llm = True
            idx += 1
        elif arg in ("-h", "--help"):
            show_help = True
            idx += 1
        elif arg in ("-v", "--version"):
            show_version = True
            idx += 1
        elif arg.startswith("-"):
            # Unknown flag before command, keep in remaining (could be passthrough or command flag)
            remaining.append(arg)
            idx += 1
        else:
            # First non-option argument encountered. Everything from here is command + args
            remaining.extend(argv[idx:])
            break

    return serial, timeout, max_lines, help_llm, show_help, show_version, escape_passthrough, remaining


def resolve_passthrough_serial(
    adb: Adb,
    explicit_serial: Optional[str],
    passthrough_args: List[str],
) -> Optional[str]:
    """Determine if a serial should be injected for passthrough adb execution."""
    if not passthrough_args:
        return explicit_serial

    first_arg = passthrough_args[0]
    if first_arg in SERVER_COMMANDS:
        return None

    # Check if passthrough_args already contains a device specifier
    for i, a in enumerate(passthrough_args):
        if a in ("-s", "-e", "-d"):
            return None
        if a.startswith("-s") and len(a) > 2:
            return None

    if explicit_serial:
        return explicit_serial

    env_serial = os.environ.get("LLMADB_SERIAL") or os.environ.get("ANDROID_SERIAL")
    if env_serial:
        return env_serial

    # Do not inject -s if none specified; let adb use its default single device logic
    return None


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entry point."""
    init_console()

    if argv is None:
        argv = sys.argv[1:]

    adb = Adb()

    try:
        (
            serial,
            timeout,
            max_lines,
            help_llm,
            show_help,
            show_version,
            escape_passthrough,
            cmd_args,
        ) = parse_global_args(argv)

        adb.default_timeout = timeout

        if help_llm:
            sys.stdout.write(HELP_LLM_TEXT)
            sys.stdout.flush()
            return 0

        if show_version:
            sys.stdout.write(f"llmadb {__version__}\n")
            sys.stdout.flush()
            return 0

        if not cmd_args:
            if show_help:
                sys.stdout.write(USAGE_TEXT)
                sys.stdout.flush()
                return 0
            # No args provided: pass through to raw adb (shows adb help)
            return adb.exec_passthrough([])

        subcommand = cmd_args[0]
        sub_args = cmd_args[1:]

        # Handle help flag on owned commands
        if show_help and subcommand not in OWNED_COMMANDS:
            # Pass --help through to adb
            passthrough_args = [subcommand] + sub_args + ["--help"]
            return adb.exec_passthrough(passthrough_args)

        # Check for owned commands, unless escaped via '--'
        if not escape_passthrough:
            if subcommand == "devices":
                return run_devices(sub_args, adb, max_lines=max_lines)
            if subcommand == "hardware":
                return run_hardware(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "ui":
                return run_ui(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "tap":
                return run_tap(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "screen":
                return run_screen(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "current":
                return run_current(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "rotate":
                return run_rotate(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "status":
                return run_status(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "clear-cache":
                return run_clear_cache(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "type":
                return run_type(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "swipe":
                return run_swipe(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "key":
                return run_key(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "wait-for":
                return run_waitfor(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "list":
                return run_list_apps(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "info":
                return run_info(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "launch":
                return run_launch(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "stop":
                return run_stop(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "clear":
                return run_clear(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "log":
                return run_log(sub_args, adb, serial=serial, max_lines=max_lines)
            if subcommand == "mark":
                return run_mark(sub_args, adb, serial=serial, max_lines=max_lines)

        # All unowned or escaped subcommands pass through transparently to adb
        passthrough_serial = resolve_passthrough_serial(adb, serial, cmd_args)
        return adb.exec_passthrough(cmd_args, serial=passthrough_serial)

    except LlmadbError as err:
        sys.stderr.write(err.format_line() + "\n")
        sys.stderr.flush()
        return err.exit_code
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        sys.stderr.write(f"error: E_GENERIC {exc} | hint: unexpected error, report bug\n")
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    sys.exit(main())
