"""Tests for UI tree reduction, parsing, and formatting."""

import pytest

from llmadb.uitree import parse_ui_tree


def test_turkish_locale_launcher_dump():
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.sec.android.app.launcher" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][720,1280]">
        <node index="0" text="Kişiler" resource-id="com.sec.android.app.launcher:id/home_icon" class="android.widget.TextView" package="com.sec.android.app.launcher" content-desc="Kişiler" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="true" password="false" selected="false" bounds="[36,1100][180,1240]" />
        <node index="1" text="Mesajlar" resource-id="com.sec.android.app.launcher:id/home_msg" class="android.widget.TextView" package="com.sec.android.app.launcher" content-desc="Mesajlar" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="true" password="false" selected="false" bounds="[200,1100][344,1240]" />
        <node index="2" text="Uygulmlr" resource-id="com.sec.android.app.launcher:id/home_allAppsIcon" class="android.widget.TextView" package="com.sec.android.app.launcher" content-desc="Uygulamalar" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[540,1100][684,1240]" />
      </node>
    </hierarchy>""".encode("utf-8")
    snapshot = parse_ui_tree(xml, snapshot_id=1)

    assert snapshot.screen_width == 720
    assert snapshot.screen_height == 1280
    assert snapshot.rotation == 0
    assert snapshot.app_package == "com.sec.android.app.launcher"

    tree_str = snapshot.format_tree()
    # Verify Turkish characters preserved
    assert "Kişiler" in tree_str
    assert "Mesajlar" in tree_str
    assert "Uygulmlr" in tree_str

    # Verify short id stripped package prefix
    assert "id=home_allAppsIcon" in tree_str
    assert "com.sec.android.app.launcher:id/" not in tree_str

    # Verify indexing starts at 1 and increases monotonically
    assert tree_str.startswith("screen 720x1280 app=com.sec.android.app.launcher rot=0 snap=1\n1 ")
    for i, el in enumerate(snapshot.elements, start=1):
        assert el.idx == i


def test_bidi_marker_stripping():
    from llmadb.uitree import clean_label
    raw_with_bidi = "\u2068Alice\U0001f4f1\u2069"
    cleaned = clean_label(raw_with_bidi, "")
    assert "\u2068" not in cleaned
    assert "\u2069" not in cleaned
    assert cleaned == "Alice\U0001f4f1"


def test_android_16_launcher_dump():
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.launcher" bounds="[0,0][1080,2412]">
        <node index="0" text="Pazar" resource-id="com.android.launcher:id/weather_title" class="android.widget.TextView" package="com.android.launcher" clickable="true" enabled="true" bounds="[60,180][420,260]" />
        <node index="1" text="Telefon" resource-id="com.android.launcher:id/dock_phone" class="android.widget.TextView" package="com.android.launcher" clickable="true" enabled="true" bounds="[60,2100][260,2320]" />
        <node index="2" text="Firefox" resource-id="com.android.launcher:id/dock_browser" class="android.widget.TextView" package="com.android.launcher" clickable="true" enabled="true" bounds="[560,2100][760,2320]" />
        <node index="3" text="Kamera" resource-id="com.android.launcher:id/dock_camera" class="android.widget.TextView" package="com.android.launcher" clickable="true" enabled="true" bounds="[820,2100][1020,2320]" />
      </node>
    </hierarchy>""".encode("utf-8")
    snapshot = parse_ui_tree(xml, snapshot_id=1)

    assert snapshot.screen_width == 1080
    assert snapshot.screen_height == 2412
    assert snapshot.rotation == 0
    assert snapshot.app_package == "com.android.launcher"

    tree_str = snapshot.format_tree()
    assert "Pazar" in tree_str
    assert "Telefon" in tree_str
    assert "Firefox" in tree_str
    assert "Kamera" in tree_str


