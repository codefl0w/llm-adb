# llm-adb Autonomous Agent Test Suite

A model-agnostic, runtime-agnostic test suite for evaluating autonomous LLM agents controlling Android devices through `llm-adb`.

---

## Instructions for the LLM Agent Under Test

> **Agent Directive:**
> You are an autonomous coding/agent model testing an Android device via `llm-adb` (CLI binary: `llmadb`, or raw `adb` during baseline runs).
> 1. **Learn primitives first.** Run `llmadb --help` and `llmadb --help-llm` before running commands to understand syntax, options, and output formats.
> 2. **Perceive before acting.** Use `llmadb ui` to inspect indexed elements. If the screen is busy, animating, has an `! overlay` warning, or contains a childless WebView, use `llmadb screen` to view the 100px device coordinate grid.
> 3. **Follow the high-level task instructions.** Do not rely on hardcoded coordinates or predetermined element indices. Inspect the device, plan your actions, and adapt dynamically.
> 4. **NO CHEATING (Strict On-Device UI Enforcement):** Models are strictly prohibited from using host harness tools (`web_search`, `fetch`, host `curl`/`Invoke-WebRequest`) or shell shortcuts (`adb shell curl`, `wget`, or `am start -a VIEW -d <url>` deep-linking past search/navigation steps) to pre-fetch websites, scrape HTML, or paste direct download links. Every navigation, search, and interaction step must be executed natively through the device UI via `adb` or `llmadb`, no exceptions.
> 5. **Confirm success** using the stated verification criteria for each test.
> 6. **Report state changes and propose cleanup:** Once testing is complete, report every system toggle modified, package installed, and file created. Recommend exact `llmadb` commands to revert the device to its original state, and offer to execute the cleanup.

---

## Model Capability Tiers & Raw `adb` Baseline Protocol

### 1. Capability Tiers
Not all models support multimodal vision inputs. Test cases are divided into two capability tiers:
- **Tier 1 - Text / Accessibility Hierarchy Only (`TC-01` through `TC-04`):**
  - Can be completed using compact accessibility trees (`llmadb ui` or raw `adb shell uiautomator dump`) without inspecting screenshots.
  - **Mandatory Entry Gate (`TC-02`):** All models (both multimodal vision models and text-only local models) must first be evaluated on **TC-02 (Launcher Navigation & Web Search)** to validate core perception, app launch, and text input.
- **Tier 2 - Multimodal Vision Required (`TC-05` and `TC-06`):**
  - Requires reading screenshots (`llmadb screen` 100px coordinate grid or `adb exec-out screencap -p`) to navigate unexposed browser WebViews, 60fps animations (`! ui busy/animating`), and non-focused system overlays / dynamic-island alerts.
  - Only justified for models with image-viewing capabilities that have passed Tier 1 (`TC-02`).

### 2. Raw `adb` vs. `llm-adb` Comparative Baseline
Raw token counts are only meaningful when compared against an unassisted `adb` baseline on the same hardware and task:
1. **Raw `adb` Baseline Run:** Execute `TC-02` and `TC-06` on zero-context ("clueless") agents with `llmadb` masked from `PATH`, restricting the agent to standard `adb` commands (`adb shell uiautomator dump`, `adb shell input tap/swipe/text/keyevent`, `adb exec-out screencap -p`, `adb shell dumpsys`, `adb install`).
2. **`llm-adb` Evaluation Runs:** Execute the identical tasks on zero-context agents with `llm-adb` enabled (`llmadb --help` and `llmadb --help-llm`). Run multiple trials per model per test (`1x Raw adb` + `2x llm-adb` = `3 results per model per test`) to establish statistical credibility and compare uncached token consumption, cached context reads, and wall-clock execution time.

---

## Verified Target Environments

`llm-adb` primitives and this test suite have been validated live on three distinct Android generations and UI skins:

| Platform | Device / Hardware | Android / SDK | UI Skin | Resolution & DPI |
|---|---|---|---|---|
| **Legacy OEM** | Samsung Galaxy Note 5 (`SM-N920C`) | Android 7.0 (SDK 24) | Grace UX / TouchWiz | `720x1280` effective (`1440x2560` physical) |
| **Modern OEM** | OnePlus 11 (`CPH2451`, Snapdragon 8 Gen 2) | Android 16 (SDK 36) | OxygenOS 16 | `1080x2412` (480 DPI) |
| **Modern AOSP** | Google Pixel Emulator (`sdk_gphone16k_x86_64`) | Android 17 (SDK 37) | Stock AOSP / Pixel UI | `1080x2400` (420 DPI) |

