"""Handler for 'current' command: foreground package/activity, rotation, keyboard state."""

import re
import sys
from typing import List, Optional

from llmadb.adb import Adb
from llmadb.device import resolve_device
from llmadb.shellbatch import run_batch

COMPONENT_RE = re.compile(r"([a-zA-Z0-9_.]+/[a-zA-Z0-9_.]+)")
ROTATION_RE = re.compile(r"(?:mCurrentRotation|mRotation|orientation|rot)=(?:ROTATION_)?(\d+)")


def parse_component(focus_text: str, resumed_text: str) -> str:
    """Extract foreground package/activity using fallback strategies."""
    # Strategy 1: mCurrentFocus
    for line in focus_text.splitlines():
        if "mCurrentFocus" in line:
            m = COMPONENT_RE.search(line)
            if m:
                return m.group(1)

    # Strategy 2: ResumedActivity
    for line in resumed_text.splitlines():
        if "ResumedActivity" in line or "mResumedActivity" in line:
            m = COMPONENT_RE.search(line)
            if m:
                return m.group(1)

    # Strategy 3: Any component match in focus_text
    m = COMPONENT_RE.search(focus_text)
    if m:
        return m.group(1)

    # Strategy 4: Any component match in resumed_text
    m = COMPONENT_RE.search(resumed_text)
    if m:
        return m.group(1)

    return "unknown/unknown"


def parse_keyboard(ime_text: str) -> str:
    """Detect if software keyboard / IME is visible."""
    if "mInputShown=true" in ime_text or "isInputViewShown=true" in ime_text or "mInputShown : true" in ime_text:
        return "visible"
    return "hidden"


def parse_rotation(rot_setting: str, window_rot_text: str) -> int:
    """Extract screen rotation 0-3."""
    # Check user_rotation setting first
    rot_str = rot_setting.strip()
    if rot_str in ("0", "1", "2", "3"):
        return int(rot_str)

    # Check window rotation dumpsys
    m = ROTATION_RE.search(window_rot_text)
    if m:
        try:
            val = int(m.group(1))
            if val in (0, 1, 2, 3):
                return val
            if val in (90, 180, 270):
                return val // 90
        except ValueError:
            pass

    return 0


def get_current_state(adb: Adb, serial: Optional[str] = None) -> str:
    """Query current device foreground state in single batched shell call."""
    batch_cmds = {
        "focus": "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'",
        "resumed": "dumpsys activity activities | grep -E 'ResumedActivity|mResumedActivity'",
        "ime": "dumpsys input_method | grep -E 'mInputShown|isInputViewShown'",
        "auto_rot": "settings get system accelerometer_rotation",
        "rot_setting": "settings get system user_rotation",
        "rot_window": "dumpsys window displays | grep -m 1 -E 'mCurrentRotation=|mRotation=(ROTATION_)?[0-9]'",
    }
    raw = run_batch(adb, batch_cmds, serial=serial, timeout=5.0)

    component = parse_component(raw.get("focus", ""), raw.get("resumed", ""))
    keyboard = parse_keyboard(raw.get("ime", ""))
    auto = raw.get("auto_rot", "").strip() == "1"
    user_rot = "" if auto else raw.get("rot_setting", "")
    rotation = parse_rotation(user_rot, raw.get("rot_window", ""))

    return f"{component} rot={rotation} keyboard={keyboard}"


def run_current(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Execute 'current' command."""
    target_serial = resolve_device(adb, explicit_serial=serial)
    state = get_current_state(adb, serial=target_serial)
    sys.stdout.write(state + "\n")
    sys.stdout.flush()
    return 0
