"""Tests for optional OCR module (llmadb.ocr) and `llmadb screen --ocr` integration."""

import io
import pytest
from PIL import Image

from llmadb.adb import Result as AdbResult
from llmadb.cache import load_snapshot
from llmadb.commands.screen import run_screen
from llmadb.commands.tap import resolve_tap_target
from llmadb.errors import E_UNSUPPORTED, E_USAGE, EXIT_USAGE, LlmadbError
from llmadb.ocr import (
    OcrBox,
    extract_ocr_boxes,
    map_ocr_boxes_to_device_elements,
    merge_ocr_into_snapshot,
)
from llmadb.uitree import Element, Snapshot


def test_extract_ocr_boxes_missing_dependency_raises_e_unsupported(monkeypatch):
    monkeypatch.setattr("llmadb.ocr._get_rapidocr_engine", lambda: None)
    monkeypatch.setattr("llmadb.ocr._run_pytesseract", lambda img, conf: None)

    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    with pytest.raises(LlmadbError) as exc:
        extract_ocr_boxes(img)

    assert exc.value.code == E_UNSUPPORTED
    assert exc.value.exit_code == EXIT_USAGE
    assert 'pip install "llm-adb[ocr]"' in exc.value.hint


def test_screen_ocr_fails_fast_when_ocr_unavailable(monkeypatch):
    monkeypatch.setattr("llmadb.commands.screen.resolve_device", lambda adb, explicit_serial=None: "emu1")
    monkeypatch.setattr("llmadb.ocr.is_ocr_available", lambda: False)

    class FailIfCalledAdb:
        def run(self, args, **kwargs):
            raise AssertionError("ADB should not be called if --ocr fails fast on missing dependency")

    with pytest.raises(LlmadbError) as exc:
        run_screen(["--ocr"], FailIfCalledAdb())

    assert exc.value.code == E_UNSUPPORTED
    assert exc.value.exit_code == EXIT_USAGE


def test_extract_ocr_boxes_sorts_reading_order():
    img = Image.new("RGB", (500, 500))
    unsorted_boxes = [
        OcrBox(text="Bottom Button", bounds=(100, 400, 300, 440), confidence=0.95),
        OcrBox(text="Top Right", bounds=(260, 42, 420, 78), confidence=0.91),
        OcrBox(text="Top Left", bounds=(20, 40, 180, 76), confidence=0.98),
    ]
    res = extract_ocr_boxes(img, backend_fn=lambda _im, _c: list(unsorted_boxes))
    assert [b.text for b in res] == ["Top Left", "Top Right", "Bottom Button"]


def test_merge_ocr_into_snapshot_deduplicates_and_indexes():
    existing_el = Element(
        idx=1,
        node_type="text",
        label="Settings",
        resource_id="android:id/title",
        short_id="title",
        bounds=(40, 100, 300, 160),
        center=(170, 130),
    )
    search_el = Element(
        idx=2,
        node_type="input",
        label="Search Settings",
        resource_id="com.android.settings:id/search_action_bar",
        short_id="search_action_bar",
        bounds=(40, 165, 1040, 220),
        center=(540, 192),
    )
    snap = Snapshot(
        id=10,
        screen_width=1080,
        screen_height=2400,
        app_package="com.android.settings",
        rotation=0,
        elements=[existing_el, search_el],
    )

    ocr_boxes = [
        # Duplicate of existing UI element "Settings" at same position -> should be skipped
        OcrBox(text="Settings", bounds=(45, 105, 295, 155), confidence=0.99),
        # Leading 1-char icon glyph artifact ("Q Search Settings") overlapping "Search Settings" -> skipped
        OcrBox(text="Q Search Settings", bounds=(120, 170, 540, 215), confidence=0.94),
        # New visual-only element (e.g. inside WebView or non-idle screen)
        OcrBox(text="Build number", bounds=(60, 2040, 420, 2120), confidence=0.96),
    ]

    merged_snap, new_ocr_elems = merge_ocr_into_snapshot(
        snapshot=snap,
        ocr_boxes=ocr_boxes,
        crop_offset=(0, 0),
        scale_to_device_x=1.0,
        scale_to_device_y=1.0,
        fallback_snap_id=10,
        screen_width=1080,
        screen_height=2400,
    )

    assert len(new_ocr_elems) == 1
    assert new_ocr_elems[0].idx == 3
    assert new_ocr_elems[0].node_type == "ocr"
    assert new_ocr_elems[0].label == "Build number"
    assert new_ocr_elems[0].center == (240, 2080)
    assert len(merged_snap.elements) == 3


