"""Tests for cache clearing command and cache management helpers."""

import pytest
from llmadb.cache import clear_cache, format_byte_size
from llmadb.commands.cache_cmd import run_clear_cache
from llmadb.errors import E_USAGE, LlmadbError


def test_format_byte_size():
    assert format_byte_size(500) == "500 B"
    assert format_byte_size(1536) == "1.5 KB"
    assert format_byte_size(2097152) == "2.0 MB"


def test_clear_cache_single_device(tmp_path, monkeypatch):
    monkeypatch.setattr("llmadb.cache.get_base_cache_dir", lambda: tmp_path)

    dev_dir = tmp_path / "dev1"
    screens_dir = dev_dir / "screens"
    screens_dir.mkdir(parents=True)

    img1 = screens_dir / "1.png"
    img1.write_bytes(b"x" * 100)
    img2 = screens_dir / "2.png"
    img2.write_bytes(b"y" * 200)

    snap = dev_dir / "snap.json"
    snap.write_text('{"id": 1}', encoding="utf-8")

    # Clear screens only for dev1
    count, total_bytes = clear_cache(serial="dev1", all_data=False)
    assert count == 2
    assert total_bytes == 300
    assert not img1.exists()
    assert not img2.exists()
    assert snap.exists()


def test_clear_cache_all_data(tmp_path, monkeypatch):
    monkeypatch.setattr("llmadb.cache.get_base_cache_dir", lambda: tmp_path)

    dev_dir = tmp_path / "dev1"
    screens_dir = dev_dir / "screens"
    screens_dir.mkdir(parents=True)

    img = screens_dir / "1.png"
    img.write_bytes(b"x" * 100)
    snap = dev_dir / "snap.json"
    snap.write_text('{"id": 1}', encoding="utf-8")
    mark = dev_dir / "mark"
    mark.write_text("test_mark", encoding="utf-8")
    snap_id = dev_dir / "last_snap_id"
    snap_id.write_text("42", encoding="utf-8")

    # Clear all data
    count, total_bytes = clear_cache(serial="dev1", all_data=True)
    # img + snap + mark = 3 files; last_snap_id preserved for monotonic ids
    assert count == 3
    assert not img.exists()
    assert not snap.exists()
    assert not mark.exists()
    assert snap_id.read_text(encoding="utf-8") == "42"


def test_clear_cache_missing_dirs_not_created(tmp_path, monkeypatch):
    base = tmp_path / "absent"
    monkeypatch.setattr("llmadb.cache.get_base_cache_dir", lambda: base)

    assert clear_cache(serial=None) == (0, 0)
    assert clear_cache(serial="ghost") == (0, 0)
    assert not base.exists()


def test_clear_cache_across_all_devices(tmp_path, monkeypatch):
    monkeypatch.setattr("llmadb.cache.get_base_cache_dir", lambda: tmp_path)

    for dev in ("dev1", "dev2"):
        s_dir = tmp_path / dev / "screens"
        s_dir.mkdir(parents=True)
        (s_dir / "pic.png").write_bytes(b"z" * 50)

    count, total_bytes = clear_cache(serial=None, all_data=False)
    assert count == 2
    assert total_bytes == 100


def test_run_clear_cache_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("llmadb.cache.get_base_cache_dir", lambda: tmp_path)

    s_dir = tmp_path / "dev1" / "screens"
    s_dir.mkdir(parents=True)
    (s_dir / "pic.png").write_bytes(b"a" * 1024)

    from llmadb.adb import Adb
    ret = run_clear_cache([], Adb(), serial=None)
    assert ret == 0
    captured = capsys.readouterr()
    assert captured.out == "cleared 1 files (1.0 KB)\n"

    with pytest.raises(LlmadbError) as exc:
        run_clear_cache(["--bad"], Adb(), serial=None)
    assert exc.value.code == E_USAGE
