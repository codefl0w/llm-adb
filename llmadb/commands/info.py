"""Handler for 'info' command: condensed package metadata, permissions, and runtime state."""

import re
import sys
from typing import Any, Dict, List, Optional

from llmadb.adb import Adb
from llmadb.device import resolve_device
from llmadb.errors import (
    E_NOT_FOUND,
    E_USAGE,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    LlmadbError,
)
from llmadb.shellbatch import run_batch

VERSION_CODE_RE = re.compile(r"versionCode=(\d+)")
MIN_SDK_RE = re.compile(r"minSdk=(\d+)")
TARGET_SDK_RE = re.compile(r"targetSdk=(\d+)")
VERSION_NAME_RE = re.compile(r"versionName=([^\s]+)")
INSTALLER_RE = re.compile(r"installerPackageName=([^\s]+)")
FIRST_INSTALL_RE = re.compile(r"firstInstallTime=([^\r\n]+)")
LAST_UPDATE_RE = re.compile(r"lastUpdateTime=([^\r\n]+)")
ENABLED_RE = re.compile(r"enabled=(\d+)")
RUNTIME_PERM_RE = re.compile(
    r"^\s*([a-zA-Z0-9_.]+):\s*granted=(true|false)", re.MULTILINE
)
COMPONENT_LINE_RE = re.compile(r"([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)")

ENABLED_MAP = {
    "0": "default",
    "1": "enabled",
    "2": "disabled",
    "3": "disabled_user",
    "4": "disabled_until_used",
}


def shorten_permission(perm: str) -> str:
    """Shorten standard android.permission.X names to X."""
    prefix = "android.permission."
    if perm.startswith(prefix):
        return perm[len(prefix) :]
    return perm


def extract_launcher_from_dumpsys(dumpsys_text: str, pkg: str) -> str:
    """Fallback extraction of MAIN/LAUNCHER activity from dumpsys package output."""
    lines = dumpsys_text.splitlines()
    in_main = False
    candidate = ""
    for line in lines:
        stripped = line.strip()
        if "android.intent.action.MAIN:" in stripped:
            in_main = True
            continue
        if in_main:
            # New intent action section starts
            if stripped.startswith("android.intent.action.") and "MAIN" not in stripped:
                break
            if "Non-Data Actions:" in stripped or "MIME Typed Actions:" in stripped:
                break
            m = COMPONENT_LINE_RE.search(stripped)
            if m and m.group(1).startswith(pkg + "/"):
                candidate = m.group(1)
            if "android.intent.category.LAUNCHER" in stripped and candidate:
                return candidate
    return candidate


