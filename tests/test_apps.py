"""Tests for 'list apps' command: package parsing, path classification, and formatting."""

import pytest

from llmadb.adb import Result as AdbResult
from llmadb.commands.apps import (
    classify_package,
    format_apps_output,
    parse_package_line,
    run_list_apps,
)
from llmadb.errors import E_USAGE, LlmadbError
from llmadb.shellbatch import DELIM_PREFIX, DELIM_SUFFIX


def test_parse_package_line_with_equals_in_path():
    # Base64-like Android 11+ encrypted dir paths contain '='
    line = "package:/data/app/~~abc123==/com.example.app-xyz==/base.apk=com.example.app"
    parsed = parse_package_line(line)
    assert parsed == (
        "/data/app/~~abc123==/com.example.app-xyz==/base.apk",
        "com.example.app",
    )


def test_classify_package_categories():
    # Regular user app
    assert classify_package("/data/app/com.user.app-1/base.apk", in_system_set=False, in_user_set=True) == "user"

    # Updated system app (lives in /data/app but belongs to -s system set)
    assert classify_package("/data/app/com.android.chrome-2/base.apk", in_system_set=True, in_user_set=False) == "system*"

    # System & system_ext
    assert classify_package("/system/priv-app/Settings/Settings.apk", in_system_set=True) == "system"
    assert classify_package("/system_ext/app/CarrierConfig/CarrierConfig.apk", in_system_set=True) == "system"

    # Vendor & odm
    assert classify_package("/vendor/overlay/DisplayCutout.apk", in_system_set=True) == "vendor"
    assert classify_package("/odm/app/OdmService/OdmService.apk", in_system_set=True) == "vendor"

    # Product
    assert classify_package("/product/app/LatinIME/LatinIME.apk", in_system_set=True) == "product"


def test_format_apps_output_scopes_and_grep():
    classified = {
        "com.mixplorer": "user",
        "org.mozilla.firefox": "user",
        "com.android.settings": "system",
        "com.android.chrome": "system*",
        "com.qualcomm.qti": "vendor",
        "com.google.android.LatinIME": "product",
    }

    # Default user scope
    assert format_apps_output(classified, scope="user") == "com.mixplorer\norg.mozilla.firefox"

    # System scope includes system and system*
    assert format_apps_output(classified, scope="system") == "com.android.chrome\tsystem*\ncom.android.settings"

    # All scope uses section headers
    all_out = format_apps_output(classified, scope="all")
    assert "[user]\ncom.mixplorer\norg.mozilla.firefox" in all_out
    assert "[system]\ncom.android.chrome\tsystem*\ncom.android.settings" in all_out
    assert "[vendor]\ncom.qualcomm.qti" in all_out
    assert "[product]\ncom.google.android.LatinIME" in all_out

    # Grep filtering
    grep_out = format_apps_output(classified, scope="all", grep_pattern="android")
    assert "com.android.chrome\tsystem*" in grep_out
    assert "com.mixplorer" not in grep_out


def test_run_list_apps_command(monkeypatch, capsys):
    monkeypatch.setattr("llmadb.commands.apps.resolve_device", lambda adb, explicit_serial=None: "emu1")

    batch_out = (
        f"{DELIM_PREFIX}all_f{DELIM_SUFFIX}\n"
        "package:/data/app/~~xyz==/com.foo.bar-1==/base.apk=com.foo.bar\n"
        "package:/system/app/SysApp/SysApp.apk=com.android.sys\n"
        f"{DELIM_PREFIX}user_3{DELIM_SUFFIX}\n"
        "package:com.foo.bar\n"
        f"{DELIM_PREFIX}sys_s{DELIM_SUFFIX}\n"
        "package:com.android.sys\n"
    )

    class FakeAdb:
        def run(self, args, **kwargs):
            return AdbResult(stdout=batch_out.encode("utf-8"), stderr=b"", code=0)

    ret = run_list_apps(["apps", "user"], FakeAdb())
    assert ret == 0
    assert capsys.readouterr().out == "com.foo.bar\n"


def test_run_list_apps_conflicting_flags():
    class DummyAdb:
        pass

    with pytest.raises(LlmadbError) as exc:
        run_list_apps(["apps", "--disabled", "--enabled"], DummyAdb())
    assert exc.value.code == E_USAGE
