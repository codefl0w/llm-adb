"""Tests for app lifecycle commands: launch, stop, and clear."""

import pytest

from llmadb.adb import Result as AdbResult
from llmadb.commands.launch import resolve_launcher_component, run_clear, run_launch, run_stop
from llmadb.errors import E_ADB, E_NOT_FOUND, LlmadbError


def test_resolve_launcher_component_via_cmd():
    class FakeAdb:
        def run(self, args, **kwargs):
            return AdbResult(
                stdout=b"priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\ncom.android.chrome/com.google.android.apps.chrome.Main\n",
                stderr=b"",
                code=0,
            )

    comp = resolve_launcher_component(FakeAdb(), "com.android.chrome", "emu1")
    assert comp == "com.android.chrome/com.google.android.apps.chrome.Main"


def test_run_launch_monkey_fallback(monkeypatch, capsys):
    monkeypatch.setattr("llmadb.commands.launch.resolve_device", lambda adb, explicit_serial=None: "emu1")
    monkeypatch.setattr("llmadb.commands.launch.get_current_state", lambda adb, serial=None: "com.example.app/.Main rot=0 keyboard=hidden")
    monkeypatch.setattr("time.sleep", lambda s: None)

    calls = []

    class FakeAdb:
        def run(self, args, **kwargs):
            calls.append(args)
            if "resolve-activity" in args or "dumpsys" in args:
                return AdbResult(stdout=b"No activity found\n", stderr=b"", code=0)
            if "monkey" in args:
                return AdbResult(stdout=b"Events injected: 1\n", stderr=b"", code=0)
            return AdbResult(stdout=b"", stderr=b"", code=0)

    ret = run_launch(["com.example.app"], FakeAdb())
    assert ret == 0
    assert any("monkey" in c for c in calls)
    assert capsys.readouterr().out == "com.example.app/.Main rot=0 keyboard=hidden\n"


def test_run_stop_and_clear(monkeypatch, capsys):
    monkeypatch.setattr("llmadb.commands.launch.resolve_device", lambda adb, explicit_serial=None: "emu1")

    class FakeAdb:
        def run(self, args, **kwargs):
            if "clear" in args:
                return AdbResult(stdout=b"Success\n", stderr=b"", code=0)
            return AdbResult(stdout=b"", stderr=b"", code=0)

    assert run_stop(["com.example.app"], FakeAdb()) == 0
    assert capsys.readouterr().out == "stopped com.example.app\n"

    assert run_clear(["com.example.app"], FakeAdb()) == 0
    assert capsys.readouterr().out == "cleared com.example.app\n"


def test_run_clear_failure(monkeypatch):
    monkeypatch.setattr("llmadb.commands.launch.resolve_device", lambda adb, explicit_serial=None: "emu1")

    class FailAdb:
        def run(self, args, **kwargs):
            return AdbResult(stdout=b"Failed\n", stderr=b"", code=0)

    with pytest.raises(LlmadbError) as exc:
        run_clear(["com.missing.app"], FailAdb())
    assert exc.value.code == E_ADB
