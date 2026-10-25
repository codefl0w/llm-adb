"""UI Automator XML reduction, filtering, indexing, and formatting."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

INTERACTIVE_CLASSES = {
    "Button",
    "ImageButton",
    "EditText",
    "Switch",
    "CheckBox",
    "RadioButton",
    "ToggleButton",
    "SeekBar",
    "Spinner",
    "TabWidget",
    "ProgressBar",
}

INTERACTIVE_TYPES = {"button", "input", "switch", "check", "radio"}

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass
class Element:
    idx: int
    node_type: str
    label: str
    resource_id: str
    short_id: str
    bounds: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    center: Tuple[int, int]            # (cx, cy)
    flags: List[str] = field(default_factory=list)
    raw_class: str = ""
    package: str = ""

    def format_row(self, full_bounds: bool = False) -> str:
        loc_str = (
            f"[{self.bounds[0]},{self.bounds[1]}][{self.bounds[2]},{self.bounds[3]}]"
            if full_bounds
            else f"@{self.center[0]},{self.center[1]}"
        )
        id_str = f" id={self.short_id}" if self.short_id else ""
        flags_str = f" [{' '.join(self.flags)}]" if self.flags else ""
        escaped_label = self.label.replace('"', '\\"').replace("\n", " ").replace("\r", "")
        return f'{self.idx} {self.node_type} "{escaped_label}"{id_str}{flags_str} {loc_str}'


@dataclass
class Snapshot:
    id: int
    screen_width: int
    screen_height: int
    app_package: str
    rotation: int
    elements: List[Element]
    raw_xml: bytes = b""
    warnings: List[str] = field(default_factory=list)

    def format_header(self) -> str:
        return f"screen {self.screen_width}x{self.screen_height} app={self.app_package} rot={self.rotation} snap={self.id}"

    def format_tree(self, full_bounds: bool = False) -> str:
        lines = [self.format_header()]
        for w in self.warnings:
            lines.append(w if w.startswith("! ") else f"! {w}")
        for el in self.elements:
            lines.append(el.format_row(full_bounds=full_bounds))
        return "\n".join(lines)


def format_snapshot_diff(prev: Optional[Snapshot], current: Snapshot) -> str:
    """Format differential view of UI changes between two snapshots."""
    header = current.format_header()
    if prev is None:
        return current.format_tree()

    prev_map = {(el.bounds, el.label): el for el in prev.elements}
    curr_map = {(el.bounds, el.label): el for el in current.elements}

    removed = [el for key, el in prev_map.items() if key not in curr_map]
    added = [el for key, el in curr_map.items() if key not in prev_map]

    lines = [header]
    for w in current.warnings:
        lines.append(w if w.startswith("! ") else f"! {w}")

    if not removed and not added:
        lines.append("  (no changes)")
        return "\n".join(lines)

    for el in removed:
        lines.append(f"- {el.format_row()}")
    for el in added:
        lines.append(f"+ {el.format_row()}")

    return "\n".join(lines)


HANDLE_RE = re.compile(
    r"InputWindowHandle=Window\{[^}]*\s+([^\s}]+)\}.*?"
    r"layer=(\d+),\s*frame=\[(-?\d+),(-?\d+),(-?\d+),(-?\d+)\]"
    r"(?:,\s*touchableRegion=SkRegion\(\((-?\d+),(-?\d+),(-?\d+),(-?\d+)\)\))?"
    r".*?visible=(true|false)"
)
INPUT_WIN_RE = re.compile(
    r"^\s*(\d+):\s*name=(?:([0-9a-f]+)\s+)?([^,]+),\s*id=\d+,\s*displayId=(\d+),\s*"
    r"inputConfig=([^,]+),.*?frame=\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\].*?"
    r"touchableRegion=(.+?)(?:,\s*[a-zA-Z0-9_.]+=|$)"
)
RECT_PAIR_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
FOCUS_WIN_RE = re.compile(r"mCurrentFocus=Window\{([0-9a-f]+)?\s*[^\s}]*\s+([^\s}]+)\}")
CUR_SIZE_RE = re.compile(r"(?:cur|init)=(\d+)x(\d+)")

IGNORED_SYSTEM_WINDOWS = {
    "NavigationBar",
    "NavigationBar_displayId_0",
    "InputMethod",
    "DockedStackDivider",
    "KeyguardScrim",
    "ContainerKeyguardScrim",
    "Bouncer",
    "AssistOverlay",
    "EdgePanels",
    "CocktailBar",
    "ImageWallpaper",
    "Wallpaper",
    "ScreenDecorOverlay",
    "ScreenDecorOverlayBottom",
    "OplusOSEdgeFloatBar",
    "ColorOSEdgePanel",
    "ColorSideGestureLeft_displayId_0",
    "ColorSideGestureRight_displayId_0",
}


def parse_window_state(dumpsys_text: str) -> Tuple[str, int, int, List[str]]:
    """Parse dumpsys window/input output for focused package, dimensions, and active overlay warnings."""
    focus_hash = ""
    focus_win = ""
    focus_pkg = ""
    screen_w = 0
    screen_h = 0

    for line in dumpsys_text.splitlines():
        if screen_w == 0:
            ms = CUR_SIZE_RE.search(line)
            if ms:
                screen_w, screen_h = int(ms.group(1)), int(ms.group(2))
        if not focus_win and "mCurrentFocus=" in line:
            m = FOCUS_WIN_RE.search(line)
            if m:
                focus_hash = m.group(1) or ""
                focus_win = m.group(2)
                focus_pkg = focus_win.split("/", 1)[0]

    windows = []
    focus_layer = 0
    input_windows = []
    focus_input_idx: Optional[int] = None
    input_table_done = False

    for line in dumpsys_text.splitlines():
        if "InputWindowHandle=" in line:
            m = HANDLE_RE.search(line)
            if not m:
                continue
            win_name = m.group(1)
            layer = int(m.group(2))
            fx1, fy1, fx2, fy2 = int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6))
            if m.group(7) is not None:
                tx1, ty1, tx2, ty2 = int(m.group(7)), int(m.group(8)), int(m.group(9)), int(m.group(10))
                if tx2 > tx1 and ty2 > ty1:
                    x1, y1, x2, y2 = tx1, ty1, tx2, ty2
                else:
                    x1, y1, x2, y2 = fx1, fy1, fx2, fy2
            else:
                x1, y1, x2, y2 = fx1, fy1, fx2, fy2
            visible = m.group(11) == "true"

            if win_name == focus_win:
                focus_layer = layer
                if fx2 > fx1 and fy2 > fy1:
                    screen_w = max(screen_w, fx2)
                    screen_h = max(screen_h, fy2)
            elif visible and fx2 > fx1 and fy2 > fy1 and "/" in win_name:
                screen_w = max(screen_w, fx2)
                screen_h = max(screen_h, fy2)

            windows.append((win_name, layer, (x1, y1, x2, y2), visible))
            continue

        mi = INPUT_WIN_RE.match(line)
        if mi and not input_table_done:
            idx = int(mi.group(1))
            if idx == 0 and input_windows:
                input_table_done = True
                continue
            win_hash = mi.group(2) or ""
            win_name = mi.group(3).strip()
            disp_id = int(mi.group(4))
            if disp_id != 0:
                continue
            input_cfg = mi.group(5)
            fx1, fy1, fx2, fy2 = int(mi.group(6)), int(mi.group(7)), int(mi.group(8)), int(mi.group(9))
            t_region = mi.group(10)

            is_focus = (
                (focus_win and win_name == focus_win)
                or (focus_hash and win_hash == focus_hash)
            )
            if is_focus and focus_input_idx is None:
                focus_input_idx = idx
                if fx2 > fx1 and fy2 > fy1:
                    screen_w = max(screen_w, fx2)
                    screen_h = max(screen_h, fy2)

            input_windows.append((idx, win_name, input_cfg, (fx1, fy1, fx2, fy2), t_region))

    overlay_warnings: List[str] = []
    for win_name, layer, (x1, y1, x2, y2), visible in windows:
        if not visible:
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        if win_name == focus_win:
            continue

        short_name = win_name.split("/")[-1].rsplit(".", 1)[-1]
        if short_name in IGNORED_SYSTEM_WINDOWS or win_name in IGNORED_SYSTEM_WINDOWS:
            continue
        if short_name == "StatusBar" and (y2 - y1) <= 80:
            continue

        is_overlay = (focus_layer > 0 and layer > focus_layer) or any(
            k in short_name for k in ("Popup", "Toast", "HeadsUp", "Overlay", "Alert")
        )
        if is_overlay:
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            overlay_warnings.append(
                f'! overlay window="{short_name}" bounds=[{x1},{y1}][{x2},{y2}] @{cx},{cy} '
                f"(not in UI tree; use 'llmadb screen' to see buttons)"
            )

    if not overlay_warnings and input_windows:
        for idx, win_name, input_cfg, (fx1, fy1, fx2, fy2), t_region in input_windows:
            if focus_input_idx is not None and idx >= focus_input_idx:
                continue
            if any(flag in input_cfg for flag in ("NOT_VISIBLE", "NOT_TOUCHABLE", "NO_INPUT_CHANNEL", "SPY")):
                continue
            if t_region == "<empty>" or win_name.startswith("[Gesture Monitor]") or win_name.startswith("ActivityRecordInputSink"):
                continue

            rect_matches = RECT_PAIR_RE.findall(t_region)
            if rect_matches:
                xs1 = [int(r[0]) for r in rect_matches]
                ys1 = [int(r[1]) for r in rect_matches]
                xs2 = [int(r[2]) for r in rect_matches]
                ys2 = [int(r[3]) for r in rect_matches]
                x1, y1, x2, y2 = min(xs1), min(ys1), max(xs2), max(ys2)
            else:
                x1, y1, x2, y2 = fx1, fy1, fx2, fy2

            if x2 <= x1 or y2 <= y1:
                continue

            short_name = win_name.split("/")[-1].rsplit(".", 1)[-1]
            if short_name in IGNORED_SYSTEM_WINDOWS or win_name in IGNORED_SYSTEM_WINDOWS:
                continue
            if short_name == "StatusBar" and (y2 - y1) <= 135:
                continue
            if short_name == "NotificationShade" and focus_pkg == "com.android.systemui":
                continue

            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            overlay_warnings.append(
                f'! overlay window="{short_name}" bounds=[{x1},{y1}][{x2},{y2}] @{cx},{cy} '
                f"(not in UI tree; use 'llmadb screen' to see buttons)"
            )

    return focus_pkg, screen_w, screen_h, overlay_warnings



def parse_bounds(bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse bounds string '[x1,y1][x2,y2]' into tuple (x1, y1, x2, y2)."""
    m = BOUNDS_RE.match(bounds_str)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def map_class_to_type(class_name: str) -> str:
    """Map Android class name to compact type string."""
    name = class_name.rsplit(".", 1)[-1]
    if name == "TextView":
        return "text"
    if name in ("Button", "ImageButton"):
        return "button"
    if name == "EditText":
        return "input"
    if name == "CheckBox":
        return "check"
    if name in ("Switch", "ToggleButton"):
        return "switch"
    if name == "RadioButton":
        return "radio"
    if name == "ImageView":
        return "image"
    if name == "ProgressBar":
        return "progress"
    if name in ("ScrollView", "RecyclerView", "ListView", "Workspace", "ViewPager"):
        return "scroll"
    return "view"