Behavior across Android versions and OEM skins varies in layout, element naming, and system overlays. Agents must discover controls dynamically rather than assuming static indices or coordinates.

### Host Preconditions
- Python 3.9+ with `pip install -e .`
- `adb` available on system `PATH` (or specified via `LLMADB_ADB`)
- Host connected to target device (or `LLMADB_SERIAL` set)
- Verify connection: `llmadb devices`

### Device Preconditions
- Device unlocked.
- Display stay-awake enabled or screen timeout set to >= 5 minutes.
- Target Quick Settings toggle (e.g. Bluetooth, NFC, Airplane mode, Auto-rotate, or Flashlight) **must be in the OFF state** prior to test execution.
- Required applications available:
  - Web browser (e.g. Chrome or Firefox)
  - System Clock app with Timer capability
  - File explorer application
  - Quick Settings notification shade with accessible tiles

---

## Primitive Execution Speed Benchmarks

Do not measure total model wall-clock time; model thinking time, parameter size, and API network latency vary widely across frontier, local, and quantized models.

Instead, measure **`llmadb` CLI execution response latency** on the host machine:

| Primitive | Operation | Maximum Acceptable CLI Latency |
|---|---|---|
| `llmadb current` | Batched focus, rotation, and IME query | < 350 ms |
| `llmadb rotate` | Orientation query and toggle | < 400 ms |
| `llmadb status` | Battery and connectivity query | < 500 ms |
| `llmadb info <pkg>` | Package metadata, SDK, permissions, and PID | < 500 ms |
| `llmadb list apps` | Package categorization and filtering | < 800 ms |
| `llmadb type "..."` | Keyevent clear + ASCII text dispatch | < 1.0 s |
| `llmadb screen` | Screencap + 960 downscale + 100px grid annotation | < 1.5 s |
| `llmadb ui` (idle) | Hierarchy dump + snapshot caching | < 2.5 s |
| `llmadb tap <target>` | Input tap/hold + 150ms animation pause + settle dump | < 2.5 s |
| `llmadb ui` (busy/animating) | Fail-fast non-idle dump + overlay detection | < 4.0 s (no 30s hang) |
| `llmadb log --since-mark` | Timestamp mark + deduplicated PID filter | < 500 ms |

---

## Test Cases

### TC-01: Hardware, Window State & Package Inspection
- **Preconditions:** Device unlocked; at least one third-party/user package installed.
- **Task Instructions:**
  1. Run `llmadb devices` and `llmadb hardware` to inspect device specifications.
  2. Open an application, run `llmadb current` with the software keyboard hidden, then focus a text input field and re-run `llmadb current` to confirm `keyboard=visible`.
  3. List installed user applications (`llmadb list apps user`) and inspect a package (`llmadb info <pkg>`).
  4. Record a logcat timestamp mark (`llmadb mark`), launch the package (`llmadb launch <pkg>`), inspect logs since the mark (`llmadb log --pkg <pkg> --since-mark`), then stop the package (`llmadb stop <pkg>`).
- **Verification Criteria:**
  - `llmadb hardware` populates resolution, DPI, SDK, memory, storage, and SELinux state.
  - `llmadb current` accurately transitions between `keyboard=hidden` and `keyboard=visible`.
  - `llmadb info <pkg>` reports `running=stopped` after force-stop.

---

### TC-02: Launcher Navigation & Web Search
- **Preconditions:** Device on home screen; browser installed.
- **Task Instructions:**
  1. Inspect the home screen launcher.
  2. Open the web browser.
  3. Search the web for `"codefl0w"` using `llmadb type --clear "codefl0w" --enter`.
  4. Confirm that the search results page loaded.
- **Verification Criteria:**
  - `llmadb current` reports browser package in foreground.
  - UI snapshot contains search result text matching `"codefl0w.xyz"` or `"fl0w"`.

---

### TC-03: Quick Settings Expansion & Toggle State Change
- **Preconditions:** Target quick settings tile (e.g. Bluetooth, NFC, Airplane mode, Auto-rotate, or Flashlight) is **OFF**.
- **Task Instructions:**
  1. Pull down the Quick Settings notification panel.
  2. Locate the designated toggle tile (expand full grid or swipe pages if paginated).
  3. Confirm the tile is currently off, then toggle it ON.
  4. Verify the tile reflects the active/on state.
  5. Return to the home screen.
