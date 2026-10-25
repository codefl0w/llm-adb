"""Tests for current foreground app and state parsers."""

from llmadb.commands.current import parse_component, parse_keyboard, parse_rotation


def test_parse_component_focus():
    focus_text = "mCurrentFocus=Window{da60713d0 u0 com.android.chrome/com.google.android.apps.chrome.Main}"
    res = parse_component(focus_text, "")
    assert res == "com.android.chrome/com.google.android.apps.chrome.Main"


def test_parse_component_resumed_fallback():
    focus_text = "mCurrentFocus=null"
    resumed_text = "mResumedActivity: ActivityRecord{abc u0 com.example.app/.MainActivity t123}"
    res = parse_component(focus_text, resumed_text)
    assert res == "com.example.app/.MainActivity"


def test_parse_keyboard():
    assert parse_keyboard("mInputShown=true") == "visible"
    assert parse_keyboard("isInputViewShown=true") == "visible"
    assert parse_keyboard("mInputShown=false") == "hidden"


def test_parse_rotation():
    assert parse_rotation("1", "") == 1
    assert parse_rotation("", "mCurrentRotation=3") == 3
    assert parse_rotation("", "mRotation=ROTATION_90") == 1
    assert parse_rotation("", "mRotation=ROTATION_270") == 3
    assert parse_rotation("", "") == 0
