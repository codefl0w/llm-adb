"""Tests for shellbatch command delimiter splitting."""

from llmadb.adb import Result
from llmadb.shellbatch import DELIM_PREFIX, DELIM_SUFFIX, run_batch


class MockBatchAdb:
    def __init__(self, raw_output: str):
        self.raw_output = raw_output

    def run(self, args, **kwargs):
        return Result(stdout=self.raw_output.encode("utf-8"), stderr=b"", code=0)


def test_run_batch_delimiters():
    fake_stdout = (
        f"{DELIM_PREFIX}cmd1{DELIM_SUFFIX}\nhello world\n"
        f"{DELIM_PREFIX}cmd2{DELIM_SUFFIX}\n12345\n"
    )
    fake_adb = MockBatchAdb(fake_stdout)
    res = run_batch(fake_adb, {"cmd1": "echo hello world", "cmd2": "echo 12345"})

    assert res["cmd1"] == "hello world"
    assert res["cmd2"] == "12345"
