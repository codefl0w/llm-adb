"""Tests for snapshot and mark caching."""

import json
from pathlib import Path

from llmadb.cache import (
    compute_content_hash,
    get_device_cache_dir,
    get_next_snapshot_id,
    load_snapshot,
    save_snapshot,
)
from llmadb.uitree import Element, Snapshot


def test_cache_snapshot_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    elements = [
        Element(
            idx=1,
            node_type="button",
            label="OK",
            resource_id="com.test:id/ok",
            short_id="ok",
            bounds=(0, 0, 100, 50),
            center=(50, 25),
        )
    ]
    snap = Snapshot(
        id=12,
        screen_width=720,
        screen_height=1280,
        app_package="com.test",
        rotation=0,
        elements=elements,
        raw_xml=b"<hierarchy></hierarchy>",
    )

    save_snapshot("test_serial", snap)
    loaded = load_snapshot("test_serial")

    assert loaded is not None
    assert loaded.id == 12
    assert loaded.screen_width == 720
    assert loaded.elements[0].label == "OK"
    assert loaded.elements[0].center == (50, 25)


def test_next_snapshot_id(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    id1 = get_next_snapshot_id("dev1")
    id2 = get_next_snapshot_id("dev1")
    assert id2 == id1 + 1


def test_screen_output_routing(tmp_path, monkeypatch, capsys):
    import io
    from PIL import Image
    from llmadb.adb import Result as AdbResult
    from llmadb.commands.screen import run_screen

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("llmadb.commands.screen.resolve_device", lambda adb, explicit_serial=None: "emu1")

    buf = io.BytesIO()
    Image.new("RGB", (200, 400), color=(20, 40, 60)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    class MockScreenAdb:
        def run(self, args, **kwargs):
            return AdbResult(stdout=png_bytes, stderr=b"", code=0)

    # 1. Explicit -o directory
    out_dir1 = tmp_path / "out_flag"
    assert run_screen(["--no-ui", "-o", str(out_dir1)], MockScreenAdb()) == 0
    assert (out_dir1 / "0.png").exists()
    assert f"path={out_dir1 / '0.png'}" in capsys.readouterr().out

    # 2. LLMADB_SCREENSHOT_OUTDIR env var
    out_dir2 = tmp_path / "out_env"
    monkeypatch.setenv("LLMADB_SCREENSHOT_OUTDIR", str(out_dir2))
    assert run_screen(["--no-ui"], MockScreenAdb()) == 0
    assert (out_dir2 / "0.png").exists()
    assert f"path={out_dir2 / '0.png'}" in capsys.readouterr().out

    # 3. Default cache fallback when neither is set
    monkeypatch.delenv("LLMADB_SCREENSHOT_OUTDIR")
    assert run_screen(["--no-ui"], MockScreenAdb()) == 0
    default_file = tmp_path / "cache" / "llmadb" / "emu1" / "screens" / "0.png"
    assert default_file.exists()
    assert f"path={default_file}" in capsys.readouterr().out

