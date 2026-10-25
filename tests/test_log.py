"""Tests for 'log' and 'mark' commands: deduplication, PID filtering, and timestamp formatting."""

import pytest

from llmadb.adb import Result as AdbResult
from llmadb.commands.log import format_and_collapse_logs, run_log, run_mark
from llmadb.errors import E_USAGE, LlmadbError

SAMPLE_LOGCAT = """--------- beginning of main
10-18 02:23:45.101  1234  1234 D TagOne  : Debug message ignored at W
10-18 02:23:45.250  1234  5678 W Network : Connection retry failed
10-18 02:23:45.500  1234  5678 W Network : Connection retry failed
10-18 02:23:46.120  1234  5678 W Network : Connection retry failed
10-18 02:23:47.999  9999  9999 E OtherApp: Fatal crash in other process
10-18 02:23:48.005  1234  5678 E AndroidRuntime: FATAL EXCEPTION: main
"""


def test_format_and_collapse_logs_dedup_and_level():
    lines = format_and_collapse_logs(
        raw_text=SAMPLE_LOGCAT,
        min_level="W",
        full_timestamps=False,
    )
    assert len(lines) == 3
    # Sub-second '.250' stripped, consecutive 3 duplicates collapsed with '... x3'
    assert lines[0] == "10-18 02:23:45 W Network: Connection retry failed ... x3"
    assert lines[1] == "10-18 02:23:47 E OtherApp: Fatal crash in other process"
    assert lines[2] == "10-18 02:23:48 E AndroidRuntime: FATAL EXCEPTION: main"


def test_format_and_collapse_logs_pid_filter():
    lines = format_and_collapse_logs(
        raw_text=SAMPLE_LOGCAT,
        min_level="V",
        full_timestamps=False,
        allowed_pids={"1234"},
    )
    assert len(lines) == 3
    assert all("OtherApp" not in line for line in lines)


def test_mark_and_log_since_mark(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("llmadb.cache.get_base_cache_dir", lambda: tmp_path)
    monkeypatch.setattr("llmadb.commands.log.resolve_device", lambda adb, explicit_serial=None: "emu1")

    recorded_cmds = []

    class FakeAdb:
        def run(self, args, **kwargs):
            recorded_cmds.append(args)
            if 'date +"%m-%d %H:%M:%S.000"' in args:
                return AdbResult(stdout=b"10-18 21:55:00.000\n", stderr=b"", code=0)
            return AdbResult(stdout=SAMPLE_LOGCAT.encode("utf-8"), stderr=b"", code=0)

    adb = FakeAdb()
    assert run_mark([], adb) == 0
    assert capsys.readouterr().out == "mark=10-18 21:55:00.000\n"

    assert run_log(["--since-mark", "--level", "E"], adb) == 0
    out = capsys.readouterr().out
    assert "FATAL EXCEPTION: main" in out
    assert any("-T" in cmd and "'10-18 21:55:00.000'" in cmd for cmd in recorded_cmds)


def test_log_since_mark_without_mark_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("llmadb.cache.get_base_cache_dir", lambda: tmp_path)
    monkeypatch.setattr("llmadb.commands.log.resolve_device", lambda adb, explicit_serial=None: "emu1")

    class DummyAdb:
        pass

    with pytest.raises(LlmadbError) as exc:
        run_log(["--since-mark"], DummyAdb())
    assert exc.value.code == E_USAGE
