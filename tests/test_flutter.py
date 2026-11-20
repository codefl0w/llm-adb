"""Tests for Flutter app support and Android 7/17 cross-generation edge cases."""

import pytest

from llmadb.adb import Result as AdbResult
from llmadb.cache import load_snapshot, save_snapshot
from llmadb.commands.rotate import run_rotate
from llmadb.commands.tap import resolve_tap_target, settle_ui
from llmadb.commands.ui import get_ui_snapshot
from llmadb.errors import E_NOT_FOUND, LlmadbError
from llmadb.uitree import Element, Snapshot, parse_ui_tree, parse_window_state


def test_parse_window_state_prefers_override_cur_over_physical_init():
    """Galaxy Note5 Android 7 reports init=1440x2560 before cur=720x1280; cur must win."""
    dumpsys_a7 = """
    init=1440x2560 560dpi base=720x1280 280dpi cur=720x1280 app=720x1280 rng=720x678-1280x1238
    mCurrentFocus=Window{6a35b51 u0 com.example.flutter_edge_lab/com.example.flutter_edge_lab.MainActivity}
    InputWindowHandle=Window{6a35b51 u0 com.example.flutter_edge_lab/com.example.flutter_edge_lab.MainActivity}, layer=21000, frame=[0,0,1440,2560], visible=true
    """
    pkg, w, h, warnings = parse_window_state(dumpsys_a7)
    assert pkg == "com.example.flutter_edge_lab"
    assert (w, h) == (720, 1280)
    assert warnings == []


def test_parse_window_state_ignores_landscape_statusbar():
    """Landscape StatusBar on Android 17 has thin width (63px) and full height (2400px)."""
    dumpsys_land = """
    init=1080x2400 420dpi cur=2400x1080 app=2400x1080
    mCurrentFocus=Window{6a35b51 u0 com.example.flutter_edge_lab/com.example.flutter_edge_lab.MainActivity}
      7: name=3acb33b StatusBar, id=97, displayId=0, inputConfig=NOT_FOCUSABLE | TRUSTED_OVERLAY, alpha=1, frame=[1017,0][1080,2400], globalScale=1, applicationInfo.name=, applicationInfo.token=<null>, touchableRegion=[1017,0][1080,2400], ownerPid=6161
      16: name=6a35b51 com.example.flutter_edge_lab/com.example.flutter_edge_lab.MainActivity, id=105, displayId=0, inputConfig=0x0, alpha=1, frame=[0,0][2400,1080], globalScale=1, applicationInfo.name=, applicationInfo.token=0x123, touchableRegion=[0,0][2400,1080], ownerPid=6602
    """
    pkg, w, h, warnings = parse_window_state(dumpsys_land)
    assert pkg == "com.example.flutter_edge_lab"
    assert (w, h) == (2400, 1080)
    assert warnings == []