def extract_first_descendant_text(node: ET.Element) -> str:
    """Find text of first descendant with text or content-desc."""
    for child in node.iter("node"):
        if child is node:
            continue
        text = child.attrib.get("text", "").strip()
        if text:
            return text
        desc = child.attrib.get("content-desc", "").strip()
        if desc:
            return desc
    return ""


BIDI_CHARS = dict.fromkeys(
    map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200b\ufeff"), None
)


def clean_label(text: str, content_desc: str, full: bool = False) -> str:
    """Pick label from text or content-desc, strip BiDi markers, and truncate if needed."""
    raw = text.strip() if text.strip() else content_desc.strip()
    raw = raw.translate(BIDI_CHARS)
    raw = " ".join(raw.split())
    if not full and len(raw) > 120:
        return raw[:117] + "..."
    return raw



class RawNode:
    def __init__(self, element: ET.Element):
        self.attrib = element.attrib
        self.element = element
        self.children: List["RawNode"] = []
        self.bounds = parse_bounds(element.attrib.get("bounds", ""))
        self.text = element.attrib.get("text", "")
        self.desc = element.attrib.get("content-desc", "")
        self.class_name = element.attrib.get("class", "")
        self.pkg = element.attrib.get("package", "")
        self.resource_id = element.attrib.get("resource-id", "")
        self.clickable = element.attrib.get("clickable", "false") == "true"
        self.long_clickable = element.attrib.get("long-clickable", "false") == "true"
        self.checkable = element.attrib.get("checkable", "false") == "true"
        self.checked = element.attrib.get("checked", "false") == "true"
        self.scrollable = element.attrib.get("scrollable", "false") == "true"
        self.enabled = element.attrib.get("enabled", "true") == "true"
        self.focused = element.attrib.get("focused", "false") == "true"
        self.password = element.attrib.get("password", "false") == "true"
        self.visible = element.attrib.get("visible-to-user", "true") != "false"


