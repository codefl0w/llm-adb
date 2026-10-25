"""Image annotation using Pillow for element bounding boxes, badges, and grids."""

import re
from typing import List, Optional, Tuple

from llmadb.uitree import Snapshot

OVERLAY_BOUNDS_RE = re.compile(r'overlay window="([^"]+)" bounds=\[(\d+),(\d+)\]\[(\d+),(\d+)\]')


def get_default_font(size: int = 14):
    """Attempt to load a crisp TrueType font, falling back to default."""
    from PIL import ImageFont
    try:
        # Common Windows font
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        try:
            # Common Linux font
            return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
        except OSError:
            return ImageFont.load_default()


def draw_grid(
    draw,
    width: int,
    height: int,
    interval_device_px: int,
    scale_x: float,
    scale_y: float,
    font,
) -> None:
    """Draw gridlines with device-coordinate labels along all 4 edges and interior intersections."""
    if interval_device_px <= 0 or scale_x <= 0 or scale_y <= 0:
        return

    grid_color = (0, 229, 255, 130)      # semi-transparent cyan for major lines
    subgrid_color = (0, 229, 255, 55)    # faint cyan for 50px midpoint lines
    label_bg = (0, 0, 0, 185)
    label_fg = (255, 255, 255)
    cross_bg = (0, 20, 30, 165)
    cross_fg = (160, 245, 255)

    small_font = get_default_font(size=11)

    # Subtle midpoint sub-grid lines (e.g. every 50 device px when interval is 100)
    if interval_device_px >= 100:
        half_step = interval_device_px // 2
        dev_x = half_step
        while True:
            x = int(round(dev_x * scale_x))
            if x >= width:
                break
            draw.line([(x, 0), (x, height)], fill=subgrid_color, width=1)
            dev_x += interval_device_px

        dev_y = half_step
        while True:
            y = int(round(dev_y * scale_y))
            if y >= height:
                break
            draw.line([(0, y), (width, y)], fill=subgrid_color, width=1)
            dev_y += interval_device_px

    # Vertical major lines + top & bottom edge labels
    x_positions: List[Tuple[int, int]] = []
    dev_x = interval_device_px
    while True:
        x = int(round(dev_x * scale_x))
        if x >= width:
            break
        x_positions.append((dev_x, x))
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
        text = str(dev_x)
        tw = len(text) * 7 + 6
        # Top edge label
        draw.rectangle([(x - 1, 0), (x + tw, 15)], fill=label_bg)
        draw.text((x + 2, 1), text, fill=label_fg, font=small_font)
        # Bottom edge label
        if height > 36:
            draw.rectangle([(x - 1, height - 15), (x + tw, height)], fill=label_bg)
            draw.text((x + 2, height - 14), text, fill=label_fg, font=small_font)
        dev_x += interval_device_px

    # Horizontal major lines + left & right edge labels
    y_positions: List[Tuple[int, int]] = []
    dev_y = interval_device_px
    while True:
        y = int(round(dev_y * scale_y))
        if y >= height:
            break
        y_positions.append((dev_y, y))
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)
        text = str(dev_y)
        tw = len(text) * 7 + 6
        # Left edge label
        draw.rectangle([(0, y - 1), (tw, y + 14)], fill=label_bg)
        draw.text((2, y), text, fill=label_fg, font=small_font)
        # Right edge label
        if width > 72:
            draw.rectangle([(width - tw, y - 1), (width, y + 14)], fill=label_bg)
            draw.text((width - tw + 2, y), text, fill=label_fg, font=small_font)
        dev_y += interval_device_px

    # Interior (x,y) coordinate tags every 2 * interval_device_px (e.g. 200px)
    major_step = interval_device_px * 2
    for dev_x, x in x_positions:
        if dev_x % major_step != 0:
            continue
        if x < 40 or x > width - 55:
            continue
        for dev_y, y in y_positions:
            if dev_y % major_step != 0:
                continue
            if y < 24 or y > height - 24:
                continue
            coord_text = f"{dev_x},{dev_y}"
            cw = len(coord_text) * 6 + 6
            ch = 13
            draw.rectangle([(x + 1, y + 1), (x + 1 + cw, y + 1 + ch)], fill=cross_bg)
            draw.text((x + 3, y + 1), coord_text, fill=cross_fg, font=small_font)


