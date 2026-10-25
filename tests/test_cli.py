"""Tests for CLI dispatcher and argument parsing."""

import io
import sys
import pytest

from llmadb.cli import main, parse_global_args, resolve_passthrough_serial
from llmadb.adb import Adb
from llmadb.errors import E_USAGE, EXIT_USAGE, LlmadbError


def test_parse_global_args_flags():
    serial, timeout, max_lines, help_llm, show_help, show_ver, escape, remaining = parse_global_args([
        "-s", "emu1",
        "--timeout", "5.5",
        "--max-lines", "20",
        "devices"
    ])
    assert serial == "emu1"
    assert timeout == 5.5
    assert max_lines == 20
    assert help_llm is False
    assert show_help is False
    assert show_ver is False
    assert escape is False
    assert remaining == ["devices"]


def test_parse_global_args_escape_hatch():
    serial, timeout, max_lines, help_llm, show_help, show_ver, escape, remaining = parse_global_args([
        "--", "devices", "-l"
    ])
    assert escape is True
    assert remaining == ["devices", "-l"]


def test_parse_global_args_invalid_timeout():
    with pytest.raises(LlmadbError) as exc:
        parse_global_args(["--timeout", "not-a-number", "devices"])
    assert exc.value.code == E_USAGE
    assert exc.value.exit_code == EXIT_USAGE


def test_resolve_passthrough_serial():
    adb = Adb()
    # Server command should never inject serial
    assert resolve_passthrough_serial(adb, "emu1", ["start-server"]) is None
    assert resolve_passthrough_serial(adb, "emu1", ["version"]) is None

    # Explicit -s in passthrough args should not double-inject
    assert resolve_passthrough_serial(adb, "emu1", ["-s", "emu2", "shell"]) is None

    # Normal command with explicit serial
    assert resolve_passthrough_serial(adb, "emu1", ["shell", "ls"]) == "emu1"


def test_help_llm_output(capsys):
    ret = main(["--help-llm"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Token-efficient ADB wrapper for LLM agents." in captured.out
    assert "devices:" in captured.out


def test_run_devices_command(monkeypatch, capsys):
    from llmadb.commands.devices import run_devices

    class MockAdb:
        def run(self, args, **kwargs):
            return AdbResult(
                stdout=b"List of devices attached\nemu1 device model:TestModel transport_id:1\n",
                stderr=b"",
                code=0,
            )

    from llmadb.adb import Result as AdbResult
    ret = run_devices([], MockAdb())
    assert ret == 0
    captured = capsys.readouterr()
    assert captured.out == "emu1\tdevice\tTestModel\ttransport_id:1\n"


def test_run_devices_empty_raises():
    from llmadb.commands.devices import run_devices
    from llmadb.errors import E_NO_DEVICE, LlmadbError

    class EmptyAdb:
        def run(self, args, **kwargs):
            return AdbResult(stdout=b"List of devices attached\n\n", stderr=b"", code=0)

    from llmadb.adb import Result as AdbResult
    with pytest.raises(LlmadbError) as exc:
        run_devices([], EmptyAdb())
    assert exc.value.code == E_NO_DEVICE
    assert exc.value.exit_code == 3


def test_main_dispatches_new_commands(monkeypatch):
    called = []
    monkeypatch.setattr("llmadb.cli.run_rotate", lambda args, adb, serial=None, max_lines=None: (called.append("rotate"), 0)[1])
    monkeypatch.setattr("llmadb.cli.run_status", lambda args, adb, serial=None, max_lines=None: (called.append("status"), 0)[1])
    monkeypatch.setattr("llmadb.cli.run_clear_cache", lambda args, adb, serial=None, max_lines=None: (called.append("clear-cache"), 0)[1])
    monkeypatch.setattr("llmadb.cli.run_hardware", lambda args, adb, serial=None, max_lines=None: (called.append(f"hardware:{','.join(args)}"), 0)[1])

    assert main(["rotate"]) == 0
    assert main(["status"]) == 0
    assert main(["clear-cache"]) == 0
    assert main(["hardware", "--json"]) == 0
    assert called == ["rotate", "status", "clear-cache", "hardware:--json"]


