"""Tests for 'info' command: dumpsys package parsing and permission shortening."""

import pytest

from llmadb.commands.info import (
    extract_launcher_from_dumpsys,
    format_package_info,
    parse_package_info,
    shorten_permission,
)
from llmadb.errors import E_NOT_FOUND, LlmadbError

SAMPLE_DUMPSYS = """
Activity Resolver Table:
  Non-Data Actions:
      android.intent.action.MAIN:
        42b1c3d com.example.demo/.MainActivity filter 43a9f12
          Action: "android.intent.action.MAIN"
          Category: "android.intent.category.LAUNCHER"

Packages:
  Package [com.example.demo] (7b8a9c0):
    userId=10142
    versionCode=42 minSdk=24 targetSdk=34
    versionName=2.4.0-beta
    pkgFlags=[ DEBUGGABLE HAS_CODE ALLOW_CLEAR_USER_DATA ]
    installerPackageName=com.android.vending
    firstInstallTime=2026-01-10 14:22:00
    lastUpdateTime=2026-10-18 01:15:30
    User 0: ceDataInode=12345 installed=true hidden=false suspended=false stopped=false notLaunched=false enabled=0
    runtime permissions:
      android.permission.CAMERA: granted=true, flags=[ USER_SENSITIVE_WHEN_GRANTED ]
      android.permission.RECORD_AUDIO: granted=false, flags=[ USER_SET ]
      com.custom.perm.ACCESS: granted=true
"""


def test_shorten_permission():
    assert shorten_permission("android.permission.CAMERA") == "CAMERA"
    assert shorten_permission("com.custom.perm.ACCESS") == "com.custom.perm.ACCESS"


def test_extract_launcher_from_dumpsys():
    comp = extract_launcher_from_dumpsys(SAMPLE_DUMPSYS, "com.example.demo")
    assert comp == "com.example.demo/.MainActivity"


def test_parse_package_info_complete():
    info = parse_package_info(
        pkg="com.example.demo",
        dumpsys_text=SAMPLE_DUMPSYS,
        resolve_text="",
        pid_text="4812\n",
    )
    assert info["package"] == "com.example.demo"
    assert info["version_name"] == "2.4.0-beta"
    assert info["version_code"] == "42"
    assert info["min_sdk"] == "24"
    assert info["target_sdk"] == "34"
    assert info["debuggable"] is True
    assert info["enabled"] == "default"
    assert info["installer"] == "com.android.vending"
    assert info["first_install"] == "2026-01-10 14:22:00"
    assert info["last_update"] == "2026-10-18 01:15:30"
    assert info["launcher"] == "com.example.demo/.MainActivity"
    assert info["running"] == "pid=4812"
    assert info["granted_permissions"] == ["CAMERA", "com.custom.perm.ACCESS"]
    assert info["denied_permissions"] == ["RECORD_AUDIO"]

    formatted = format_package_info(info)
    assert "version: 2.4.0-beta (42)" in formatted
    assert "sdk: min=24 target=34" in formatted
    assert "running=pid=4812 debuggable=yes" in formatted
    assert "granted: CAMERA, com.custom.perm.ACCESS" in formatted
    assert "denied: RECORD_AUDIO" in formatted


def test_parse_package_info_not_found():
    with pytest.raises(LlmadbError) as exc:
        parse_package_info("com.missing.app", "Unable to find package: com.missing.app")
    assert exc.value.code == E_NOT_FOUND
    assert exc.value.exit_code == 6