- **Verification Criteria:**
  - Tile accessibility state or label reflects active (`[checked]`, `"On"`, or `"Enabled"`).
  - `llmadb current` reports launcher in foreground.

---

### TC-04: File Creation & Transparent Passthrough Validation
- **Preconditions:** File explorer application installed.
- **Task Instructions:**
  1. Open the file explorer application.
  2. Navigate into the standard `Download` directory (`/sdcard/Download`).
  3. Create a text file named `test.txt` containing the text `"Success"` (or if the stock AOSP file manager is read-only for text creation, create a folder via UI and write `test.txt` via passthrough).
  4. Validate file contents using `llmadb shell cat /sdcard/Download/test.txt`.
- **Verification Criteria:**
  - `llmadb shell cat /sdcard/Download/test.txt` outputs exact string `Success` with exit code `0`.

---

### TC-05: Visual Recovery & Coordinate Grid Navigation
- **Preconditions:** Web browser installed and connected to internet.
- **Task Instructions:**
  1. Open a test URL triggering an SSL certificate warning or unexposed DOM in the browser (`https://expired.badssl.com/`).
  2. Open advanced details view to locate the bypass/proceed link.
  3. Capture an annotated screenshot with `llmadb screen` and inspect the 100px device coordinate grid.
  4. Tap the proceed link by coordinates (`llmadb tap x,y`) or element index and verify the destination page loads.
- **Verification Criteria:**
  - `llmadb screen` produces a downscaled image (`max-edge 960`) with 100px device coordinate grid and interior crosshairs.
  - Tapping the proceed control loads the destination page.

---

### TC-06: End-to-End Multi-App Autonomous Flow
- **Preconditions:**
  - Target quick settings toggle is **OFF**.
  - Device connected to internet.
  - Clock app with timer function available.
- **Task Instructions:**
  1. Open Quick Settings and turn ON the designated toggle.
  2. Return to the home screen and open the web browser.
  3. Search for `"MiXplorer XDA"` and open the official XDA Forums release thread.
  4. Locate the APK download link, download the compatible APK for the device architecture, and install/update it (note: on Android 11+, stage device APKs via `/data/local/tmp/` before running `pm install -r`, or use host `llmadb install -r`). Verify installation with `llmadb info <pkg>`.
  5. Open the Clock app and set a timer for 20 seconds (with label `"Test success"` if the Clock app provides a label field).
  6. Start the 20-second countdown, then immediately return to the home screen (`llmadb key home`).
  7. Wait for the timer to expire. Run `llmadb ui` and `llmadb screen` to catch the heads-up notification or alarm overlay, tap the Stop/Dismiss button to turn it off, and verify the home screen is clear.
- **Verification Criteria:**
  - Quick settings toggle switched from OFF to ON.
  - Target APK installed; `llmadb info <pkg>` confirms installation.
  - Active countdown or animation returns in < 4 seconds without a 30-second UI hang.
  - Expired timer heads-up banner / overlay detected (`! overlay window="..."` or via `llmadb screen` grid) and dismissed via single tap.
  - Final foreground state is home launcher with alarm silenced.

---

## Post-Test Reporting & Reversion Directive

> [!IMPORTANT]
> **Mandatory Agent Step Upon Completion:**
> When reporting results to the user after running any test that modifies device state:
> 1. **State Summary:** Explicitly list every change made to the device:
>    - System toggles modified (e.g. NFC or Bluetooth turned ON).
>    - Packages installed or updated (e.g. package name, version, APK path).
>    - Files or directories created on disk (e.g. `/sdcard/Download/test.txt`).
> 2. **Reversion Recommendation:** Provide the exact `llmadb` commands required to revert the device to its pre-test state.
>    Example:
>    ```bash
>    # 1. Turn toggle back OFF
>    llmadb swipe 540,10 540,1500
>    llmadb tap <toggle_index_or_coords>
>    llmadb key home
>
>    # 2. Uninstall installed test package (if newly installed)
>    llmadb shell pm uninstall <pkg_name>
>
>    # 3. Clean created files
>    llmadb shell rm -rf /sdcard/Download/test.txt
>    ```
> 3. **Offer Execution:** Ask the user if they would like you to execute the reversion commands immediately.
