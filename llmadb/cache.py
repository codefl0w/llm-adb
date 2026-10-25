"""Per-serial caching of snapshots, screenshots, marks, and state."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llmadb.uitree import Element, Snapshot


def get_base_cache_dir() -> Path:
    """Return platform-appropriate base user cache directory for llmadb."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data)
        else:
            base = Path.home() / "AppData" / "Local"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        if xdg:
            base = Path(xdg)
        else:
            base = Path.home() / ".cache"
    return base / "llmadb"


def _device_cache_path(serial: str) -> Path:
    """Return device-specific cache path without creating it."""
    # Sanitize serial for directory name
    safe_serial = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in serial)
    return get_base_cache_dir() / safe_serial


def get_device_cache_dir(serial: str) -> Path:
    """Return device-specific cache directory."""
    dir_path = _device_cache_path(serial)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def get_next_snapshot_id(serial: str) -> int:
    """Get and increment monotonically increasing snapshot ID for device."""
    cache_dir = get_device_cache_dir(serial)
    id_file = cache_dir / "last_snap_id"
    last_id = 0
    if id_file.exists():
        try:
            last_id = int(id_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            last_id = 0
    next_id = last_id + 1
    try:
        id_file.write_text(str(next_id), encoding="utf-8")
    except OSError:
        pass
    return next_id


def compute_content_hash(raw_xml: bytes) -> str:
    """Compute sha256 hash of UI content."""
    return hashlib.sha256(raw_xml).hexdigest()[:16]


def save_snapshot(serial: str, snapshot: Snapshot) -> None:
    """Save latest snapshot into snap.json."""
    cache_dir = get_device_cache_dir(serial)
    snap_file = cache_dir / "snap.json"

    data = {
        "id": snapshot.id,
        "timestamp": time.time(),
        "screen_width": snapshot.screen_width,
        "screen_height": snapshot.screen_height,
        "app_package": snapshot.app_package,
        "rotation": snapshot.rotation,
        "content_hash": compute_content_hash(snapshot.raw_xml),
        "elements": [
            {
                "idx": el.idx,
                "node_type": el.node_type,
                "label": el.label,
                "resource_id": el.resource_id,
                "short_id": el.short_id,
                "bounds": el.bounds,
                "center": el.center,
                "flags": el.flags,
                "raw_class": el.raw_class,
                "package": el.package,
            }
            for el in snapshot.elements
        ],
    }

    try:
        snap_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_snapshot(serial: str) -> Optional[Snapshot]:
    """Load latest snapshot from snap.json."""
    cache_dir = get_device_cache_dir(serial)
    snap_file = cache_dir / "snap.json"
    if not snap_file.exists():
        return None

    try:
        data = json.loads(snap_file.read_text(encoding="utf-8"))
        elements = [
            Element(
                idx=d["idx"],
                node_type=d["node_type"],
                label=d["label"],
                resource_id=d["resource_id"],
                short_id=d["short_id"],
                bounds=tuple(d["bounds"]),
                center=tuple(d["center"]),
                flags=d.get("flags", []),
                raw_class=d.get("raw_class", ""),
                package=d.get("package", ""),
            )
            for d in data.get("elements", [])
        ]
        return Snapshot(
            id=data["id"],
            screen_width=data["screen_width"],
            screen_height=data["screen_height"],
            app_package=data["app_package"],
            rotation=data.get("rotation", 0),
            elements=elements,
            raw_xml=b"",
        )
    except Exception:
        return None


def prune_screens(serial: str, max_age_seconds: float = 3600.0, max_files: int = 20) -> None:
    """Prune screenshots older than 1 hour or beyond max_files."""
    cache_dir = get_device_cache_dir(serial)
    screens_dir = cache_dir / "screens"
    if not screens_dir.exists():
        return

    now = time.time()
    files = list(screens_dir.glob("*.png"))
    # Sort by mtime descending (newest first)
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    for idx, f in enumerate(files):
        try:
            mtime = f.stat().st_mtime
            if idx >= max_files or (now - mtime) > max_age_seconds:
                f.unlink(missing_ok=True)
        except OSError:
            pass


def save_mark(serial: str, mark_str: str) -> None:
    """Store mark string in device cache."""
    cache_dir = get_device_cache_dir(serial)
    mark_file = cache_dir / "mark"
    mark_file.write_text(mark_str.strip(), encoding="utf-8")


def load_mark(serial: str) -> Optional[str]:
    """Retrieve stored mark string."""
    cache_dir = get_device_cache_dir(serial)
    mark_file = cache_dir / "mark"
    if mark_file.exists():
        return mark_file.read_text(encoding="utf-8").strip()
    return None


def format_byte_size(num_bytes: int) -> str:
    """Format bytes into readable units."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


# Never deleted: snapshot ids must stay monotonic so stale '--snap N' references
# held in an agent's context cannot collide with a fresh snapshot.
PRESERVED_CACHE_FILES = {"last_snap_id"}


def clear_cache(serial: Optional[str] = None, all_data: bool = False) -> Tuple[int, int]:
    """Clear cached screenshot files and optionally all cache files.
    
    Args:
      serial: Target device serial, or None to clear across all devices.
      all_data: If True, also clears snapshots, marks, and state files.
      
    Returns:
      (files_removed, bytes_removed)
    """
    if serial:
        target_dirs = [_device_cache_path(serial)]
    else:
        base_dir = get_base_cache_dir()
        target_dirs = [p for p in base_dir.iterdir() if p.is_dir()] if base_dir.is_dir() else []

    candidates: List[Path] = []
    for dev_dir in target_dirs:
        candidates.extend((dev_dir / "screens").glob("*.png"))
        if all_data:
            candidates.extend(
                f for f in dev_dir.glob("*") if f.is_file() and f.name not in PRESERVED_CACHE_FILES
            )

    files_removed = 0
    bytes_removed = 0
    for f in candidates:
        try:
            size = f.stat().st_size
            f.unlink()
        except OSError:
            # Missing or locked (e.g. open in an image viewer); skip
            continue
        bytes_removed += size
        files_removed += 1

    return files_removed, bytes_removed