def test_flutter_semantics_identifier_hint_slider_and_unlabeled_warnings():
    xml = b"""<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.example.flutter_edge_lab" bounds="[0,0][1080,2400]">
        <node index="0" text="" resource-id="android:id/content" class="android.widget.FrameLayout" package="com.example.flutter_edge_lab" bounds="[0,0][1080,2400]">
          <node index="0" text="" resource-id="id_only_marker" class="android.view.View" package="com.example.flutter_edge_lab" content-desc="" clickable="false" enabled="true" bounds="[32,100][1049,174]" hint="" />
          <node index="1" text="" resource-id="input_email" class="android.widget.EditText" package="com.example.flutter_edge_lab" content-desc="" clickable="true" enabled="true" bounds="[37,200][1043,347]" hint="Email Address" />
          <node index="2" text="prefilled@example.com" resource-id="input_long" class="android.widget.EditText" package="com.example.flutter_edge_lab" content-desc="" clickable="true" enabled="true" bounds="[37,370][1043,517]" hint="Long Prefilled Field" />
          <node index="3" text="" resource-id="" class="android.widget.SeekBar" package="com.example.flutter_edge_lab" content-desc="40%" clickable="true" enabled="true" bounds="[483,550][609,676]" hint="" />
          <node NAF="true" index="4" text="" resource-id="" class="android.widget.Button" package="com.example.flutter_edge_lab" content-desc="" clickable="true" enabled="true" bounds="[50,700][180,830]" hint="" />
          <node NAF="true" index="5" text="" resource-id="" class="android.widget.Button" package="com.example.flutter_edge_lab" content-desc="" clickable="true" enabled="true" bounds="[250,700][380,830]" hint="" />
          <node NAF="true" index="6" text="" resource-id="" class="android.view.View" package="com.example.flutter_edge_lab" content-desc="" clickable="true" enabled="true" bounds="[32,900][1049,1500]" hint="" />
          <node index="7" text="" resource-id="" class="android.view.View" package="com.example.flutter_edge_lab" content-desc="" clickable="false" enabled="true" bounds="[32,1550][1049,1850]" hint="" />
        </node>
      </node>
    </hierarchy>"""

    snap = parse_ui_tree(xml, snapshot_id=1)
    # Bare Semantics(identifier:) included, while native android:id/content container is NOT included
    ids = [el.short_id for el in snap.elements]
    assert "id_only_marker" in ids
    assert "content" not in ids

    # Empty EditText falls back to hint with [hint] flag
    email_el = next(el for el in snap.elements if el.short_id == "input_email")
    assert email_el.label == "Email Address"
    assert "hint" in email_el.flags
    assert email_el.hint == "Email Address"

    # Prefilled EditText keeps text as label and preserves hint metadata
    long_el = next(el for el in snap.elements if el.short_id == "input_long")
    assert long_el.label == "prefilled@example.com"
    assert "hint" not in long_el.flags
    assert long_el.hint == "Long Prefilled Field"

    # SeekBar maps to slider
    slider_el = next(el for el in snap.elements if el.label == "40%")
    assert slider_el.node_type == "slider"

    # Both CustomPaint [32,900][1049,1500] and ExcludeSemantics [32,1550][1049,1850] flagged
    assert any("! unlabeled region [32,900][1049,1500]" in w for w in snap.warnings)
    assert any("! unlabeled region [32,1550][1049,1850]" in w for w in snap.warnings)

    # 2 unlabeled IconButtons surfaced in concise warning
    assert any("2 unlabeled controls" in w for w in snap.warnings)


def test_tap_text_matches_ocr_dropped_spaces_and_input_hint():
    snap = Snapshot(
        id=10,
        screen_width=1080,
        screen_height=2400,
        app_package="com.example.flutter_edge_lab",
        rotation=0,
        elements=[
            Element(
                idx=1,
                node_type="ocr",
                label="CLAIMREWARD",
                resource_id="",
                short_id="",
                bounds=(100, 1000, 980, 1120),
                center=(540, 1060),
            ),
            Element(
                idx=2,
                node_type="input",
                label="existing value",
                resource_id="input_long",
                short_id="input_long",
                bounds=(37, 500, 1043, 640),
                center=(540, 570),
                hint="Long Prefilled Field",
            ),
        ],
    )
    # Whitespace-collapsed match handles RapidOCR dropping spaces
    cx, cy, desc = resolve_tap_target("", "CLAIM REWARD", None, snap, None)
    assert (cx, cy) == (540, 1060)
    assert "CLAIMREWARD" in desc

    # Hint fallback matches prefilled Flutter TextField by its labelText/hintText
    cx2, cy2, desc2 = resolve_tap_target("", "Long Prefilled Field", None, snap, None)
    assert (cx2, cy2) == (540, 570)
    assert "Long Prefilled Field" in desc2


def test_settle_ui_retains_ocr_elements_when_screen_stays_busy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("llmadb.commands.tap.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "llmadb.commands.tap.dump_hierarchy_bytes",
        lambda adb, serial=None: b"ERROR: could not get idle state.\n",
    )
    monkeypatch.setattr(
        "llmadb.commands.ui.detect_window_state",
        lambda adb, serial=None: ("com.example.flutter_edge_lab", 1080, 2400, []),
    )

    prev_ocr_snap = Snapshot(
        id=40,
        screen_width=1080,
        screen_height=2400,
        app_package="com.example.flutter_edge_lab",
        rotation=0,
        elements=[
            Element(
                idx=1,
                node_type="ocr",
                label="FREEZE TICKER",
                resource_id="",
                short_id="",
                bounds=(100, 1400, 980, 1520),
                center=(540, 1460),
            )
        ],
    )

    class DummyAdb:
        pass

    settled = settle_ui(DummyAdb(), serial="emu1", prev_snapshot=prev_ocr_snap)
    assert len(settled.elements) == 1
    assert settled.elements[0].label == "FREEZE TICKER"
    assert any("retained 1 OCR elements" in w for w in settled.warnings)

    # Confirm persisted in cache with warnings intact
    loaded = load_snapshot("emu1")
    assert loaded is not None
    assert len(loaded.elements) == 1
    assert any("busy/animating" in w for w in loaded.warnings)