def build_raw_tree(xml_root: ET.Element) -> Tuple[Optional[RawNode], int, int, int]:
    """Build hierarchy and extract root dimensions and rotation."""
    rotation = int(xml_root.attrib.get("rotation", "0"))
    screen_w = 0
    screen_h = 0

    first_node = xml_root.find("node")
    if first_node is None:
        return None, 0, 0, rotation

    def walk(el: ET.Element) -> RawNode:
        rn = RawNode(el)
        for child in el.findall("node"):
            rn.children.append(walk(child))
        return rn

    root_rn = walk(first_node)
    if root_rn.bounds:
        screen_w = max(screen_w, root_rn.bounds[2])
        screen_h = max(screen_h, root_rn.bounds[3])

    return root_rn, screen_w, screen_h, rotation


def should_include_node(node: RawNode, screen_w: int, screen_h: int) -> bool:
    """Evaluate inclusion and exclusion rules."""
    if not node.bounds:
        return False
    x1, y1, x2, y2 = node.bounds

    # Zero or negative area exclusion
    if x1 >= x2 or y1 >= y2:
        return False

    # Screen boundary exclusion
    if x2 <= 0 or y2 <= 0 or x1 >= screen_w or y1 >= screen_h:
        return False

    # visible-to-user exclusion
    if not node.visible:
        return False

    # Inclusion checks
    has_text = bool(node.text.strip() or node.desc.strip())
    is_interactive = (
        node.clickable or node.long_clickable or node.checkable or node.scrollable
    )
    class_leaf = node.class_name.rsplit(".", 1)[-1]
    is_interactive_class = class_leaf in INTERACTIVE_CLASSES

    return has_text or is_interactive or is_interactive_class


