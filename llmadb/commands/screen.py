"""Handler for 'screen' command: screenshot capture, annotation, and caching."""

import io
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from llmadb.adb import Adb
from llmadb.annotate import annotate_snapshot, draw_grid, get_default_font
from llmadb.cache import get_device_cache_dir, load_snapshot, prune_screens
from llmadb.commands.ui import get_ui_snapshot
from llmadb.device import resolve_device
from llmadb.errors import (
    E_ADB,
    E_NOT_FOUND,
    E_SECURE_OR_EMPTY,
    E_USAGE,
    EXIT_ADB,
    EXIT_NOT_FOUND,
    EXIT_SECURE_OR_EMPTY,
    EXIT_USAGE,
    LlmadbError,
)
from llmadb.uitree import Snapshot

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def capture_screenshot_bytes(adb: Adb, serial: Optional[str] = None) -> bytes:
    """Capture raw screencap PNG bytes with signature validation."""
    res = adb.run(["exec-out", "screencap", "-p"], serial=serial, timeout=10.0)
    data = res.stdout
    idx = data.find(PNG_MAGIC)
    if idx == -1:
        raise LlmadbError(
            code=E_ADB,
            message="screencap did not return valid PNG data",
            hint="check device display power or permissions",
            exit_code=EXIT_ADB,
        )
    return data[idx:]


def run_screen(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Handle 'screen' capture and annotation."""
    from PIL import Image, ImageDraw

    target_serial = resolve_device(adb, explicit_serial=serial)

    # Parse flags
    no_ui = "--no-ui" in args
    raw_mode = "--raw" in args
    no_grid = "--no-grid" in args
    max_edge = 960
    grid_interval: Optional[int] = None
    region: Optional[Tuple[int, int, int, int]] = None
    element_idx: Optional[int] = None

    idx = 0
    while idx < len(args):
        a = args[idx]
        if a == "--max-edge":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "--max-edge requires integer", "specify max edge size", EXIT_USAGE)
            max_edge = int(args[idx + 1])
            idx += 2
        elif a.startswith("--max-edge="):
            max_edge = int(a.split("=", 1)[1])
            idx += 1
        elif a == "--grid":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "--grid requires interval", "specify grid interval in device px", EXIT_USAGE)
            grid_interval = int(args[idx + 1])
            idx += 2
        elif a.startswith("--grid="):
            grid_interval = int(a.split("=", 1)[1])
            idx += 1
        elif a == "--region":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "--region requires x1,y1,x2,y2", "specify crop region", EXIT_USAGE)
            coords = [int(p.strip()) for p in args[idx + 1].split(",")]
            if len(coords) == 4:
                region = (coords[0], coords[1], coords[2], coords[3])
            idx += 2
        elif a.startswith("--region="):
            coords = [int(p.strip()) for p in a.split("=", 1)[1].split(",")]
            if len(coords) == 4:
                region = (coords[0], coords[1], coords[2], coords[3])
            idx += 1
        elif a == "--element":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "--element requires index", "specify element index to crop", EXIT_USAGE)
            element_idx = int(args[idx + 1])
            idx += 2
        elif a.startswith("--element="):
            element_idx = int(a.split("=", 1)[1])
            idx += 1
        else:
            idx += 1

    # Default to 100px coordinate grid unless --raw, --no-grid, or --element is used
    if grid_interval is None and not raw_mode and not no_grid and element_idx is None:
        grid_interval = 100

    # 1. Capture screencap bytes
    png_bytes = capture_screenshot_bytes(adb, serial=target_serial)
    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")

    # 2. Acquire UI snapshot unless --no-ui
    snapshot: Optional[Snapshot] = None
    if not no_ui:
        try:
            snapshot = get_ui_snapshot(adb, serial=target_serial)
        except LlmadbError as e:
            if e.code != E_SECURE_OR_EMPTY:
                raise

    # Check for blank/secure screen
    extrema = image.convert("L").getextrema()
    if extrema == (0, 0) and (snapshot is None or not snapshot.elements):
        raise LlmadbError(
            code=E_SECURE_OR_EMPTY,
            message="blank or secure screen detected",
            hint="screen is black; FLAG_SECURE may block screencap. Disable FLAG_SECURE or inspect device",
            exit_code=EXIT_SECURE_OR_EMPTY,
        )

    orig_w, orig_h = image.size
    cached_snap = snapshot or load_snapshot(target_serial)
    tree_w = cached_snap.screen_width if cached_snap and cached_snap.screen_width > 0 else orig_w
    tree_h = cached_snap.screen_height if cached_snap and cached_snap.screen_height > 0 else orig_h

    # Handle element crop
    if element_idx is not None:
        if not snapshot:
            raise LlmadbError(E_NOT_FOUND, "cannot crop element without UI snapshot", "remove --no-ui", EXIT_NOT_FOUND)
        el = next((e for e in snapshot.elements if e.idx == element_idx), None)
        if not el:
            raise LlmadbError(E_NOT_FOUND, f"element #{element_idx} not found", "check element indices with `llmadb ui`", EXIT_NOT_FOUND)
        region = el.bounds

    # Handle region crop
    if region:
        rx1, ry1, rx2, ry2 = region
        sx = orig_w / tree_w
        sy = orig_h / tree_h
        crop_box = (
            int(round(rx1 * sx)),
            int(round(ry1 * sy)),
            int(round(rx2 * sx)),
            int(round(ry2 * sy)),
        )
        image = image.crop(crop_box)
        orig_w, orig_h = image.size
        tree_w = max(1, rx2 - rx1)
        tree_h = max(1, ry2 - ry1)

    # Downscale to max_edge
    long_edge = max(orig_w, orig_h)
    downscale_factor = 1.0
    if max_edge > 0 and long_edge > max_edge:
        downscale_factor = max_edge / long_edge
        new_w = max(1, int(round(orig_w * downscale_factor)))
        new_h = max(1, int(round(orig_h * downscale_factor)))
        image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    final_w, final_h = image.size
    scale_from_tree_x = final_w / tree_w
    scale_from_tree_y = final_h / tree_h

    # Annotate image
    if not raw_mode and snapshot:
        annotate_snapshot(
            image,
            snapshot=snapshot,
            scale_x=scale_from_tree_x,
            scale_y=scale_from_tree_y,
            grid_interval=grid_interval,
        )
    elif grid_interval and grid_interval > 0:
        draw = ImageDraw.Draw(image, "RGBA")
        font = get_default_font(size=14)
        draw_grid(
            draw,
            width=final_w,
            height=final_h,
            interval_device_px=grid_interval,
            scale_x=scale_from_tree_x,
            scale_y=scale_from_tree_y,
            font=font,
        )

    # Save to cache
    cache_dir = get_device_cache_dir(target_serial)
    screens_dir = cache_dir / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)
    snap_id = snapshot.id if snapshot else (cached_snap.id if cached_snap else 0)
    out_path = screens_dir / f"{snap_id}.png"
    image.save(out_path, format="PNG")

    prune_screens(target_serial)

    # Print summary output: path=<file> size=WxH device=WxH scale=<f> snap=<n> elements=<n>
    elem_count = len(snapshot.elements) if snapshot else 0
    scale_str = f"{downscale_factor:.2f}" if downscale_factor != 1.0 else "1.0"
    out_line = (
        f"path={out_path} size={final_w}x{final_h} device={tree_w}x{tree_h} "
        f"scale={scale_str} snap={snap_id} elements={elem_count}\n"
    )
    sys.stdout.write(out_line)
    sys.stdout.flush()
    return 0
