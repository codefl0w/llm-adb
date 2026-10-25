"""Handler for 'hardware' command."""

import json
import re
import sys
from typing import Any, Dict, List, Optional

from llmadb.adb import Adb
from llmadb.device import resolve_device
from llmadb.errors import E_USAGE, EXIT_USAGE, LlmadbError
from llmadb.shellbatch import run_batch

PROP_RE = re.compile(r"^\[(.*?)\]: \[(.*?)\]$")


def parse_getprop(text: str) -> Dict[str, str]:
    """Parse output of getprop into dictionary."""
    props: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        m = PROP_RE.match(line)
        if m:
            props[m.group(1)] = m.group(2)
    return props


def parse_wm_size(text: str) -> Dict[str, str]:
    """Parse wm size into physical and override sizes."""
    res = {"physical": "", "effective": ""}
    for line in text.splitlines():
        line = line.strip()
        if "Physical size:" in line:
            res["physical"] = line.split(":", 1)[1].strip()
        elif "Override size:" in line:
            res["effective"] = line.split(":", 1)[1].strip()
    if not res["effective"] and res["physical"]:
        res["effective"] = res["physical"]
    return res


def parse_wm_density(text: str) -> int:
    """Parse wm density into effective DPI."""
    physical = 0
    override = 0
    for line in text.splitlines():
        line = line.strip()
        if "Physical density:" in line:
            try:
                physical = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif "Override density:" in line:
            try:
                override = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return override if override > 0 else physical


def parse_meminfo(text: str) -> Dict[str, int]:
    """Parse /proc/meminfo for total and available RAM in MB."""
    mem_total_kb = 0
    mem_avail_kb = 0
    mem_free_kb = 0
    buffers_kb = 0
    cached_kb = 0

    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            val_str = parts[1]
            try:
                val = int(val_str)
                if key == "MemTotal":
                    mem_total_kb = val
                elif key == "MemAvailable":
                    mem_avail_kb = val
                elif key == "MemFree":
                    mem_free_kb = val
                elif key == "Buffers":
                    buffers_kb = val
                elif key == "Cached":
                    cached_kb = val
            except ValueError:
                pass

    if mem_avail_kb == 0:
        mem_avail_kb = mem_free_kb + buffers_kb + cached_kb

    return {
        "total_mb": round(mem_total_kb / 1024),
        "available_mb": round(mem_avail_kb / 1024),
    }


def parse_df(text: str) -> Dict[str, float]:
    """Parse df /data output for size and used in GB."""
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return {"data_size_gb": 0.0, "data_used_gb": 0.0}

    # Take the last line which corresponds to the mount
    row = lines[-1].split()
    # Format: Filesystem 1K-blocks Used Available Use% Mounted
    if len(row) >= 4:
        try:
            total_1k = float(row[1])
            used_1k = float(row[2])
            return {
                "data_size_gb": round(total_1k / (1024 * 1024), 1),
                "data_used_gb": round(used_1k / (1024 * 1024), 1),
            }
        except ValueError:
            pass

    return {"data_size_gb": 0.0, "data_used_gb": 0.0}


def parse_root(text: str) -> str:
    """Determine root status from su command output."""
    if "uid=0(" in text:
        return "yes"
    if "not found" in text.lower() or "permission denied" in text.lower() or "rejected" in text.lower():
        return "no"
    return "unknown"