def test_parent_sole_child_merge_and_flags():
    xml = b"""<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node index="0" text="" class="android.widget.FrameLayout" package="com.example.app" bounds="[0,0][1080,2400]">
        <node index="0" text="" resource-id="com.example.app:id/btn_wrap" class="android.widget.FrameLayout" package="com.example.app" clickable="true" enabled="true" bounds="[100,400][980,520]">
          <node index="0" text="Continue" resource-id="" class="android.widget.TextView" package="com.example.app" clickable="false" enabled="true" bounds="[100,400][980,520]" />
        </node>
        <node index="1" text="Wi-Fi" resource-id="com.example.app:id/wifi_switch" class="android.widget.Switch" package="com.example.app" checkable="true" checked="true" clickable="true" enabled="true" bounds="[800,600][1000,700]" />
      </node>
    </hierarchy>"""
    snapshot = parse_ui_tree(xml, snapshot_id=42)
    assert snapshot.screen_width == 1080
    assert snapshot.screen_height == 2400
    tree_text = snapshot.format_tree()
    assert "snap=42" in tree_text
    assert '1 text "Continue" id=btn_wrap @540,460' in tree_text
    assert '2 switch "Wi-Fi" id=wifi_switch [checked] @900,650' in tree_text
    assert "\x00" not in tree_text


def test_empty_webview_warning_emitted():
    xml = b"""<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node index="0" text="" class="android.widget.FrameLayout" package="com.android.chrome" bounds="[0,0][720,1280]">
        <node index="1" text="https://self-signed.badssl.com/" class="android.webkit.WebView" package="com.android.chrome" clickable="false" focusable="true" bounds="[0,156][720,1280]" />
      </node>
    </hierarchy>"""
    snap = parse_ui_tree(xml, snapshot_id=7)
    assert len(snap.warnings) == 1
    assert 'webview "https://self-signed.badssl.com/" [0,156][720,1280]' in snap.warnings[0]
    tree_str = snap.format_tree()
    assert "! webview" in tree_str


def test_parse_window_state_detects_non_focused_overlay():
    from llmadb.uitree import parse_window_state

    dumpsys_sample = """
    InputWindowHandle=Window{d9057b7 u0 StatusBar}, layer=161000, frame=[0,0,720,42], touchableRegion=SkRegion((0,0,720,42)), visible=true
    InputWindowHandle=Window{479bc11 u0 com.sec.android.app.clockpackage.timer.viewmodel.TimerAlarmPopupService}, layer=171005, frame=[0,0,719,245], touchableRegion=SkRegion((0,0,719,245)), visible=true
    InputWindowHandle=Window{33c53fe u0 com.sec.android.app.clockpackage/com.sec.android.app.clockpackage.ClockPackage}, layer=21045, frame=[0,0,720,1280], touchableRegion=SkRegion((0,0,720,1280)), visible=true
    mCurrentFocus=Window{33c53fe u0 com.sec.android.app.clockpackage/com.sec.android.app.clockpackage.ClockPackage}
    """
    pkg, w, h, warnings = parse_window_state(dumpsys_sample)
    assert pkg == "com.sec.android.app.clockpackage"
    assert w == 720
    assert h == 1280
    assert len(warnings) == 1
    assert 'overlay window="TimerAlarmPopupService" bounds=[0,0][719,245] @359,122' in warnings[0]


