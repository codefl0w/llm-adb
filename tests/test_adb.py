"""Tests for adb runner and output cleaning."""

from llmadb.adb import Adb, clean_adb_output


def test_clean_adb_output():
    raw = (
        b"* daemon not running; starting now at tcp:5037\n"
        b"* daemon started successfully\n"
        b"real output line 1\n"
        b"real output line 2\n"
    )
    cleaned = clean_adb_output(raw)
    assert cleaned == b"real output line 1\nreal output line 2\n"


def test_build_cmd():
    adb = Adb(adb_path="adb")
    assert adb.build_cmd(["devices"]) == ["adb", "devices"]
    assert adb.build_cmd(["devices"], serial="emu1") == ["adb", "-s", "emu1", "devices"]