def test_map_ocr_boxes_with_region_crop_and_scaling():
    # Suppose device screen is 1440x2560, UI tree is 720x1280 (scale 0.5),
    # and we cropped region (100, 200, 500, 600) in tree coords -> (200, 400) offset in raw screenshot px
    ocr_boxes = [
        OcrBox(text="Proceed", bounds=(40, 60, 240, 140), confidence=0.92),
    ]
    elems = map_ocr_boxes_to_device_elements(
        boxes=ocr_boxes,
        crop_offset=(200, 400),
        scale_to_device_x=0.5,
        scale_to_device_y=0.5,
        screen_width=720,
        screen_height=1280,
        start_idx=5,
    )
    assert len(elems) == 1
    # x1 = (40 + 200) * 0.5 = 120, y1 = (60 + 400) * 0.5 = 230
    # x2 = (240 + 200) * 0.5 = 220, y2 = (140 + 400) * 0.5 = 270
    assert elems[0].bounds == (120, 230, 220, 270)
    assert elems[0].center == (170, 250)
    assert elems[0].idx == 5


def test_run_screen_ocr_persists_snapshot_for_tap(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("llmadb.commands.screen.resolve_device", lambda adb, explicit_serial=None: "emu1")
    monkeypatch.setattr("llmadb.ocr.is_ocr_available", lambda: True)
    monkeypatch.setattr(
        "llmadb.ocr.extract_ocr_boxes",
        lambda image, **kw: [
            OcrBox(text="Accept Risk and Continue", bounds=(120, 1800, 960, 1900), confidence=0.97),
            OcrBox(text="Build number", bounds=(80, 2040, 520, 2120), confidence=0.95),
        ],
    )

    buf = io.BytesIO()
    Image.new("RGB", (1080, 2400), color=(30, 30, 30)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    class MockOcrAdb:
        def run(self, args, **kwargs):
            return AdbResult(stdout=png_bytes, stderr=b"", code=0)

    assert run_screen(["--no-ui", "--ocr"], MockOcrAdb()) == 0
    out = capsys.readouterr().out
    assert "ocr=2" in out
    assert '1 ocr "Accept Risk and Continue" @540,1850' in out
    assert '2 ocr "Build number" @300,2080' in out

    # Verify snapshot was saved to cache and `llmadb tap` can target OCR items by index or --text
    saved = load_snapshot("emu1")
    assert saved is not None
    assert len(saved.elements) == 2

    cx1, cy1, desc1 = resolve_tap_target("1", None, None, saved, None)
    assert (cx1, cy1) == (540, 1850)
    assert "Accept Risk and Continue" in desc1

    cx2, cy2, desc2 = resolve_tap_target("", "Build number", None, saved, None)
    assert (cx2, cy2) == (300, 2080)
    assert "Build number" in desc2


def test_screen_rejects_invalid_region_and_unknown_flags(monkeypatch):
    monkeypatch.setattr("llmadb.commands.screen.resolve_device", lambda adb, explicit_serial=None: "emu1")

    class DummyAdb:
        pass

    for bad_args in (
        ["--unknown-flag"],
        ["--region", "100,200,50,60"],
        ["--region=invalid"],
        ["--max-edge=abc"],
    ):
        with pytest.raises(LlmadbError) as exc:
            run_screen(bad_args, DummyAdb())
        assert exc.value.code == E_USAGE


def test_run_screen_no_ui_ocr_ignores_stale_portrait_cache_on_landscape(tmp_path, monkeypatch, capsys):
    from llmadb.cache import save_snapshot

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("llmadb.commands.screen.resolve_device", lambda adb, explicit_serial=None: "emu1")
    monkeypatch.setattr("llmadb.ocr.is_ocr_available", lambda: True)

    # Pre-populate cache with a Portrait (1080x2400) snapshot id=5
    save_snapshot(
        "emu1",
        Snapshot(id=5, screen_width=1080, screen_height=2400, app_package="com.android.settings", rotation=0, elements=[]),
    )

    # Now mock a Landscape (2400x1080) screenshot with an OCR box near the right edge (x=1800..2200, y=500..600)
    monkeypatch.setattr(
        "llmadb.ocr.extract_ocr_boxes",
        lambda image, **kw: [OcrBox(text="Landscape Item", bounds=(1800, 500, 2200, 600), confidence=0.95)],
    )

    buf = io.BytesIO()
    Image.new("RGB", (2400, 1080), color=(40, 40, 40)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    class MockLandscapeAdb:
        def run(self, args, **kwargs):
            return AdbResult(stdout=png_bytes, stderr=b"", code=0)

    assert run_screen(["--no-ui", "--ocr"], MockLandscapeAdb()) == 0
    out = capsys.readouterr().out
    assert "device=2400x1080" in out
    assert '1 ocr "Landscape Item" @2000,550' in out