def parse_ui_tree(
    xml_bytes: bytes,
    snapshot_id: int = 1,
    full_labels: bool = False,
) -> Snapshot:
    """Parse uiautomator XML bytes into optimized Snapshot."""
    # Truncate at closing tag </hierarchy> if trailing text exists (e.g. from exec-out)
    closing_tag = b"</hierarchy>"
    idx_close = xml_bytes.find(closing_tag)
    if idx_close != -1:
        xml_bytes = xml_bytes[: idx_close + len(closing_tag)]

    try:
        root_et = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return Snapshot(
            id=snapshot_id,
            screen_width=0,
            screen_height=0,
            app_package="",
            rotation=0,
            elements=[],
            raw_xml=xml_bytes,
        )

    root_node, screen_w, screen_h, rotation = build_raw_tree(root_et)
    if not root_node:
        return Snapshot(
            id=snapshot_id,
            screen_width=screen_w,
            screen_height=screen_h,
            app_package="",
            rotation=rotation,
            elements=[],
            raw_xml=xml_bytes,
        )

    # Detect dominant / foreground package and childless WebViews
    pkg_counts: Dict[str, int] = {}
    warnings: List[str] = []
    for el in root_et.iter("node"):
        pkg = el.attrib.get("package", "")
        if pkg:
            pkg_counts[pkg] = pkg_counts.get(pkg, 0) + 1
        cls = el.attrib.get("class", "")
        if (cls == "android.webkit.WebView" or cls.endswith(".WebView")) and el.attrib.get("visible-to-user", "true") != "false":
            if el.find("node") is None:
                wb = parse_bounds(el.attrib.get("bounds", ""))
                if wb and (wb[2] - wb[0]) >= 200 and (wb[3] - wb[1]) >= 200:
                    w_label = clean_label(el.attrib.get("text", ""), el.attrib.get("content-desc", ""), full=False)
                    warnings.append(
                        f'! webview "{w_label}" [{wb[0]},{wb[1]}][{wb[2]},{wb[3]}] '
                        f"DOM not exposed in UI tree; use 'llmadb screen' for coordinate grid"
                    )
    fg_package = max(pkg_counts, key=pkg_counts.get) if pkg_counts else ""

    # Merge rules:
    # 1. Parent and sole child with identical bounds merge into one row.
    # 2. Clickable container with no own label takes descendant text when descendants are not separately clickable.
    suppressed_nodes: Set[int] = set()

    def merge_nodes(node: RawNode) -> List[RawNode]:
        merged_children: List[RawNode] = []
        for child in node.children:
            merged_children.extend(merge_nodes(child))
        node.children = merged_children

        # Rule 1: Check identical bounds with sole child
        if len(node.children) == 1:
            child = node.children[0]
            if node.bounds and child.bounds and node.bounds == child.bounds:
                if not node.text and child.text:
                    node.text = child.text
                if not node.desc and child.desc:
                    node.desc = child.desc
                if not node.resource_id and child.resource_id:
                    node.resource_id = child.resource_id
                if not node.pkg and child.pkg:
                    node.pkg = child.pkg
                if map_class_to_type(node.class_name) == "view":
                    node.class_name = child.class_name
                node.clickable = node.clickable or child.clickable
                node.long_clickable = node.long_clickable or child.long_clickable
                node.checkable = node.checkable or child.checkable
                node.checked = node.checked or child.checked
                node.scrollable = node.scrollable or child.scrollable
                node.focused = node.focused or child.focused
                node.password = node.password or child.password
                node.children = child.children

        # Rule 2: Clickable container inheriting descendant text
        if node.clickable and not node.text.strip() and not node.desc.strip():
            # Check if any descendant is separately clickable
            has_clickable_descendant = False
            desc_text_nodes: List[RawNode] = []

            def check_descendants(n: RawNode) -> None:
                nonlocal has_clickable_descendant
                for c in n.children:
                    if c.clickable or c.long_clickable:
                        has_clickable_descendant = True
                    t = c.text.strip() or c.desc.strip()
                    if t:
                        desc_text_nodes.append(c)
                    check_descendants(c)

            check_descendants(node)

            if not has_clickable_descendant and desc_text_nodes:
                first_node = desc_text_nodes[0]
                node.text = first_node.text.strip() or first_node.desc.strip()
                # Suppress the redundant inner text node if container took its text
                for tn in desc_text_nodes:
                    suppressed_nodes.add(id(tn))

        return [node]

    merged_tree = merge_nodes(root_node)

    # Collect included elements in document order
    included_nodes: List[RawNode] = []

    def collect(node: RawNode) -> None:
        if id(node) not in suppressed_nodes and should_include_node(node, screen_w, screen_h):
            included_nodes.append(node)
        for child in node.children:
            collect(child)

    for r in merged_tree:
        collect(r)

    # Deduplicate exact duplicate bounds & labels if identical
    seen_keys: Set[Tuple[Tuple[int, int, int, int], str]] = set()
    elements: List[Element] = []
    idx = 1

    for node in included_nodes:
        bounds = node.bounds
        assert bounds is not None
        label = clean_label(node.text, node.desc, full=full_labels)
        key = (bounds, label)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        cx = (bounds[0] + bounds[2]) // 2
        cy = (bounds[1] + bounds[3]) // 2

        node_type = map_class_to_type(node.class_name)

        # Short ID calculation
        short_id = ""
        if node.resource_id:
            res = node.resource_id
            if fg_package and res.startswith(f"{fg_package}:id/"):
                short_id = res.split(":id/", 1)[1]
            elif ":id/" in res:
                short_id = res  # keep package if foreign
            else:
                short_id = res

        # Flags calculation
        flags: List[str] = []
        if not node.enabled:
            flags.append("-enabled")
        if node.checked:
            flags.append("checked")
        if node.focused:
            flags.append("focused")
        if node.password:
            flags.append("password")
        if node.scrollable and node_type != "scroll":
            flags.append("scroll")
        if node_type in INTERACTIVE_TYPES and not node.clickable:
            flags.append("!clickable")

        elements.append(
            Element(
                idx=idx,
                node_type=node_type,
                label=label,
                resource_id=node.resource_id,
                short_id=short_id,
                bounds=bounds,
                center=(cx, cy),
                flags=flags,
                raw_class=node.class_name,
                package=node.pkg,
            )
        )
        idx += 1

    return Snapshot(
        id=snapshot_id,
        screen_width=screen_w,
        screen_height=screen_h,
        app_package=fg_package,
        rotation=rotation,
        elements=elements,
        raw_xml=xml_bytes,
        warnings=warnings,
    )