def test_parse_window_state_android_16_17_input_dispatcher():
    from llmadb.uitree import parse_window_state

    dumpsys_a16 = """
    init=1080x2412 480dpi mMinSizeOfResizeableTaskDp=220 cur=1080x2412 app=1080x2412 rng=1080x1080-2412x2412
    mCurrentFocus=Window{5908d28 u0 com.google.android.apps.nexuslauncher/com.google.android.apps.nexuslauncher.NexusLauncherActivity}
      0: name=c7ef1c9 ScreenDecorOverlayBottom, id=75, displayId=0, inputConfig=NOT_FOCUSABLE | NOT_TOUCHABLE | TRUSTED_OVERLAY | SLIPPERY, alpha=1, frame=[0,2235][1080,2412], globalScale=1, applicationInfo.name=, applicationInfo.token=<null>, touchableRegion=<empty>, ownerPid=6161
      2: name=[Gesture Monitor] swipe-up, id=99, displayId=0, inputConfig=NOT_FOCUSABLE | TRUSTED_OVERLAY | SPY, alpha=1, frame=[0,0][0,0], globalScale=1, applicationInfo.name=[Gesture Monitor] swipe-up, applicationInfo.token=<null>, touchableRegion=[-10800,-24120][10800,24120], ownerPid=6602
      6: name=f7be3e3 NavigationBar_displayId_0, id=93, displayId=0, inputConfig=NOT_FOCUSABLE | TRUSTED_OVERLAY, alpha=1, frame=[0,2280][1080,2412], globalScale=1, applicationInfo.name=, applicationInfo.token=<null>, touchableRegion=<empty>, ownerPid=6161
      7: name=3acb33b StatusBar, id=97, displayId=0, inputConfig=NOT_FOCUSABLE | TRUSTED_OVERLAY, alpha=1, frame=[0,0][1080,120], globalScale=1, applicationInfo.name=, applicationInfo.token=<null>, touchableRegion=[0,0][1080,120], ownerPid=6161
      8: name=58cead3 NotificationShade, id=98, displayId=0, inputConfig=NOT_FOCUSABLE | TRUSTED_OVERLAY, alpha=1, frame=[0,0][1080,2412], globalScale=1, applicationInfo.name=, applicationInfo.token=<null>, touchableRegion=[42,96][1038,348], ownerPid=6161
      16: name=5908d28 com.google.android.apps.nexuslauncher/com.google.android.apps.nexuslauncher.NexusLauncherActivity, id=105, displayId=0, inputConfig=0x0, alpha=1, frame=[0,0][1080,2412], globalScale=1, applicationInfo.name=, applicationInfo.token=0x123, touchableRegion=[0,0][1080,2412], ownerPid=6602
    """
    pkg, w, h, warnings = parse_window_state(dumpsys_a16)
    assert pkg == "com.google.android.apps.nexuslauncher"
    assert w == 1080
    assert h == 2412
    assert len(warnings) == 1
    assert 'overlay window="NotificationShade" bounds=[42,96][1038,348] @540,222' in warnings[0]


def test_dump_hierarchy_bytes_fails_fast_on_non_idle():
    from llmadb.adb import Result as AdbResult
    from llmadb.commands.ui import dump_hierarchy_bytes

    calls = []

    class BusyAdb:
        def run(self, args, **kwargs):
            calls.append(args)
            return AdbResult(stdout=b"ERROR: could not get idle state.\n", stderr=b"", code=0)

    out = dump_hierarchy_bytes(BusyAdb(), serial="dev1", retries=3)
    assert b"could not get idle state" in out
    # Must fail fast on first call without sdcard fallback or retries
    assert len(calls) == 1


def test_annotate_snapshot_with_grid_and_overlay():
    from PIL import Image
    from llmadb.annotate import annotate_snapshot
    from llmadb.uitree import Element, Snapshot

    img = Image.new("RGB", (540, 960), (30, 30, 30))
    snap = Snapshot(
        id=9,
        screen_width=720,
        screen_height=1280,
        app_package="com.sec.android.app.clockpackage",
        rotation=0,
        elements=[
            Element(
                idx=1,
                node_type="button",
                label="Start",
                resource_id="com.sec.android.app.clockpackage:id/start",
                short_id="start",
                bounds=(200, 1000, 520, 1100),
                center=(360, 1050),
            )
        ],
        warnings=['! overlay window="TimerAlarmPopupService" bounds=[0,0][719,245] @359,122'],
    )
    out = annotate_snapshot(img, snap, scale_x=0.75, scale_y=0.75, grid_interval=100)
    assert out.size == (540, 960)
