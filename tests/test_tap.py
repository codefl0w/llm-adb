"""Tests for tap target resolution and guards."""

import pytest

from llmadb.adb import Result as AdbResult
from llmadb.commands.tap import resolve_tap_target, run_tap
from llmadb.errors import E_AMBIGUOUS, E_NOT_FOUND, E_USAGE, LlmadbError
from llmadb.uitree import Element, Snapshot


def make_sample_snapshot():
    elements = [
        Element(
            idx=1,
            node_type="button",
            label="Save",
            resource_id="com.example:id/btn_save",
            short_id="btn_save",
            bounds=(10, 20, 100, 60),
            center=(55, 40),
        ),
        Element(
            idx=2,
            node_type="button",
            label="Cancel",
            resource_id="com.example:id/btn_cancel",
            short_id="btn_cancel",
            bounds=(110, 20, 200, 60),
            center=(155, 40),
        ),
        Element(
            idx=3,
            node_type="text",
            label="Save as draft",
            resource_id="com.example:id/txt_draft",
            short_id="txt_draft",
            bounds=(10, 70, 200, 100),
            center=(105, 85),
        ),
    ]
    return Snapshot(
        id=5,
        screen_width=1080,
        screen_height=1920,
        app_package="com.example",
        rotation=0,
        elements=elements,
    )


def test_resolve_by_index():
    snap = make_sample_snapshot()
    cx, cy, desc = resolve_tap_target("2", None, None, snap, None)
    assert cx == 155
    assert cy == 40
    assert "Cancel" in desc


def test_resolve_by_coords():
    cx, cy, desc = resolve_tap_target("300,500", None, None, None, None)
    assert cx == 300
    assert cy == 500
    assert desc == "coords @300,500"


def test_resolve_by_coords_reports_hit_element():
    snap = make_sample_snapshot()
    cx, cy, desc = resolve_tap_target("55,40", None, None, snap, None)
    assert cx == 55
    assert cy == 40
    assert 'hits #1 [button] "Save"' in desc


def test_resolve_by_id():
    snap = make_sample_snapshot()
    cx, cy, desc = resolve_tap_target("", None, "btn_save", snap, None)
    assert cx == 55
    assert cy == 40


def test_resolve_by_text_exact():
    snap = make_sample_snapshot()
    # "Save" matches exact label on element 1
    cx, cy, desc = resolve_tap_target("", "Save", None, snap, None)
    assert cx == 55
    assert cy == 40


def test_resolve_by_text_ambiguous():
    snap = make_sample_snapshot()
    # "draft" is substring of "Save as draft"
    cx, cy, desc = resolve_tap_target("", "draft", None, snap, None)
    assert cx == 105
    assert cy == 85


def test_resolve_stale_snap_guard():
    snap = make_sample_snapshot()
    with pytest.raises(LlmadbError) as exc:
        resolve_tap_target("1", None, None, snap, expected_snap_id=4)
    assert exc.value.code == E_NOT_FOUND
    assert "stale" in exc.value.message


def test_resolve_clamps_bottom_gesture_inset():
    el = Element(
        idx=1,
        node_type="button",
        label="Accept Risk",
        resource_id="org.mozilla.firefox:id/advancedPanelAcceptButtonContainer",
        short_id="advancedPanelAcceptButtonContainer",
        bounds=(120, 2328, 960, 2412),
        center=(540, 2370),
    )
    snap = Snapshot(
        id=34,
        screen_width=1080,
        screen_height=2412,
        app_package="org.mozilla.firefox",
        rotation=0,
        elements=[el],
    )
    cx, cy, _ = resolve_tap_target("1", None, None, snap, None)
    assert cx == 540
    # Must be clamped above the bottom 66px gesture zone (y < 2346)
    assert 2328 < cy < 2346


class MockTapAdb:
    def __init__(self):
        self.commands = []

    def run(self, args, **kwargs):
        self.commands.append(args)
        return AdbResult(stdout=b"", stderr=b"", code=0)


def test_run_tap_hold_default_and_explicit(monkeypatch, capsys):
    snap = make_sample_snapshot()
    monkeypatch.setattr("llmadb.commands.tap.resolve_device", lambda adb, explicit_serial=None: "emu1")
    monkeypatch.setattr("llmadb.commands.tap.load_snapshot", lambda serial: snap)

    # 1. Default --hold (500ms) after target
    adb = MockTapAdb()
    assert run_tap(["1", "--hold", "--no-ui"], adb) == 0
    assert adb.commands[-1] == ["shell", "input", "swipe", "55", "40", "55", "40", "500"]
    assert "tapped #1 [button] \"Save\" @55,40 (hold 500ms)" in capsys.readouterr().out

    # 2. Explicit --hold 1200 after target
    adb = MockTapAdb()
    assert run_tap(["1", "--hold", "1200", "--no-ui"], adb) == 0
    assert adb.commands[-1] == ["shell", "input", "swipe", "55", "40", "55", "40", "1200"]
    assert "(hold 1200ms)" in capsys.readouterr().out

    # 3. --hold=800 syntax
    adb = MockTapAdb()
    assert run_tap(["--hold=800", "2", "--no-ui"], adb) == 0
    assert adb.commands[-1] == ["shell", "input", "swipe", "155", "40", "155", "40", "800"]

    # 4. --hold before single target index uses default 500ms and keeps target
    adb = MockTapAdb()
    assert run_tap(["--hold", "2", "--no-ui"], adb) == 0
    assert adb.commands[-1] == ["shell", "input", "swipe", "155", "40", "155", "40", "500"]

    # 5. --hold 900 before target index
    adb = MockTapAdb()
    assert run_tap(["--hold", "900", "2", "--no-ui"], adb) == 0
    assert adb.commands[-1] == ["shell", "input", "swipe", "155", "40", "155", "40", "900"]

    # 6. --hold 750 with --text
    adb = MockTapAdb()
    assert run_tap(["--hold", "750", "--text", "Save", "--no-ui"], adb) == 0
    assert adb.commands[-1] == ["shell", "input", "swipe", "55", "40", "55", "40", "750"]


def test_run_tap_hold_invalid_duration(monkeypatch):
    monkeypatch.setattr("llmadb.commands.tap.resolve_device", lambda adb, explicit_serial=None: "emu1")

    for bad_args in (["1", "--hold", "abc"], ["1", "--hold", "-100"], ["1", "--hold=0"]):
        with pytest.raises(LlmadbError) as exc:
            run_tap(bad_args, MockTapAdb())
        assert exc.value.code == E_USAGE
