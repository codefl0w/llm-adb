"""Tests for hardware command parsers."""

import json
from llmadb.adb import Result as AdbResult
from llmadb.commands.hardware import (
    format_hardware_text,
    parse_df,
    parse_getprop,
    parse_meminfo,
    parse_root,
    parse_wm_density,
    parse_wm_size,
    run_hardware,
)
from llmadb.errors import E_USAGE, LlmadbError
import pytest


def test_parse_getprop():
    sample = """
[ro.product.manufacturer]: [Google]
[ro.product.model]: [Pixel 7]
[ro.build.version.release]: [13]
"""
    props = parse_getprop(sample)
    assert props["ro.product.manufacturer"] == "Google"
    assert props["ro.product.model"] == "Pixel 7"
    assert props["ro.build.version.release"] == "13"


def test_parse_wm_size():
    sample = """
Physical size: 1080x2400
Override size: 720x1600
"""
    size = parse_wm_size(sample)
    assert size["physical"] == "1080x2400"
    assert size["effective"] == "720x1600"


def test_parse_wm_density():
    sample = "Physical density: 420\nOverride density: 360"
    assert parse_wm_density(sample) == 360

    sample2 = "Physical density: 420"
    assert parse_wm_density(sample2) == 420


def test_parse_meminfo():
    sample = """
MemTotal:        7944044 kB
MemAvailable:    4123456 kB
"""
    mem = parse_meminfo(sample)
    assert mem["total_mb"] == round(7944044 / 1024)
    assert mem["available_mb"] == round(4123456 / 1024)


def test_parse_df():
    sample = """
Filesystem       1K-blocks      Used Available Use% Mounted on
/dev/block/dm-50 112345678  23456789  88888888  21% /data
"""
    storage = parse_df(sample)
    assert storage["data_size_gb"] > 0
    assert storage["data_used_gb"] > 0


def test_parse_root():
    assert parse_root("uid=0(root) gid=0(root)") == "yes"
    assert parse_root("/system/bin/sh: su: not found") == "no"
    assert parse_root("unknown response") == "unknown"


def test_format_hardware_text():
    info = {
        "manufacturer": "Google",
        "model": "Pixel 7",
        "android_version": "13",
        "sdk": 33,
        "security_patch": "2023-05-05",
        "fingerprint": "google/panther/panther:13/TQ2A.230505.002/9890123:user/release-keys",
        "abi": ["arm64-v8a", "armeabi-v7a"],
        "hardware": "panther",
        "platform": "pantah",
        "resolution": {
            "physical": "1080x2400",
            "effective": "1080x2400",
            "dpi": 420,
        },
        "memory": {"total_mb": 7758, "available_mb": 4027},
        "storage": {"data_size_gb": 107.1, "data_used_gb": 22.4},
        "selinux": "Enforcing",
        "root": "no",
    }
    text = format_hardware_text(info)
    assert "manufacturer: Google" in text
    assert "model: Pixel 7" in text
    assert "android_version: 13" in text
    assert "sdk: 33" in text
    assert "security_patch: 2023-05-05" in text
    assert "abi: arm64-v8a, armeabi-v7a" in text
    assert "hardware: panther" in text
    assert "platform: pantah" in text
    assert "resolution: 1080x2400 (420 dpi)" in text
    assert "memory: 4027 MB available / 7758 MB total" in text
    assert "storage: 22.4 GB used / 107.1 GB total" in text
    assert "selinux: Enforcing" in text
    assert "root: no" in text


def test_format_hardware_text_effective_resolution():
    info = {
        "manufacturer": "OnePlus",
        "model": "CPH2449",
        "android_version": "14",
        "sdk": 34,
        "security_patch": "",
        "fingerprint": "",
        "abi": [],
        "hardware": "",
        "platform": "",
        "resolution": {
            "physical": "1440x3216",
            "effective": "1080x2412",
            "dpi": 480,
        },
        "memory": {"total_mb": 0, "available_mb": 0},
        "storage": {"data_size_gb": 0.0, "data_used_gb": 0.0},
        "selinux": "Permissive",
        "root": "yes",
    }
    text = format_hardware_text(info)
    assert "resolution: 1080x2412 (physical: 1440x3216, 480 dpi)" in text
    assert "memory: unknown" in text
    assert "storage: unknown" in text
    assert "abi: unknown" in text
    assert "selinux: Permissive" in text
    assert "root: yes" in text


class MockHardwareAdb:
    def run(self, args, **kwargs):
        out = (
            "___LLMADB_BATCH_getprop___\n"
            "[ro.product.manufacturer]: [Google]\n"
            "[ro.product.model]: [Pixel 7]\n"
            "[ro.build.version.release]: [13]\n"
            "[ro.build.version.sdk]: [33]\n"
            "[ro.product.cpu.abilist]: [arm64-v8a,armeabi-v7a]\n"
            "___LLMADB_BATCH_wm_size___\n"
            "Physical size: 1080x2400\n"
            "___LLMADB_BATCH_wm_density___\n"
            "Physical density: 420\n"
            "___LLMADB_BATCH_meminfo___\n"
            "MemTotal:        7944044 kB\n"
            "MemAvailable:    4123456 kB\n"
            "___LLMADB_BATCH_df___\n"
            "Filesystem 1K-blocks Used Available Use% Mounted\n"
            "/dev/block/dm-50 112345678 23456789 88888888 21% /data\n"
            "___LLMADB_BATCH_getenforce___\n"
            "Enforcing\n"
            "___LLMADB_BATCH_su___\n"
            "/system/bin/sh: su: not found\n"
        )
        return AdbResult(stdout=out.encode("utf-8"), stderr=b"", code=0)


def test_run_hardware_plaintext(monkeypatch, capsys):
    monkeypatch.setattr("llmadb.commands.hardware.resolve_device", lambda adb, explicit_serial=None: "emu1")

    ret = run_hardware([], MockHardwareAdb())
    assert ret == 0
    captured = capsys.readouterr()
    assert "manufacturer: Google" in captured.out
    assert "model: Pixel 7" in captured.out
    assert "resolution: 1080x2400 (420 dpi)" in captured.out
    assert "selinux: Enforcing" in captured.out
    assert "root: no" in captured.out
    # Verify it is not JSON
    assert not captured.out.strip().startswith("{")


def test_run_hardware_json(monkeypatch, capsys):
    monkeypatch.setattr("llmadb.commands.hardware.resolve_device", lambda adb, explicit_serial=None: "emu1")

    ret = run_hardware(["--json"], MockHardwareAdb())
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["manufacturer"] == "Google"
    assert data["model"] == "Pixel 7"
    assert data["resolution"]["dpi"] == 420
    assert data["selinux"] == "Enforcing"
    assert data["root"] == "no"


def test_run_hardware_max_lines(monkeypatch, capsys):
    monkeypatch.setattr("llmadb.commands.hardware.resolve_device", lambda adb, explicit_serial=None: "emu1")

    ret = run_hardware([], MockHardwareAdb(), max_lines=3)
    assert ret == 0
    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert len(lines) == 4  # 3 lines + 1 truncation line
    assert "[truncated:" in lines[-1]


def test_run_hardware_invalid_option():
    with pytest.raises(LlmadbError) as exc:
        run_hardware(["--invalid"], MockHardwareAdb())
    assert exc.value.code == E_USAGE

