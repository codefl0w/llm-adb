"""Optional OCR module for llm-adb.

Strictly decoupled from base llm-adb dependencies:
- Base llm-adb only requires Pillow.
- OCR engines (RapidOCR ONNX Runtime or pytesseract) are imported lazily inside
  `extract_ocr_boxes` when `llmadb screen --ocr` is invoked.
- If no OCR engine is installed, raises `LlmadbError(E_UNSUPPORTED, ..., exit_code=EXIT_USAGE)`.
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from llmadb.errors import E_UNSUPPORTED, EXIT_USAGE, LlmadbError
from llmadb.uitree import Element, Snapshot, clean_label

DEFAULT_MIN_CONFIDENCE = 0.45

_RAPIDOCR_INSTANCE: Any = None


@dataclass
class OcrBox:
    """Detected text bounding box in image pixel coordinates."""
    text: str
    bounds: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float


def _get_rapidocr_engine() -> Any:
    """Lazily initialize and cache RapidOCR engine instance."""
    global _RAPIDOCR_INSTANCE
    if _RAPIDOCR_INSTANCE is not None:
        return _RAPIDOCR_INSTANCE

    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
        _RAPIDOCR_INSTANCE = RapidOCR()
        return _RAPIDOCR_INSTANCE
    except ImportError:
        pass

    try:
        from rapidocr import RapidOCR  # type: ignore
        _RAPIDOCR_INSTANCE = RapidOCR()
        return _RAPIDOCR_INSTANCE
    except ImportError:
        return None


def _run_rapidocr(engine: Any, image: Any, min_confidence: float) -> List[OcrBox]:
    """Run RapidOCR on a PIL Image and return normalized OcrBox items."""
    import numpy as np  # type: ignore

    arr = np.asarray(image.convert("RGB"))
    try:
        result, _ = engine(arr, use_cls=False)
    except TypeError:
        result, _ = engine(arr)
    if not result:
        return []

    boxes: List[OcrBox] = []
    for item in result:
        if not item or len(item) < 3:
            continue
        pts, raw_text, score = item[0], item[1], item[2]
        try:
            conf = float(score)
        except (TypeError, ValueError):
            conf = 1.0
        if conf < min_confidence:
            continue

        label = clean_label(str(raw_text), "", full=False)
        if not label:
            continue

        try:
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            x1, y1, x2, y2 = int(round(min(xs))), int(round(min(ys))), int(round(max(xs))), int(round(max(ys)))
        except Exception:
            continue

        if x2 <= x1 or y2 <= y1:
            continue

        boxes.append(OcrBox(text=label, bounds=(x1, y1, x2, y2), confidence=conf))

    return boxes


def _run_pytesseract(image: Any, min_confidence: float) -> Optional[List[OcrBox]]:
    """Fallback to pytesseract if installed."""
    try:
        import pytesseract  # type: ignore
    except ImportError:
        return None

    try:
        data = pytesseract.image_to_data(image.convert("RGB"), output_type=pytesseract.Output.DICT)
    except Exception:
        return None

    boxes: List[OcrBox] = []
    n_items = len(data.get("text", []))
    for i in range(n_items):
        raw_text = str(data["text"][i]).strip()
        if not raw_text:
            continue
        try:
            conf_val = float(data["conf"][i])
        except (TypeError, ValueError):
            conf_val = -1.0
        # pytesseract reports confidence in 0..100
        norm_conf = conf_val / 100.0 if conf_val > 1.0 else conf_val
        if norm_conf < min_confidence:
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])
        if w <= 0 or h <= 0:
            continue
        label = clean_label(raw_text, "", full=False)
        if not label:
            continue
        boxes.append(OcrBox(text=label, bounds=(x, y, x + w, y + h), confidence=norm_conf))

    return boxes


def is_ocr_available() -> bool:
    """Return True if an optional OCR backend is installed and importable."""
    if _get_rapidocr_engine() is not None:
        return True
    try:
        import pytesseract  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def extract_ocr_boxes(
    image: Any,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    backend_fn: Optional[Callable[[Any, float], List[OcrBox]]] = None,
) -> List[OcrBox]:
    """Run OCR on a PIL Image and return detected OcrBox list sorted in reading order.

    Raises:
      LlmadbError(E_UNSUPPORTED, exit_code=2) if no OCR backend is installed.
    """
    if backend_fn is not None:
        raw_boxes = backend_fn(image, min_confidence)
    else:
        engine = _get_rapidocr_engine()
        if engine is not None:
            raw_boxes = _run_rapidocr(engine, image, min_confidence)
        else:
            tess_boxes = _run_pytesseract(image, min_confidence)
            if tess_boxes is None:
                raise LlmadbError(
                    code=E_UNSUPPORTED,
                    message="OCR module dependencies are not installed",
                    hint="install optional OCR support via: pip install \"llm-adb[ocr]\"",
                    exit_code=EXIT_USAGE,
                )
            raw_boxes = tess_boxes

    # Sort top-to-bottom (grouped by ~20px vertical bands), then left-to-right
    raw_boxes.sort(key=lambda b: ((b.bounds[1] + b.bounds[3]) // 40, b.bounds[0]))
    return raw_boxes


def _normalize_for_dedup(label: str) -> Tuple[str, str]:
    """Return (normalized_lower, icon_stripped_lower) for OCR-to-UI deduplication."""
    norm = " ".join(label.strip().lower().split())
    parts = norm.split(" ", 1)
    # Strip leading 1-char OCR icon artifact (e.g. 'Q Search Settings' -> 'search settings')
    if len(parts) == 2 and len(parts[0]) == 1 and len(parts[1]) >= 3:
        return norm, parts[1]
    return norm, norm


def _boxes_overlap_same_text(
    a_bounds: Tuple[int, int, int, int],
    a_label: str,
    b_bounds: Tuple[int, int, int, int],
    b_label: str,
) -> bool:
    """Return True if two elements have matching normalized text and overlapping/near-identical centers."""
    acx = (a_bounds[0] + a_bounds[2]) // 2
    acy = (a_bounds[1] + a_bounds[3]) // 2
    # Check if center of OCR box falls inside existing UI element bounds (with 12px tolerance)
    if not ((b_bounds[0] - 12) <= acx <= (b_bounds[2] + 12) and (b_bounds[1] - 12) <= acy <= (b_bounds[3] + 12)):
        return False

    na, na_stripped = _normalize_for_dedup(a_label)
    nb, nb_stripped = _normalize_for_dedup(b_label)
    if not na or not nb:
        return False

    if na == nb or na_stripped == nb or na == nb_stripped:
        return True

    # Also suppress if UI element is a single row/item (height <= 360px) whose label already contains the OCR line
    b_height = b_bounds[3] - b_bounds[1]
    if b_height <= 360 and len(na_stripped) >= 3 and (na in nb or na_stripped in nb):
        return True

    return False


def map_ocr_boxes_to_device_elements(
    boxes: List[OcrBox],
    crop_offset: Tuple[int, int],
    scale_to_device_x: float,
    scale_to_device_y: float,
    screen_width: int,
    screen_height: int,
    existing_elements: Optional[List[Element]] = None,
    start_idx: int = 1,
) -> List[Element]:
    """Map image-space OcrBox coordinates back to full-device screen coordinates and Element objects."""
    off_x, off_y = crop_offset
    existing = existing_elements or []
    elements: List[Element] = []
    seen_ocr: List[Tuple[Tuple[int, int, int, int], str]] = []
    next_idx = start_idx

    for box in boxes:
        bx1, by1, bx2, by2 = box.bounds
        dx1 = int(round((bx1 + off_x) * scale_to_device_x))
        dy1 = int(round((by1 + off_y) * scale_to_device_y))
        dx2 = int(round((bx2 + off_x) * scale_to_device_x))
        dy2 = int(round((by2 + off_y) * scale_to_device_y))

        if screen_width > 0:
            dx1 = max(0, min(screen_width, dx1))
            dx2 = max(0, min(screen_width, dx2))
        if screen_height > 0:
            dy1 = max(0, min(screen_height, dy1))
            dy2 = max(0, min(screen_height, dy2))

        if dx2 <= dx1 or dy2 <= dy1:
            continue

        dev_bounds = (dx1, dy1, dx2, dy2)
        label = box.text

        # Deduplicate against existing UI elements or earlier OCR elements at the same position
        if any(_boxes_overlap_same_text(dev_bounds, label, el.bounds, el.label) for el in existing):
            continue
        if any(_boxes_overlap_same_text(dev_bounds, label, prev_b, prev_l) for prev_b, prev_l in seen_ocr):
            continue

        seen_ocr.append((dev_bounds, label))
        cx = (dx1 + dx2) // 2
        cy = (dy1 + dy2) // 2

        elements.append(
            Element(
                idx=next_idx,
                node_type="ocr",
                label=label,
                resource_id="",
                short_id="",
                bounds=dev_bounds,
                center=(cx, cy),
                flags=[],
                raw_class="ocr.Text",
                package="",
            )
        )
        next_idx += 1

    return elements


def merge_ocr_into_snapshot(
    snapshot: Optional[Snapshot],
    ocr_boxes: List[OcrBox],
    crop_offset: Tuple[int, int],
    scale_to_device_x: float,
    scale_to_device_y: float,
    fallback_snap_id: int,
    screen_width: int,
    screen_height: int,
) -> Tuple[Snapshot, List[Element]]:
    """Merge OCR detections into existing UI Snapshot (or build a new Snapshot) so `llmadb tap` can target them."""
    if snapshot is None:
        base_elements: List[Element] = []
        start_idx = 1
        snap = Snapshot(
            id=fallback_snap_id,
            screen_width=screen_width,
            screen_height=screen_height,
            app_package="",
            rotation=0,
            elements=[],
        )
    else:
        base_elements = list(snapshot.elements)
        start_idx = max((el.idx for el in base_elements), default=0) + 1
        snap = snapshot

    ocr_elements = map_ocr_boxes_to_device_elements(
        boxes=ocr_boxes,
        crop_offset=crop_offset,
        scale_to_device_x=scale_to_device_x,
        scale_to_device_y=scale_to_device_y,
        screen_width=snap.screen_width or screen_width,
        screen_height=snap.screen_height or screen_height,
        existing_elements=base_elements,
        start_idx=start_idx,
    )

    snap.elements = base_elements + ocr_elements
    return snap, ocr_elements

