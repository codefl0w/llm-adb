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
    from llmadb.errors import E_UNSUPPORTED

    monkeypatch.setattr("llmadb.commands.input.resolve_device", lambda adb, explicit_serial=None: "dev1")
    monkeypatch.setattr("llmadb.commands.input.load_snapshot", lambda serial: None)

    class DummyAdb:
        def run(self, args, **kwargs):
            raise AssertionError("adb.run should not be called for non-ASCII input")

    with pytest.raises(LlmadbError) as exc:
        run_type(["test çğıöşü"], DummyAdb())
    assert exc.value.code == E_UNSUPPORTED
    assert "non-ASCII" in exc.value.message
