"""Handler for 'list apps' command: package listing, classification, and filtering."""

import sys
from typing import Dict, List, Optional, Set, Tuple

from llmadb.adb import Adb
from llmadb.device import resolve_device
from llmadb.errors import E_USAGE, EXIT_USAGE, LlmadbError
from llmadb.shellbatch import run_batch

VALID_SCOPES = {"user", "system", "vendor", "product", "all"}


def parse_package_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse a line from 'pm list packages -f' into (apk_path, package_name).

    Format: package:/path/to/base.apk=com.example.app
    Paths may contain '=', so split on the last '='.
    """
    line = line.strip()
    if not line.startswith("package:"):
        return None
    body = line[len("package:") :]
    if "=" not in body:
        return ("", body.strip())
    path, pkg = body.rsplit("=", 1)
    return path.strip(), pkg.strip()


def parse_plain_package_set(text: str) -> Set[str]:
    """Parse output of 'pm list packages' (without -f) into a set of package names."""
    pkgs: Set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            pkg = line[len("package:") :].strip()
            if pkg:
                pkgs.add(pkg)
    return pkgs


def classify_package(
    apk_path: str,
    in_system_set: bool = False,
    in_user_set: bool = False,
) -> str:
    """Classify a package by its APK path prefix and pm -s/-3 membership.

    Returns one of: 'user', 'system', 'system*', 'vendor', 'product'.
    """
    if apk_path.startswith("/data/app"):
        if in_system_set:
            return "system*"
        return "user"
    if apk_path.startswith("/vendor/") or apk_path.startswith("/odm/"):
        return "vendor"
    if apk_path.startswith("/product/"):
        return "product"
    if apk_path.startswith("/system/") or apk_path.startswith("/system_ext/"):
        return "system"

    # Fallback when path prefix is non-standard (e.g. /apex, /mnt/asec)
    if in_user_set and not in_system_set:
        return "user"
    return "system"


def format_apps_output(
    classified: Dict[str, str],
    scope: str = "user",
    grep_pattern: Optional[str] = None,
) -> str:
    """Format classified packages according to requested scope and grep filter."""
    query = grep_pattern.lower() if grep_pattern else None

    def matches_grep(pkg: str) -> bool:
        return query is None or query in pkg.lower()

    if scope == "user":
        items = sorted(
            pkg
            for pkg, cat in classified.items()
            if cat == "user" and matches_grep(pkg)
        )
        return "\n".join(items)

    if scope == "system":
        items = []
        for pkg in sorted(classified.keys()):
            cat = classified[pkg]
            if cat in ("system", "system*") and matches_grep(pkg):
                items.append(f"{pkg}\tsystem*" if cat == "system*" else pkg)
        return "\n".join(items)

    if scope == "vendor":
        items = sorted(
            pkg
            for pkg, cat in classified.items()
            if cat == "vendor" and matches_grep(pkg)
        )
        return "\n".join(items)

    if scope == "product":
        items = sorted(
            pkg
            for pkg, cat in classified.items()
            if cat == "product" and matches_grep(pkg)
        )
        return "\n".join(items)

    if scope == "all":
        sections = [
            ("user", ("user",)),
            ("system", ("system", "system*")),
            ("vendor", ("vendor",)),
            ("product", ("product",)),
        ]
        blocks: List[str] = []
        for header, cats in sections:
            sec_lines: List[str] = []
            for pkg in sorted(classified.keys()):
                cat = classified[pkg]
                if cat in cats and matches_grep(pkg):
                    sec_lines.append(f"{pkg}\tsystem*" if cat == "system*" else pkg)
            if sec_lines:
                blocks.append(f"[{header}]\n" + "\n".join(sec_lines))
        return "\n\n".join(blocks)

    return ""


def run_list_apps(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'list apps [user|system|vendor|all] [--grep S] [--disabled] [--enabled]'."""
    # Allow optional leading 'apps' subcommand token
    work_args = list(args)
    if work_args and work_args[0] == "apps":
        work_args = work_args[1:]
    elif work_args and not work_args[0].startswith("-") and work_args[0] not in VALID_SCOPES:
        raise LlmadbError(
            code=E_USAGE,
            message=f"unknown list target '{work_args[0]}'",
            hint="usage: llmadb list apps [user|system|vendor|all] [--grep S] [--disabled] [--enabled]",
            exit_code=EXIT_USAGE,
        )

    scope = "user"
    grep_pattern: Optional[str] = None
    only_disabled = False
    only_enabled = False

    idx = 0
    while idx < len(work_args):
        a = work_args[idx]
        if a == "--grep":
            if idx + 1 >= len(work_args):
                raise LlmadbError(
                    code=E_USAGE,
                    message="option --grep requires an argument",
                    hint="specify substring filter (e.g. --grep samsung)",
                    exit_code=EXIT_USAGE,
                )
            grep_pattern = work_args[idx + 1]
            idx += 2
        elif a.startswith("--grep="):
            grep_pattern = a.split("=", 1)[1]
            idx += 1
        elif a == "--disabled":
            only_disabled = True
            idx += 1
        elif a == "--enabled":
            only_enabled = True
            idx += 1
        elif not a.startswith("-"):
            if a not in VALID_SCOPES:
                raise LlmadbError(
                    code=E_USAGE,
                    message=f"invalid package scope '{a}'",
                    hint="supported scopes: user, system, vendor, product, all",
                    exit_code=EXIT_USAGE,
                )
            scope = a
            idx += 1
        else:
            raise LlmadbError(
                code=E_USAGE,
                message=f"unknown option '{a}'",
                hint="usage: llmadb list apps [user|system|vendor|all] [--grep S] [--disabled] [--enabled]",
                exit_code=EXIT_USAGE,
            )

    if only_disabled and only_enabled:
        raise LlmadbError(
            code=E_USAGE,
            message="cannot combine --disabled and --enabled",
            hint="use either --disabled or --enabled",
            exit_code=EXIT_USAGE,
        )

    target_serial = resolve_device(adb, explicit_serial=serial)

    batch_cmds = {
        "all_f": "pm list packages -f",
        "user_3": "pm list packages -3",
        "sys_s": "pm list packages -s",
    }
    if only_disabled:
        batch_cmds["state_filter"] = "pm list packages -d"
    elif only_enabled:
        batch_cmds["state_filter"] = "pm list packages -e"

    raw = run_batch(adb, batch_cmds, serial=target_serial, timeout=15.0)
    user_set = parse_plain_package_set(raw.get("user_3", ""))
    sys_set = parse_plain_package_set(raw.get("sys_s", ""))
    allowed_set: Optional[Set[str]] = None
    if "state_filter" in batch_cmds:
        allowed_set = parse_plain_package_set(raw.get("state_filter", ""))

    classified: Dict[str, str] = {}
    for line in raw.get("all_f", "").splitlines():
        parsed = parse_package_line(line)
        if not parsed:
            continue
        apk_path, pkg = parsed
        if allowed_set is not None and pkg not in allowed_set:
            continue
        classified[pkg] = classify_package(
            apk_path=apk_path,
            in_system_set=(pkg in sys_set),
            in_user_set=(pkg in user_set),
        )

    output = format_apps_output(classified, scope=scope, grep_pattern=grep_pattern)
    if not output:
        return 0

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
