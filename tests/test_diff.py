"""Tests for UI differential formatting."""

from llmadb.uitree import Element, Snapshot, format_snapshot_diff


def test_format_snapshot_diff():
    el1 = Element(idx=1, node_type="button", label="Submit", resource_id="", short_id="", bounds=(0, 0, 10, 10), center=(5, 5))
    el2 = Element(idx=2, node_type="text", label="Old status", resource_id="", short_id="", bounds=(0, 10, 10, 20), center=(5, 15))
    el3 = Element(idx=2, node_type="text", label="Success!", resource_id="", short_id="", bounds=(0, 10, 10, 20), center=(5, 15))

    snap_old = Snapshot(id=1, screen_width=100, screen_height=200, app_package="test", rotation=0, elements=[el1, el2])
    snap_new = Snapshot(id=2, screen_width=100, screen_height=200, app_package="test", rotation=0, elements=[el1, el3])

    diff_str = format_snapshot_diff(snap_old, snap_new)

    assert "- 2 text \"Old status\" @5,15" in diff_str
    assert "+ 2 text \"Success!\" @5,15" in diff_str
    # Unchanged element 1 should not appear in diff
    assert "Submit" not in diff_str
