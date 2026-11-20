"""Tests for input primitives: text escaping, swipe math, and key mapping."""

import pytest

from llmadb.commands.input import compute_swipe_coords, escape_input_text
from llmadb.errors import E_USAGE, LlmadbError


def test_escape_input_text():
    assert escape_input_text("hello world") == "hello%sworld"
    assert escape_input_text("user@example.com") == "user@example.com"
    assert escape_input_text("foo&bar;baz") == r"foo\&bar\;baz"
    assert escape_input_text('He said "hello"') == r"He%ssaid%s\"hello\""


def test_compute_swipe_coords_up():
    x1, y1, x2, y2 = compute_swipe_coords("up", 0.5, 1000, 2000)
    assert x1 == 500
    assert x2 == 500
    # finger moves up from y1=1500 to y2=500
    assert y1 == 1500
    assert y2 == 500


def test_compute_swipe_coords_down():
    x1, y1, x2, y2 = compute_swipe_coords("down", 0.5, 1000, 2000)
    assert x1 == 500
    assert x2 == 500
    # finger moves down from y1=500 to y2=1500
    assert y1 == 500
    assert y2 == 1500


def test_compute_swipe_coords_invalid():
    with pytest.raises(LlmadbError) as exc:
        compute_swipe_coords("diagonal", 0.5, 1000, 2000)
    assert exc.value.code == E_USAGE


def test_run_type_rejects_non_ascii(monkeypatch):
    from llmadb.commands.input import run_type
    from llmadb.errors import E_UNSUPPORTED, EXIT_USAGE

    monkeypatch.setattr("llmadb.commands.input.resolve_device", lambda adb, explicit_serial=None: "dev1")
    monkeypatch.setattr("llmadb.commands.input.load_snapshot", lambda serial: None)

    class DummyAdb:
        def run(self, args, **kwargs):
            raise AssertionError("adb.run should not be called for non-ASCII input")

    with pytest.raises(LlmadbError) as exc:
        run_type(["test çğıöşü"], DummyAdb())
    assert exc.value.code == E_UNSUPPORTED
    assert exc.value.exit_code == EXIT_USAGE
    assert "non-ASCII" in exc.value.message


def test_run_type_clear_over_40_chars(monkeypatch):
    from llmadb.adb import Result
    from llmadb.commands.input import run_type
    from llmadb.uitree import Element, Snapshot

    long_existing_text = "https://example.com/some/very/long/path/that/exceeds/forty/characters/easily/1234567890"
    assert len(long_existing_text) > 80

    snap = Snapshot(
        id=1,
        screen_width=1080,
        screen_height=2400,
        app_package="com.android.chrome",
        rotation=0,
        elements=[
            Element(
                idx=1,
                node_type="input",
                label=long_existing_text,
                resource_id="com.android.chrome:id/url_bar",
                short_id="url_bar",
                bounds=(100, 100, 980, 200),
                center=(540, 150),
                flags=["focused"],
            )
        ],
    )

    monkeypatch.setattr("llmadb.commands.input.resolve_device", lambda adb, explicit_serial=None: "dev1")
    monkeypatch.setattr("llmadb.commands.input.load_snapshot", lambda serial: snap)

    calls = []
    timeouts = []

    class RecordingAdb:
        def run(self, args, **kwargs):
            calls.append(args)
            timeouts.append(kwargs.get("timeout"))
            return Result(stdout=b"", stderr=b"", code=0)

    rc = run_type(["--clear", "newtext", "--no-ui"], RecordingAdb())
    assert rc == 0
    # 1) Move-to-end (123) + chunked backspaces (>= len(long_existing_text) + 15) in one shell command
    assert calls[0][0] == "shell"
    script = calls[0][1]
    assert script.startswith("input keyevent 123; input keyevent 67")
    assert "keycombination" not in script
    assert script.replace(";", " ").split().count("67") >= len(long_existing_text)
    assert timeouts[0] >= 12.0
    # 2) Type new text
    assert calls[1] == ["shell", "input", "text", "newtext"]


def test_run_type_clear_legacy_fallback_over_40_chars(monkeypatch):
    from llmadb.adb import Result
    from llmadb.commands.input import run_type

    monkeypatch.setattr("llmadb.commands.input.resolve_device", lambda adb, explicit_serial=None: "dev1")
    monkeypatch.setattr("llmadb.commands.input.load_snapshot", lambda serial: None)

    calls = []
    timeouts = []

    class LegacyAdb:
        def run(self, args, **kwargs):
            calls.append(args)
            timeouts.append(kwargs.get("timeout"))
            return Result(stdout=b"", stderr=b"", code=0)

    rc = run_type(["--clear", "fallback", "--no-ui"], LegacyAdb())
    assert rc == 0
    assert calls[0][0] == "shell"
    script = calls[0][1]
    assert script.startswith("input keyevent 123; input keyevent 67")
    # Default clear sends >= 100 chunked backspaces (>40 chars) with scaled timeout for API 24
    assert script.replace(";", " ").split().count("67") >= 100
    assert timeouts[0] >= 12.0
    assert calls[1] == ["shell", "input", "text", "fallback"]
