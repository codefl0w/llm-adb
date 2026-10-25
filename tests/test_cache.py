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