def test_cold_start_flutter_accessibility_bridge_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("llmadb.commands.ui.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "llmadb.commands.ui.detect_window_state",
        lambda adb, serial=None: ("com.example.flutter_edge_lab", 1080, 2400, []),
    )

    dumps = [
        # First dump: empty cold Flutter FrameLayout before AccessibilityBridge populates
        b'<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0"><node text="" class="android.widget.FrameLayout" package="com.example.flutter_edge_lab" bounds="[0,0][1080,2400]" /></hierarchy>',
        # Second dump: populated Flutter tree
        b'<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0"><node text="" class="android.widget.FrameLayout" package="com.example.flutter_edge_lab" bounds="[0,0][1080,2400]"><node text="" content-desc="Increment" resource-id="btn_increment" class="android.widget.Button" package="com.example.flutter_edge_lab" clickable="true" bounds="[100,400][400,500]" /></node></hierarchy>',
    ]
    call_idx = {"n": 0}

    def fake_dump(adb, serial=None, compressed=False, retries=2):
        res = dumps[min(call_idx["n"], len(dumps) - 1)]
        call_idx["n"] += 1
        return res

    monkeypatch.setattr("llmadb.commands.ui.dump_hierarchy_bytes", fake_dump)

    class DummyAdb:
        pass

    snap = get_ui_snapshot(DummyAdb(), serial="emu1")
    assert call_idx["n"] == 2
    assert len(snap.elements) == 1
    assert snap.elements[0].short_id == "btn_increment"


def test_rotate_invalidates_stale_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("llmadb.commands.rotate.resolve_device", lambda adb, explicit_serial=None: "emu1")

    save_snapshot(
        "emu1",
        Snapshot(id=50, screen_width=1080, screen_height=2400, app_package="com.example", rotation=0, elements=[]),
    )
    assert load_snapshot("emu1") is not None

    class OkAdb:
        def run(self, args, **kwargs):
            return AdbResult(stdout=b"", stderr=b"", code=0)

    assert run_rotate(["landscape"], OkAdb()) == 0
    assert load_snapshot("emu1") is None


def test_empty_busy_snapshot_gives_ocr_hint_on_tap_not_found():
    busy_snap = Snapshot(
        id=99,
        screen_width=1080,
        screen_height=2400,
        app_package="com.example.flutter_edge_lab",
        rotation=0,
        elements=[],
        warnings=["! ui busy/animating (uiautomator could not get idle state); use 'llmadb screen --ocr' or 'llmadb screen' to inspect"],
    )
    with pytest.raises(LlmadbError) as exc:
        resolve_tap_target("", "FREEZE TICKER", None, busy_snap, None)
    assert exc.value.code == E_NOT_FOUND
    assert "llmadb screen --ocr" in exc.value.hint


def test_screen_region_reports_full_device_dimensions_and_region(tmp_path, monkeypatch, capsys):
    import io
    from PIL import Image
    from llmadb.commands.screen import run_screen
    from llmadb.ocr import OcrBox

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("llmadb.commands.screen.resolve_device", lambda adb, explicit_serial=None: "emu1")
    monkeypatch.setattr("llmadb.ocr.is_ocr_available", lambda: True)
    monkeypatch.setattr(
        "llmadb.ocr.extract_ocr_boxes",
        lambda image, **kw: [OcrBox(text="CANVAS BUY", bounds=(50, 200, 250, 260), confidence=0.95)],
    )

    buf = io.BytesIO()
    Image.new("RGB", (720, 1280), color=(20, 20, 20)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    class MockRegionAdb:
        def run(self, args, **kwargs):
            return AdbResult(stdout=png_bytes, stderr=b"", code=0)

    assert run_screen(["--no-ui", "--ocr", "--region", "21,350,699,753"], MockRegionAdb()) == 0
    out = capsys.readouterr().out
    assert "device=720x1280 region=21,350,699,753" in out
    assert '1 ocr "CANVAS BUY" @171,580' in out

