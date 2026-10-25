"""Tests for screen rotation command and parser."""

import pytest

from llmadb.adb import Result as AdbResult
from llmadb.commands.rotate import (
    get_rotation_state,
    parse_target_rotation,
    run_rotate,
)
from llmadb.errors import E_USAGE, LlmadbError


class MockRotateAdb:
    def __init__(self, user_rot="0", display_rot="0", auto="0"):
        self.user_rot = user_rot
        self.display_rot = display_rot
        self.auto = auto
        self.executed_commands = []

    def run(self, args, **kwargs):
        cmd = " ".join(args)
        self.executed_commands.append(cmd)

        if "___LLMADB_BATCH_auto___" in cmd:
            out = (
                f"___LLMADB_BATCH_auto___\n{self.auto}\n"
                f"___LLMADB_BATCH_user_rot___\n{self.user_rot}\n"
                f"___LLMADB_BATCH_display_rot___\n    mRotation={self.display_rot} mDeferredRotationPauseCount=0\n"
            )
            return AdbResult(stdout=out.encode("utf-8"), stderr=b"", code=0)

        for rot in "0123":
            if f"user_rotation {rot}" in cmd:
                self.user_rot = rot
        if "accelerometer_rotation 1" in cmd:
            self.auto = "1"
        elif "accelerometer_rotation 0" in cmd:
            self.auto = "0"

        return AdbResult(stdout=b"", stderr=b"", code=0)


@pytest.fixture(autouse=True)
def _fake_device(monkeypatch):
    monkeypatch.setattr("llmadb.commands.rotate.resolve_device", lambda adb, explicit_serial=None: "emu1")


def test_parse_target_rotation():
    assert parse_target_rotation("0") == 0
    assert parse_target_rotation("portrait") == 0
    assert parse_target_rotation("port") == 0

    assert parse_target_rotation("1") == 1
    assert parse_target_rotation("Landscape") == 1
    assert parse_target_rotation("land") == 1

    assert parse_target_rotation("2") == 2
    assert parse_target_rotation("reverse-portrait") == 2

    assert parse_target_rotation("3") == 3
    assert parse_target_rotation("reverse-landscape") == 3

    assert parse_target_rotation("invalid") is None
    assert parse_target_rotation("auto") is None


def test_get_rotation_state_auto_uses_display_rotation():
    # Auto-rotate on: user_rotation is stale, live display rotation wins
    assert get_rotation_state(MockRotateAdb(user_rot="0", display_rot="1", auto="1")) == (1, True)
    # Auto-rotate off: user_rotation is authoritative (portrait-locked app keeps display at 0)
    assert get_rotation_state(MockRotateAdb(user_rot="1", display_rot="0", auto="0")) == (1, False)


def test_run_rotate_toggle(capsys):
    adb = MockRotateAdb(user_rot="0")
    assert run_rotate([], adb) == 0
    assert capsys.readouterr().out == "rot=1 (landscape) auto_rotate=off\n"
    assert any("user_rotation 1" in cmd for cmd in adb.executed_commands)

    adb2 = MockRotateAdb(user_rot="1")
    assert run_rotate([], adb2) == 0
    assert capsys.readouterr().out == "rot=0 (portrait) auto_rotate=off\n"
    assert any("user_rotation 0" in cmd for cmd in adb2.executed_commands)


def test_run_rotate_explicit(capsys):
    adb = MockRotateAdb()
    assert run_rotate(["1"], adb) == 0
    assert capsys.readouterr().out == "rot=1 (landscape) auto_rotate=off\n"
    assert any("accelerometer_rotation 0" in cmd for cmd in adb.executed_commands)

    assert run_rotate(["portrait"], adb) == 0
    assert capsys.readouterr().out == "rot=0 (portrait) auto_rotate=off\n"


def test_run_rotate_auto(capsys):
    adb = MockRotateAdb(user_rot="0", display_rot="3")
    assert run_rotate(["auto"], adb) == 0
    assert capsys.readouterr().out == "rot=3 (reverse-landscape) auto_rotate=on\n"
    assert any("accelerometer_rotation 1" in cmd for cmd in adb.executed_commands)


def test_run_rotate_invalid():
    with pytest.raises(LlmadbError) as exc:
        run_rotate(["invalid-arg"], MockRotateAdb())
    assert exc.value.code == E_USAGE
