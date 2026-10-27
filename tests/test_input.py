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

    class RecordingAdb:
        def run(self, args, **kwargs):
            calls.append(args)
            return Result(stdout=b"", stderr=b"", code=0)

    rc = run_type(["--clear", "newtext", "--no-ui"], RecordingAdb())
    assert rc == 0
    # 1) Ctrl+A select-all via keycombination 113 29
    assert calls[0] == ["shell", "input", "keycombination", "113", "29"]
    # 2) Delete selection (67) + move-to-end (123) + >= len(long_existing_text) backspaces
    assert calls[1][:4] == ["shell", "input", "keyevent", "67"]
    assert calls[1][4] == "123"
    assert calls[1][5:].count("67") >= len(long_existing_text)
    # 3) Type new text
    assert calls[2] == ["shell", "input", "text", "newtext"]


def test_run_type_clear_legacy_fallback_over_40_chars(monkeypatch):
    from llmadb.adb import Result
    from llmadb.commands.input import run_type

    monkeypatch.setattr("llmadb.commands.input.resolve_device", lambda adb, explicit_serial=None: "dev1")
    monkeypatch.setattr("llmadb.commands.input.load_snapshot", lambda serial: None)

    calls = []

    class LegacyAdb:
        def run(self, args, **kwargs):
            calls.append(args)
            if "keycombination" in args:
                return Result(stdout=b"Error: Unknown command: keycombination\n", stderr=b"", code=1)
            return Result(stdout=b"", stderr=b"", code=0)

    rc = run_type(["--clear", "fallback", "--no-ui"], LegacyAdb())
    assert rc == 0
    assert calls[0] == ["shell", "input", "keycombination", "113", "29"]
    # Legacy fallback uses move-to-end (123) + 100 backspaces (>40 chars)
    assert calls[1][:4] == ["shell", "input", "keyevent", "123"]
    assert calls[1][4:].count("67") >= 100
    assert calls[2] == ["shell", "input", "text", "fallback"]
