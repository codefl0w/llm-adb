"""Handler for 'screen' command: screenshot capture, annotation, and caching."""

import io
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from llmadb.adb import Adb
from llmadb.annotate import annotate_snapshot, draw_grid, get_default_font
from llmadb.cache import (
    get_device_cache_dir,
    get_next_snapshot_id,
    load_snapshot,
    prune_screens,
    save_snapshot,
)
from llmadb.commands.ui import get_ui_snapshot
from llmadb.device import resolve_device
from llmadb.errors import (
    E_ADB,
    E_NOT_FOUND,
    E_SECURE_OR_EMPTY,
    E_UNSUPPORTED,
    E_USAGE,
    EXIT_ADB,
    EXIT_NOT_FOUND,
    EXIT_SECURE_OR_EMPTY,
    EXIT_USAGE,
    LlmadbError,
)
from llmadb.uitree import Element, Snapshot

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
    ocr_mode = "--ocr" in args
    max_edge = 960
    grid_interval: Optional[int] = None
    region: Optional[Tuple[int, int, int, int]] = None
    element_idx: Optional[int] = None
    output_arg: Optional[str] = None

    idx = 0
    while idx < len(args):
        a = args[idx]
        if a in ("-o", "--output"):
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, f"{a} requires output path", "specify file or directory path", EXIT_USAGE)
            output_arg = args[idx + 1]
            idx += 2
        elif a.startswith("--output="):
            output_arg = a.split("=", 1)[1]
            if not output_arg:
                raise LlmadbError(E_USAGE, "--output requires output path", "specify file or directory path", EXIT_USAGE)
            idx += 1
        elif a.startswith("-o") and len(a) > 2:
            output_arg = a[2:]
            idx += 1
        elif a == "--max-edge":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "--max-edge requires integer", "specify max edge size", EXIT_USAGE)
            try:
                max_edge = int(args[idx + 1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid max-edge: {args[idx + 1]}", "specify max edge as integer", EXIT_USAGE)
            idx += 2
        elif a.startswith("--max-edge="):
            try:
                max_edge = int(a.split("=", 1)[1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid max-edge: {a}", "specify max edge as integer", EXIT_USAGE)
            idx += 1
        elif a == "--grid":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "--grid requires interval", "specify grid interval in device px", EXIT_USAGE)
            try:
                grid_interval = int(args[idx + 1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid grid interval: {args[idx + 1]}", "specify grid interval as integer", EXIT_USAGE)
            idx += 2
        elif a.startswith("--grid="):
            try:
                grid_interval = int(a.split("=", 1)[1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid grid interval: {a}", "specify grid interval as integer", EXIT_USAGE)
            idx += 1
        elif a == "--region":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "--region requires x1,y1,x2,y2", "specify crop region", EXIT_USAGE)
            try:
                coords = [int(p.strip()) for p in args[idx + 1].split(",")]
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid region: {args[idx + 1]}", "specify region as x1,y1,x2,y2", EXIT_USAGE)
            if len(coords) != 4 or coords[2] <= coords[0] or coords[3] <= coords[1]:
                raise LlmadbError(E_USAGE, f"invalid region bounds: {args[idx + 1]}", "require x1,y1,x2,y2 with x2>x1 and y2>y1", EXIT_USAGE)
            region = (coords[0], coords[1], coords[2], coords[3])
            idx += 2
        elif a.startswith("--region="):
            raw_reg = a.split("=", 1)[1]
            try:
                coords = [int(p.strip()) for p in raw_reg.split(",")]
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid region: {raw_reg}", "specify region as x1,y1,x2,y2", EXIT_USAGE)
            if len(coords) != 4 or coords[2] <= coords[0] or coords[3] <= coords[1]:
                raise LlmadbError(E_USAGE, f"invalid region bounds: {raw_reg}", "require x1,y1,x2,y2 with x2>x1 and y2>y1", EXIT_USAGE)
            region = (coords[0], coords[1], coords[2], coords[3])
            idx += 1
        elif a == "--element":
            if idx + 1 >= len(args):
                raise LlmadbError(E_USAGE, "--element requires index", "specify element index to crop", EXIT_USAGE)
            try:
                element_idx = int(args[idx + 1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid element index: {args[idx + 1]}", "specify integer element index", EXIT_USAGE)
            idx += 2
        elif a.startswith("--element="):
            try:
                element_idx = int(a.split("=", 1)[1])
            except ValueError:
                raise LlmadbError(E_USAGE, f"invalid element index: {a}", "specify integer element index", EXIT_USAGE)
            idx += 1
        elif a in ("--no-ui", "--raw", "--no-grid", "--ocr"):
            idx += 1
        else:
            raise LlmadbError(
                code=E_USAGE,
                message=f"unknown screen option '{a}'",
                hint="usage: llmadb screen [-o PATH] [--ocr] [--grid N] [--no-grid] [--max-edge 960] [--element N] [--region x1,y1,x2,y2] [--raw] [--no-ui]",
                exit_code=EXIT_USAGE,
            )

    # Fail fast before ADB screencap if --ocr is requested but OCR backend is not installed
    if ocr_mode:
        from llmadb.ocr import is_ocr_available
        if not is_ocr_available():
            raise LlmadbError(
                code=E_UNSUPPORTED,
                message="OCR module dependencies are not installed",
                hint="install optional OCR support via: pip install \"llm-adb[ocr]\"",
                exit_code=EXIT_USAGE,
            )

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
    if cached_snap and cached_snap.screen_width > 0 and cached_snap.screen_height > 0:
        # Guard against stale cached dimensions if orientation changed since last UI snapshot
        if (cached_snap.screen_width > cached_snap.screen_height) != (orig_w > orig_h):
            full_tree_w, full_tree_h = orig_w, orig_h
        else:
            full_tree_w, full_tree_h = cached_snap.screen_width, cached_snap.screen_height
    else:
        full_tree_w, full_tree_h = orig_w, orig_h
    tree_w, tree_h = full_tree_w, full_tree_h
    scale_screen_to_tree_x = full_tree_w / max(1, orig_w)
    scale_screen_to_tree_y = full_tree_h / max(1, orig_h)
    crop_offset_px = (0, 0)

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
        cx1 = max(0, min(orig_w, int(round(rx1 * sx))))
        cy1 = max(0, min(orig_h, int(round(ry1 * sy))))
        cx2 = max(0, min(orig_w, int(round(rx2 * sx))))
        cy2 = max(0, min(orig_h, int(round(ry2 * sy))))
        if cx2 <= cx1 or cy2 <= cy1:
            raise LlmadbError(E_USAGE, f"crop region {region} is outside screen bounds ({tree_w}x{tree_h})", "specify valid in-screen region", EXIT_USAGE)
        crop_offset_px = (cx1, cy1)
        image = image.crop((cx1, cy1, cx2, cy2))
        orig_w, orig_h = image.size
        tree_w = max(1, rx2 - rx1)
        tree_h = max(1, ry2 - ry1)

    # Run OCR on unannotated (cropped, pre-downscale) image if requested
    ocr_elements: List[Element] = []
    snap_id = snapshot.id if snapshot else (get_next_snapshot_id(target_serial) if ocr_mode else (cached_snap.id if cached_snap else 0))
    if ocr_mode:
        from llmadb.ocr import extract_ocr_boxes, merge_ocr_into_snapshot
        if snap_id == 0:
            snap_id = get_next_snapshot_id(target_serial)
        ocr_boxes = extract_ocr_boxes(image)
        snapshot, ocr_elements = merge_ocr_into_snapshot(
            snapshot=snapshot,
            ocr_boxes=ocr_boxes,
            crop_offset=crop_offset_px,
            scale_to_device_x=scale_screen_to_tree_x,
            scale_to_device_y=scale_screen_to_tree_y,
            fallback_snap_id=snap_id,
            screen_width=full_tree_w,
            screen_height=full_tree_h,
        )
        save_snapshot(target_serial, snapshot)

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

    # Annotate image (skip snapshot element boxes when cropped to a sub-region)
    if not raw_mode and snapshot and not region:
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

    # Save to output path or cache
    custom_out = output_arg or os.environ.get("LLMADB_SCREENSHOT_OUTDIR", "").strip()
    if custom_out:
        target_path = Path(custom_out)
        if target_path.exists() and target_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            out_path = target_path / f"{snap_id}.png"
        elif target_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            out_path = target_path
        else:
            target_path.mkdir(parents=True, exist_ok=True)
            out_path = target_path / f"{snap_id}.png"
        image.save(out_path, format="PNG")
    else:
        cache_dir = get_device_cache_dir(target_serial)
        screens_dir = cache_dir / "screens"
        screens_dir.mkdir(parents=True, exist_ok=True)
        out_path = screens_dir / f"{snap_id}.png"
        image.save(out_path, format="PNG")
        prune_screens(target_serial)

    # Print summary output: path=<file> size=WxH device=WxH [region=x1,y1,x2,y2] scale=<f> snap=<n> elements=<n>
    elem_count = len(snapshot.elements) if snapshot else 0
    scale_str = f"{downscale_factor:.2f}" if downscale_factor != 1.0 else "1.0"
    region_str = f" region={region[0]},{region[1]},{region[2]},{region[3]}" if region else ""
    ocr_str = f" ocr={len(ocr_elements)}" if ocr_mode else ""
    out_Lines: List[str] = [
        f"path={out_path} size={final_w}x{final_h} device={full_tree_w}x{full_tree_h}{region_str} "
        f"scale={scale_str} snap={snap_id} elements={elem_count}{ocr_str}"
    ]
    if ocr_mode:
        for el in ocr_elements:
            out_Lines.append(el.format_row())

    if max_lines is not None and max_lines >= 0 and len(out_Lines) > max_lines:
        truncated = len(out_Lines) - max_lines
        for line in out_Lines[:max_lines]:
            sys.stdout.write(line + "\n")
        sys.stdout.write(f"[truncated: {truncated} more lines]\n")
    else:
        for line in out_Lines:
            sys.stdout.write(line + "\n")
    sys.stdout.flush()
    return 0