def get_hardware_info(adb: Adb, serial: Optional[str] = None) -> Dict[str, Any]:
    """Gather hardware specs via single batched shell call."""
    batch_cmds = {
        "getprop": "getprop",
        "wm_size": "wm size",
        "wm_density": "wm density",
        "meminfo": "cat /proc/meminfo",
        "df": "df /data",
        "getenforce": "getenforce",
        "su": "su -c id 2>&1",
    }
    raw = run_batch(adb, batch_cmds, serial=serial, timeout=10.0)

    props = parse_getprop(raw.get("getprop", ""))
    size = parse_wm_size(raw.get("wm_size", ""))
    dpi = parse_wm_density(raw.get("wm_density", ""))
    mem = parse_meminfo(raw.get("meminfo", ""))
    storage = parse_df(raw.get("df", ""))
    root_status = parse_root(raw.get("su", ""))
    selinux = raw.get("getenforce", "").strip() or "unknown"

    raw_abi = props.get("ro.product.cpu.abilist", "") or props.get("ro.product.cpu.abi", "")
    abi_list = [a.strip() for a in raw_abi.split(",") if a.strip()]

    sdk_val = 0
    try:
        sdk_val = int(props.get("ro.build.version.sdk", "0"))
    except ValueError:
        pass

    return {
        "manufacturer": props.get("ro.product.manufacturer", ""),
        "model": props.get("ro.product.model", ""),
        "android_version": props.get("ro.build.version.release", ""),
        "sdk": sdk_val,
        "security_patch": props.get("ro.build.version.security_patch", ""),
        "fingerprint": props.get("ro.build.fingerprint", ""),
        "abi": abi_list,
        "hardware": props.get("ro.boot.hardware", "") or props.get("ro.hardware", ""),
        "platform": props.get("ro.board.platform", ""),
        "resolution": {
            "physical": size["physical"],
            "effective": size["effective"],
            "dpi": dpi,
        },
        "memory": mem,
        "storage": storage,
        "selinux": selinux,
        "root": root_status,
    }


def _format_resolution(res: Dict[str, Any]) -> str:
    physical = res.get("physical", "")
    effective = res.get("effective", "")
    dpi = res.get("dpi", 0)

    details: List[str] = []
    if effective and physical and effective != physical:
        details.append(f"physical: {physical}")
    if dpi:
        details.append(f"{dpi} dpi")

    base = effective or physical or "unknown"
    return f"{base} ({', '.join(details)})" if details else base


def format_hardware_text(info: Dict[str, Any]) -> str:
    """Render compact key-value hardware specification lines."""
    res_str = _format_resolution(info.get("resolution", {}))

    mem = info.get("memory", {})
    total_mb = mem.get("total_mb", 0)
    avail_mb = mem.get("available_mb", 0)
    mem_str = f"{avail_mb} MB available / {total_mb} MB total" if total_mb else "unknown"

    st = info.get("storage", {})
    total_gb = st.get("data_size_gb", 0.0)
    used_gb = st.get("data_used_gb", 0.0)
    st_str = f"{used_gb} GB used / {total_gb} GB total" if total_gb else "unknown"

    abi_list = info.get("abi", [])
    if isinstance(abi_list, list):
        abi_str = ", ".join(str(a) for a in abi_list if a) or "unknown"
    else:
        abi_str = str(abi_list) or "unknown"

    lines = [
        f"manufacturer: {info.get('manufacturer', '')}",
        f"model: {info.get('model', '')}",
        f"android_version: {info.get('android_version', '')}",
        f"sdk: {info.get('sdk', '')}",
        f"security_patch: {info.get('security_patch', '')}",
        f"fingerprint: {info.get('fingerprint', '')}",
        f"abi: {abi_str}",
        f"hardware: {info.get('hardware', '')}",
        f"platform: {info.get('platform', '')}",
        f"resolution: {res_str}",
        f"memory: {mem_str}",
        f"storage: {st_str}",
        f"selinux: {info.get('selinux', 'unknown')}",
        f"root: {info.get('root', 'unknown')}",
    ]
    return "\n".join(lines)


def run_hardware(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle hardware command execution."""
    json_mode = False
    for a in args:
        if a == "--json":
            json_mode = True
        else:
            raise LlmadbError(
                code=E_USAGE,
                message=f"unknown hardware option '{a}'",
                hint="usage: llmadb hardware [--json]",
                exit_code=EXIT_USAGE,
            )

    target_serial = resolve_device(adb, explicit_serial=serial)
    info = get_hardware_info(adb, serial=target_serial)
    output = json.dumps(info, indent=2) if json_mode else format_hardware_text(info)

    lines = output.splitlines()
    if max_lines is not None and max_lines >= 0 and len(lines) > max_lines:
        truncated = len(lines) - max_lines
        for line in lines[:max_lines]:
            sys.stdout.write(line + "\n")
        sys.stdout.write(f"[truncated: {truncated} more lines]\n")
    else:
        sys.stdout.write(output + "\n")
    sys.stdout.flush()
    return 0