def parse_package_info(
    pkg: str,
    dumpsys_text: str,
    resolve_text: str = "",
    pid_text: str = "",
) -> Dict[str, Any]:
    """Parse condensed package info from dumpsys, launcher resolution, and pidof."""
    if not dumpsys_text or f"Unable to find package: {pkg}" in dumpsys_text or "Package [" not in dumpsys_text:
        raise LlmadbError(
            code=E_NOT_FOUND,
            message=f"package '{pkg}' not found",
            hint="run 'llmadb list apps all --grep <name>' to find package name",
            exit_code=EXIT_NOT_FOUND,
        )

    # Extract only the main Package [pkg] block to avoid sharedUserId noise
    pkg_header = f"Package [{pkg}]"
    start_idx = dumpsys_text.find(pkg_header)
    section = dumpsys_text[start_idx:] if start_idx != -1 else dumpsys_text

    version_name = ""
    m = VERSION_NAME_RE.search(section)
    if m:
        version_name = m.group(1).strip()

    version_code = ""
    m = VERSION_CODE_RE.search(section)
    if m:
        version_code = m.group(1)

    min_sdk = ""
    m = MIN_SDK_RE.search(section)
    if m:
        min_sdk = m.group(1)

    target_sdk = ""
    m = TARGET_SDK_RE.search(section)
    if m:
        target_sdk = m.group(1)

    debuggable = "DEBUGGABLE" in section

    installer = "none"
    m = INSTALLER_RE.search(section)
    if m and m.group(1) != "null":
        installer = m.group(1)

    first_install = ""
    m = FIRST_INSTALL_RE.search(section)
    if m:
        first_install = m.group(1).strip()

    last_update = ""
    m = LAST_UPDATE_RE.search(section)
    if m:
        last_update = m.group(1).strip()

    enabled_state = "enabled"
    m = ENABLED_RE.search(section)
    if m:
        enabled_state = ENABLED_MAP.get(m.group(1), m.group(1))

    # Runtime permissions (scoped to 'runtime permissions:' block to omit install-time noise)
    granted_perms: List[str] = []
    denied_perms: List[str] = []
    seen_granted = set()
    seen_denied = set()

    rt_idx = section.find("runtime permissions:")
    if rt_idx != -1:
        rt_block_lines: List[str] = []
        for line in section[rt_idx + len("runtime permissions:") :].splitlines():
            if not line.strip():
                continue
            # Stop when indentation returns to User/Package level or another header starts
            indent = len(line) - len(line.lstrip())
            if indent <= 6 and not line.strip().startswith("android.permission.") and ": granted=" not in line:
                break
            rt_block_lines.append(line)
        perm_source = "\n".join(rt_block_lines)
    else:
        perm_source = ""

    for pm in RUNTIME_PERM_RE.finditer(perm_source):
        short_p = shorten_permission(pm.group(1))
        is_granted = pm.group(2) == "true"
        if is_granted:
            if short_p not in seen_granted:
                seen_granted.add(short_p)
                granted_perms.append(short_p)
        else:
            if short_p not in seen_denied:
                seen_denied.add(short_p)
                denied_perms.append(short_p)

    # Launcher activity resolution
    launcher = "none"
    for line in resolve_text.splitlines():
        line = line.strip()
        m_comp = COMPONENT_LINE_RE.search(line)
        if m_comp and m_comp.group(1).startswith(pkg + "/"):
            launcher = m_comp.group(1)
            break
    if launcher == "none":
        fallback = extract_launcher_from_dumpsys(dumpsys_text, pkg)
        if fallback:
            launcher = fallback

    # PID / running state
    pids = [p for p in pid_text.strip().split() if p.isdigit()]
    running = f"pid={','.join(pids)}" if pids else "stopped"

    return {
        "package": pkg,
        "version_name": version_name,
        "version_code": version_code,
        "min_sdk": min_sdk,
        "target_sdk": target_sdk,
        "debuggable": debuggable,
        "enabled": enabled_state,
        "installer": installer,
        "first_install": first_install,
        "last_update": last_update,
        "launcher": launcher,
        "running": running,
        "granted_permissions": granted_perms,
        "denied_permissions": denied_perms,
    }


def format_package_info(info: Dict[str, Any]) -> str:
    """Format package info into compact line-based text."""
    lines = [
        f"package: {info['package']}",
        f"version: {info['version_name']} ({info['version_code']})",
        f"sdk: min={info['min_sdk'] or '?'} target={info['target_sdk'] or '?'}",
        f"state: {info['enabled']} running={info['running']} debuggable={'yes' if info['debuggable'] else 'no'}",
        f"installer: {info['installer']}",
        f"installed: {info['first_install']} | updated: {info['last_update']}",
        f"launcher: {info['launcher']}",
        f"granted: {', '.join(info['granted_permissions']) if info['granted_permissions'] else 'none'}",
        f"denied: {', '.join(info['denied_permissions']) if info['denied_permissions'] else 'none'}",
    ]
    return "\n".join(lines)


def run_info(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Execute 'info <package>' command."""
    pkg = ""
    for a in args:
        if not a.startswith("-"):
            pkg = a.strip()
            break

    if not pkg:
        raise LlmadbError(
            code=E_USAGE,
            message="missing package name",
            hint="usage: llmadb info <package>",
            exit_code=EXIT_USAGE,
        )

    target_serial = resolve_device(adb, explicit_serial=serial)

    batch_cmds = {
        "dumpsys": f"dumpsys package {pkg}",
        "resolve": f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {pkg} 2>/dev/null",
        "pid": f"pidof {pkg} 2>/dev/null",
    }
    raw = run_batch(adb, batch_cmds, serial=target_serial, timeout=10.0)

    info = parse_package_info(
        pkg=pkg,
        dumpsys_text=raw.get("dumpsys", ""),
        resolve_text=raw.get("resolve", ""),
        pid_text=raw.get("pid", ""),
    )
    output = format_package_info(info)
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