def annotate_snapshot(
    image,
    snapshot: Snapshot,
    scale_x: float,
    scale_y: float,
    grid_interval: Optional[int] = None,
):
    """Draw numbered element bounding boxes, overlay highlights, and coordinate grid onto the image in-place."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image, "RGBA")
    font = get_default_font(size=14)
    small_font = get_default_font(size=11)

    # Box colors
    box_outline = (255, 51, 102, 230)    # Vivid red-pink
    overlay_outline = (255, 193, 7, 240) # Bright amber for non-focused overlays
    badge_bg = (0, 0, 0, 220)            # Dark pill
    badge_fg = (255, 255, 255)           # White index text

    if grid_interval and grid_interval > 0:
        draw_grid(
            draw,
            width=image.width,
            height=image.height,
            interval_device_px=grid_interval,
            scale_x=scale_x,
            scale_y=scale_y,
            font=font,
        )

    # Extract any non-focused overlay windows detected in snapshot.warnings
    overlays: List[Tuple[str, Tuple[int, int, int, int]]] = []
    for w in getattr(snapshot, "warnings", []):
        m = OVERLAY_BOUNDS_RE.search(w)
        if m:
            ov_name = m.group(1)
            ox1, oy1, ox2, oy2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
            overlays.append((ov_name, (ox1, oy1, ox2, oy2)))

    placed_badges: List[Tuple[int, int, int, int]] = []

    def _overlaps(r1: Tuple[int, int, int, int], r2: Tuple[int, int, int, int]) -> bool:
        return not (r1[2] <= r2[0] or r1[0] >= r2[2] or r1[3] <= r2[1] or r1[1] >= r2[3])

    for el in snapshot.elements:
        cx, cy = el.center
        if any(ox1 <= cx <= ox2 and oy1 <= cy <= oy2 for _, (ox1, oy1, ox2, oy2) in overlays):
            continue

        x1, y1, x2, y2 = el.bounds
        bx1 = int(round(x1 * scale_x))
        by1 = int(round(y1 * scale_y))
        bx2 = int(round(x2 * scale_x))
        by2 = int(round(y2 * scale_y))

        # Draw bounding rectangle
        draw.rectangle([(bx1, by1), (bx2, by2)], outline=box_outline, width=2)

        # Draw badge pill with element index and collision avoidance
        badge_text = str(el.idx)
        tw = len(badge_text) * 9 + 8
        th = 16

        candidates: List[Tuple[int, int]] = [(bx1, by1)]
        if by1 >= th:
            candidates.append((bx1, by1 - th))
        for step in range(1, 5):
            if by1 + step * th + th <= max(by2, by1 + th):
                candidates.append((bx1, by1 + step * th))
            if bx1 + step * (tw + 2) + tw <= max(bx2, bx1 + tw):
                candidates.append((bx1 + step * (tw + 2), by1))
        center_pos = (
            max(0, min(image.width - tw, (bx1 + bx2 - tw) // 2)),
            max(0, min(image.height - th, (by1 + by2 - th) // 2)),
        )
        candidates.append(center_pos)

        chosen = (bx1, max(0, by1))
        for cx_pos, cy_pos in candidates:
            rect = (cx_pos, cy_pos, cx_pos + tw, cy_pos + th)
            if not any(_overlaps(rect, prev) for prev in placed_badges):
                chosen = (cx_pos, cy_pos)
                break
        else:
            chosen = center_pos

        tx1, ty1 = chosen
        tx2, ty2 = tx1 + tw, ty1 + th
        placed_badges.append((tx1, ty1, tx2, ty2))

        draw.rectangle([(tx1, ty1), (tx2, ty2)], fill=badge_bg, outline=box_outline, width=1)
        draw.text((tx1 + 4, ty1 + 1), badge_text, fill=badge_fg, font=font)

    # Highlight non-focused overlay windows
    for ov_name, (ox1, oy1, ox2, oy2) in overlays:
        bx1 = int(round(ox1 * scale_x))
        by1 = int(round(oy1 * scale_y))
        bx2 = int(round(ox2 * scale_x))
        by2 = int(round(oy2 * scale_y))
        draw.rectangle([(bx1, by1), (bx2, by2)], outline=overlay_outline, width=3)
        tag = f"overlay: {ov_name}"
        tw = len(tag) * 6 + 8
        draw.rectangle([(bx1, by1), (min(image.width, bx1 + tw), min(image.height, by1 + 15))], fill=badge_bg, outline=overlay_outline, width=1)
        draw.text((bx1 + 4, by1 + 1), tag, fill=(255, 215, 64), font=small_font)

    return image
