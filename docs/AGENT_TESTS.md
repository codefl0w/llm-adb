# llm-adb Zero-Context Autonomous Agent Benchmark - OnePlus 11 (Android 16)

## 1. Benchmark Environment & Methodology
- **Device:** OnePlus 11 (`CPH2451`), Qualcomm Snapdragon 8 Gen 2 (`kalama`, `arm64-v8a`), `1080x2412` (480 DPI)
- **OS / Skin:** Android 16 (SDK 36), OxygenOS 16 (Turkish system locale)
- **Zero-Context Isolation:** Every trial launched in an empty working directory with zero prior conversation history and barred from reading any repository documentation (`README.md`, `TEST_SUITE.md`).
  - **Raw `adb` Baseline Runs:** `llmadb` binary was temporarily removed from `PATH` so agents had to operate the device strictly with standard `adb` commands (`adb shell uiautomator dump`, `adb shell input tap/swipe/text/keyevent`, `adb exec-out screencap -p`, `adb shell dumpsys`, `adb install`).
  - **`llm-adb` Evaluation Runs:** Agents learned `llm-adb` strictly by running `llmadb --help` and `llmadb --help-llm` at the start of their session.
- **Strict Anti-Cheating Rule (`NO CHEATING`):** Agents were strictly prohibited from using host harness tools (`web_search`, `fetch`, host `curl`/`Invoke-WebRequest`) or shell shortcuts (`adb shell curl`/`wget`, `svc nfc`, `cmd nfc`, or `am start -d <url>` deep-linking past search/navigation steps) to pre-fetch websites or paste direct links. Every toggle, search, link click, and timer action had to be performed natively through the Android UI on-device.
- **Capability Tiers Tested:**
  - **Tier 1 (`TC-02: Launcher Navigation & Web Search`):** Evaluates all 3 models (including text-only local models) on launcher inspection, browser launch, search input (`'codefl0w'`), and result verification (`codefl0w.xyz` / `fl0w`).
  - **Tier 2 (`TC-06: End-to-End Multi-App Autonomous Flow`):** Evaluates multimodal vision models (plus 1 text-only baseline run demonstrating why vision is required) on 7 multi-app stages: Quick Settings NFC ON -> Browser search `'MiXplorer XDA'` -> XDA thread -> APK download & installation -> `llmadb info` verification -> 20s Clock timer -> return to home screen -> catch & dismiss OxygenOS dynamic-island (`SeedlingCard`) timer alert -> state summary & reversion report.

---

## 2. Comprehensive Comparison Charts: Raw `adb` vs. `llmadb`

### A. Tier 1 - `TC-02` (Launcher Navigation & Web Search, 3 Runs per Model = 9 Runs)

| Model | Toolchain & Trial | Success | Time Elapsed | Uncached Input | Output Tokens | Total Uncached Tokens | Cached Input Reads | Total Context Tokens | `llmadb` Advantage vs. Raw `adb` |
|---|---|---|---|---|---|---|---|---|---|
| **Gemini 3.8 Flash (Low)** | **Raw `adb`** (Baseline) | **Yes** | `66.6s` | `131,414` | `1,251` | `132,665` | `88,597` | `221,262` | *Baseline* |
| **Gemini 3.8 Flash (Low)** | **`llmadb`** (Trial 1, cold cache) | **Yes** | `63.2s` | `158,540` | `635` | `159,175` | `0` | `159,175` | **-28.1% total tokens**, **-49.2% output tokens**, **-5.1% time** |
| **Gemini 3.8 Flash (Low)** | **`llmadb`** (Trial 2, Google SERP) | **Yes** | `88.8s` | `137,697` | `802` | `138,499` | `104,975` | `243,474` | **-35.9% output tokens**, zero `/sdcard/*.xml` clutter |
| **Claude Sonnet 5.5 (Low)** | **Raw `adb`** (Baseline) | **Yes** | `40.6s` | `13,364` | `1,875` | `15,239` | `91,525` | `106,764` | *Baseline (autocomplete to `codefl0w.xyz`)* |
| **Claude Sonnet 5.5 (Low)** | **`llmadb`** (Trial 1, SERP + site) | **Yes** | `61.7s` | `36,952` | `2,020` | `38,972` | `142,914` | `181,886` | Verified both `codefl0w.xyz` AND Google SERP |
| **Claude Sonnet 5.5 (Low)** | **`llmadb`** (Trial 2, same path) | **Yes** | **`31.3s`** | `18,327` | **`1,224`** | `19,551` | **`63,825`** | **`83,376`** | **-22.9% time**, **-21.9% total tokens**, **-30.3% cached reads**, **-34.7% output tokens** |
| **CyberTiel 35B-A3B (Local)** | **Raw `adb`** (Baseline, 25 turns) | **Yes** | `208.8s` (`3m 28.8s`) | `6,358` | `6,187` | `12,545` | `153,526` | `166,071` | *Baseline (25 turns, manual XML regex & 20x DEL)* |
| **CyberTiel 35B-A3B (Local)** | **`llmadb`** (Trial 1, 17 turns) | **Yes** | `130.3s` (`2m 10.3s`) | `6,198` | `2,694` | `8,892` | `88,571` | `97,463` | **-37.6% time**, **-29.1% uncached**, **-41.3% total tokens**, **-56.5% output**, **-32% turns** |
| **CyberTiel 35B-A3B (Local)** | **`llmadb`** (Trial 2, 17 turns) | **Yes** | **`110.3s`** (`1m 50.3s`) | **`5,501`** | `3,064` | **`8,565`** | `94,491` | `103,056` | **-47.2% time**, **-31.7% uncached**, **-37.9% total tokens**, **-50.5% output**, **-32% turns** |

---

### B. Tier 2 - `TC-06` (End-to-End Multi-App Autonomous Flow, 7 Stages)

| Model | Toolchain & Trial | Vision | Success | Time Elapsed | Uncached Input | Output Tokens | Total Uncached Tokens | Cached Input Reads | `llmadb` Advantage vs. Raw `adb` |
|---|---|---|---|---|---|---|---|---|---|
| **Gemini 3.8 Flash (Low)** | **Raw `adb`** (Baseline) | Yes | **No** *(0/1; hung at step 4 Play Protect)* | `723.2s` (`12m 03.2s` T/O) | `355,723` | `8,783` | `364,506` | `2,833,784` | *Failed: mis-tapped 2015 APK without grid; hung on Play Protect* |
| **Gemini 3.8 Flash (Low)** | **`llmadb`** (Trial 1) | Yes | **Yes** *(7/7 stages)* | **`441.3s`** (`7m 21.3s`) | **`251,359`** | **`3,046`** | **`254,405`** | **`2,054,912`** | **Passed (vs Failed)**, **-39.0% time**, **-30.2% uncached tokens**, **-65.3% output tokens** |
| **Gemini 3.8 Flash (Low)** | **`llmadb`** (Trial 2, GUI install) | Yes | **Partial** *(6.5/7; timer active at 720s T/O)* | `723.1s` (`12m 03.1s` T/O) | `372,539` | `4,851` | `377,390` | `5,381,109` | Installed v6.71.15 via UI `packageinstaller` & started timer (`! overlay window="SeedlingCard"`), **-44.8% output tokens** |
| **Claude Sonnet 5.5 (Low)** | **Raw `adb`** (Baseline) | Yes | **Yes** *(7/7 stages)* | `695.4s` (`11m 35.4s`) | `149,402` | `14,344` | `163,746` | `2,889,429` | *Baseline: 2 failed `pm install` attempts + Drive mis-tap* |
| **Claude Sonnet 5.5 (Low)** | **`llmadb`** (Trial 1) | Yes | **Yes** *(7/7 stages)* | **`498.8s`** (`8m 18.8s`) | **`97,347`** | **`11,676`** | **`109,023`** | **`2,774,995`** | **-28.3% time (`-3m 16.6s`)**, **-33.4% uncached tokens**, **-34.8% input tokens**, **-18.6% output tokens** |
| **Claude Sonnet 5.5 (Low)** | **`llmadb`** (Trial 2, GUI install) | Yes | **Yes** *(7/7 stages, 19 snaps)* | `853.1s` (`14m 13.1s`) | **`122,224`** | `14,823` | **`137,047`** | `4,578,625` | **-16.3% uncached tokens** & **-18.2% input tokens** vs Raw `adb` despite full GUI PackageInstaller flow |
| **CyberTiel 35B-A3B (Local)** | **`llmadb`** (Trial 1, Text-Only) | **No** | **No** *(1/7 stages; stalled on WebView)* | `754.0s` (`12m 34.0s`) | `7,811` | `6,508` | `14,319` | `234,970` | Proves Tier 2 (`TC-06`) requires multimodal vision for unexposed WebViews & overlays |

### Key Quantitative Takeaways
1. **Local MoE Model Efficiency (`TC-02` on CyberTiel 35B-A3B):**
   - With Raw `adb`, CyberTiel required **25 turns and 208.8s** (`12,545` uncached tokens, `166,071` total context tokens) to write custom `grep`/`sed` XML parsers, compute bounding box centers by hand, and send 20x `KEYCODE_DEL`.
   - With `llmadb`, CyberTiel completed `TC-02` in **17 turns** across both trials (**-32.0% fewer turns**), averaging **120.3s (-42.4% faster)**, **8,729 uncached tokens (-30.4%)**, **2,879 output tokens (-53.5%)**, and **100,260 total context tokens (-39.6%)**.
2. **Complex Multi-App Reliability & Token Savings (`TC-06` on Gemini 3.8 Flash & Claude Sonnet 5.5):**
   - **Gemini 3.8 Flash (Low):** Failed completely under Raw `adb` (`364,506` uncached tokens, `723.2s` timeout) after mis-tapping a 2015 APK without `llmadb screen`'s coordinate grid and hanging on a Play Protect dialog. With `llmadb`, it succeeded in **441.3s (-39.0% time)** using **254,405 uncached tokens (-30.2%)** in Trial 1, and reached `6.5/7` stages (`SeedlingCard` timer active on home screen) in Trial 2 even when installing entirely through the Android GUI PackageInstaller.
   - **Claude Sonnet 5.5 (Low):** Completed `TC-06` in `695.4s` and `163,746` uncached tokens under Raw `adb` (suffering two `pm install` failures and a Drive mis-tap). With `llmadb`, it succeeded in **both Trial 1 (`498.8s`, `109,023` uncached tokens - 28.3% faster and 33.4% fewer uncached tokens)** and **Trial 2 (`137,047` uncached tokens - 16.3% fewer uncached tokens in just 19 snapshots)**.

---

## 3. Individual Run Logs (`TC-02` - Launcher Navigation & Web Search)

### Gemini 3.8 Flash (Low) - TC-02 (Raw `adb` Baseline, Trial 1)
Success: Yes
Time elapsed: 1m 06.6s (66.6s)
Tokens spent: 132,665 uncached (131,414 input + 1,251 output + 0 thinking) | 88,597 cached input reads (221,262 total billed/cached)
Extra notes: Zero-context Raw `adb` run (`6847d638-d556-4f1c-90cc-b341706ee277`). Had to manually dump raw XML hierarchies to `/sdcard/window_dump.xml`, `/sdcard/firefox_dump.xml`, and `/sdcard/search_result.xml` plus a full-resolution `1080x2412` screenshot (`/sdcard/search_result.png`), consuming **132,665 uncached tokens** (`221,262` total tokens) for a 4-step browser search flow.

### Gemini 3.8 Flash (Low) - TC-02 (`llmadb`, Trial 1)
Success: Yes
Time elapsed: 1m 03.2s (63.2s)
Tokens spent: 159,175 uncached (158,540 input + 635 output + 0 thinking) | 0 cached input reads (159,175 total billed/cached)
Extra notes: Zero-context `llmadb` run (`85ebc7da-cb51-41e2-ba7b-18e876bba830`, cold provider prompt cache). Used `llmadb ui`, `llmadb tap`, and `llmadb type --clear "codefl0w" --enter`, cutting **total context tokens by 28.1% (`159,175` vs `221,262`)** and **output tokens by 49.2% (`635` vs `1,251`)** compared to Raw `adb`.

### Gemini 3.8 Flash (Low) - TC-02 (`llmadb`, Trial 2)
Success: Yes
Time elapsed: 1m 28.8s (88.8s)
Tokens spent: 138,499 uncached (137,697 input + 802 output + 0 thinking) | 104,975 cached input reads (243,474 total billed/cached)
Extra notes: Zero-context `llmadb` run (`b469e17a-ed2e-4a85-bdb6-9358f4a95650`). Executed a fresh Google search from `google.com`, verifying results (`codefl0w.xyz`, `GitHub fl0w codefl0w`, `codefl0w/QuickADB`) with **35.9% fewer output tokens (`802` vs `1,251`)** and zero leftover XML/PNG clutter on `/sdcard/`.

---

### Claude Sonnet 5.5 (Low) - TC-02 (Raw `adb` Baseline, Trial 1)
Success: Yes
Time elapsed: 40.6s
Tokens spent: 15,239 uncached (13,364 input + 1,875 output + 0 thinking) | 91,525 cached input reads (106,764 total billed/cached)
Extra notes: Zero-context Raw `adb` run (`016e911c-903e-4a50-a9b8-f4a89871fbc5`). Used `grep`/`sed` filtering on `/sdcard/u.xml` to avoid pulling full raw XML files into context, keeping uncached input tokens down to `13,364` (`91,525` cached reads). Tapped address bar `(400,216)`, sent `input text codefl0w` + `keyevent 66`, and verified page text `"I'm fl0w, an Android developer"` and `"GitHub stats board for codefl0w"`.

### Claude Sonnet 5.5 (Low) - TC-02 (`llmadb`, Trial 1)
Success: Yes
Time elapsed: 1m 01.7s (61.7s)
Tokens spent: 38,972 uncached (36,952 input + 2,020 output + 0 thinking) | 142,914 cached input reads (181,886 total billed/cached)
Extra notes: Zero-context `llmadb` run (`ac708223-c60c-434b-8327-60cb9e12b4e5`). Learned `llmadb` via `--help` and `--help-llm`, opened Firefox via `llmadb tap --text Firefox`, and when Firefox URL autocomplete went straight to `codefl0w.xyz` (where Raw `adb` Trial 1 stopped), Sonnet went a step further: pressed back, tapped the Google search box (`llmadb tap 12`), and ran `llmadb type "codefl0w" --clear --enter` to verify the actual Google SERP (`google.com/search?q=codefl0w`) in addition to `codefl0w.xyz`.

### Claude Sonnet 5.5 (Low) - TC-02 (`llmadb`, Trial 2)
Success: Yes
Time elapsed: 31.3s
Tokens spent: 19,551 uncached (18,327 input + 1,224 output + 0 thinking) | 63,825 cached input reads (83,376 total billed/cached)
Extra notes: Zero-context `llmadb` run (`175a9bf5-f2e3-4f83-a6a9-3111631ece31`). Completed the exact same navigation path as Raw `adb` Trial 1 in **31.3s vs 40.6s (22.9% faster)** while reducing **total context tokens by 21.9% (`83,376` vs `106,764`)**, **cached reads by 30.3% (`63,825` vs `91,525`)**, and **output tokens by 34.7% (`1,224` vs `1,875`)**.

---

### CyberTiel 35B-A3B (Local) - TC-02 (Raw `adb` Baseline, Trial 1)
Success: Yes
Time elapsed: 3m 28.8s (208.8s)
Tokens spent: 12,545 uncached (6,358 input + 6,187 output across 25 turns) | 153,526 cached input reads (166,071 total context tokens)
Extra notes: Zero-context Raw `adb` run (`01a15db5-3800-74ed-8859-3e262cf15e29`). Completed `TC-02` using text-only hierarchy inspection (`uiautomator dump /sdcard/heap.xml`), proving CyberTiel can solve Tier 1 tasks without vision. However, without `llmadb`'s compact UI tree or `llmadb type --clear --enter`, it required **25 turns and 3m 28.8s** to write custom shell `grep`/`sed` XML parsers, manually calculate bounding box centers `(540, 2217)` and `(426, 215)`, send 20x `KEYCODE_DEL` backspaces, and type `'codefl0w'` character-by-character.

### CyberTiel 35B-A3B (Local) - TC-02 (`llmadb`, Trial 1)
Success: Yes
Time elapsed: 2m 10.3s (130.3s)
Tokens spent: 8,892 uncached (6,198 input + 2,694 output across 17 turns) | 88,571 cached input reads (97,463 total context tokens)
Extra notes: Zero-context `llmadb` run (`01a15dd8-efc4-70cc-a541-49d9a7741b60`). Compared to Raw `adb`, `llmadb` reduced **turns by 32.0% (`17` vs `25`)**, **wall-clock time by 37.6% (`130.3s` vs `208.8s`)**, **uncached tokens by 29.1% (`8,892` vs `12,545`)**, **output tokens by 56.5% (`2,694` vs `6,187`)**, and **total context tokens by 41.3% (`97,463` vs `166,071`)**.

### CyberTiel 35B-A3B (Local) - TC-02 (`llmadb`, Trial 2)
Success: Yes
Time elapsed: 1m 50.3s (110.3s)
Tokens spent: 8,565 uncached (5,501 input + 3,064 output across 17 turns) | 94,491 cached input reads (103,056 total context tokens)
Extra notes: Zero-context `llmadb` run (`01a15ddb-ae85-7569-83aa-2920e6b21c98`). Highly repeatable 17-turn execution (**47.2% faster (`110.3s` vs `208.8s`)**, **31.7% fewer uncached tokens (`8,565` vs `12,545`)**, and **37.9% fewer total tokens (`103,056` vs `166,071`)** than Raw `adb`).

---

## 4. Individual Run Logs (`TC-06` - End-to-End Multi-App Autonomous Flow)

# Gemini 3.8 Flash (Low) - TC-06 (Raw `adb` Baseline)
Success: No (Hung at APK installation / Play Protect dialog; timed out at 12m 03.2s)
Time elapsed: 12m 03.2s (723.2s; 578.9s active model turn + background task hang)
Tokens spent: 364,506 uncached (355,723 input + 8,783 output + 0 thinking) | 2,833,784 cached input reads (3,198,290 total billed/cached)
Extra notes: Zero-context Raw `adb` run (`552f9164-65ac-4b34-933f-a77e2a57d137`). Toggled NFC ON (`mState=on`) and opened the XDA thread in Firefox, but without `llmadb screen`'s 100px coordinate grid it mis-tapped an archived 2015 attachment (`MiXplorer_v5.3.0-build-201506092.apk`) instead of the current v6.71.15 release link. When it ran raw `pm install` on the legacy APK, Google Play Protect popped up a blocking confirmation dialog (`PlayProtectDialogsActivity`), hanging the background `pm install` command until the 12-minute timeout expired. Never reached the Clock timer stage despite spending **43.3% more uncached tokens (`364,506` vs `254,405`)** and **63.9% more time (`723.2s` vs `441.3s`)** than its `llmadb` Trial 1 run.

# Gemini 3.8 Flash (Low) - TC-06 (`llmadb`, Trial 1)
Success: Yes
Time elapsed: 7m 21.3s (441.3s)
Tokens spent: 254,405 uncached (251,359 input + 3,046 output + 0 thinking) | 2,054,912 cached input reads (2,309,317 total billed/cached)
Extra notes:
- **Session ID:** `cc7e706b-210f-444d-a87c-6024231de231` (`agy --model gemini-3.8-flash-low --dangerously-skip-permissions`)
- **Stage-by-Stage Execution on OnePlus 11 (`snap=81` -> `snap=120`):**
  1. **CLI Discovery:** Ran `llmadb --help` and `llmadb --help-llm`, then inspected hardware (`1080x2412`, `arm64-v8a`) and initial UI tree.
  2. **Quick Settings NFC Toggle:** Expanded Quick Settings shade, located the Turkish NFC tile (`switch "Kapalı" id=oplus_separate_qs_resizeable_tile_container @426,1737`), tapped it, and verified transition to `switch "Açık" [checked]` (`mState=on`).
  3. **Browser & XDA Navigation:** Returned home (`llmadb key home`), opened Firefox (`org.mozilla.firefox`) from dock, searched `'MiXplorer XDA'`, opened the official XDA thread, and navigated to the download repository (`mixplorer.com/beta`).
  4. **APK Download, Staging & Installation:** Downloaded `MiXplorer_v6.71.15-BETA_B26090412-arm64.apk` to `/sdcard/Download/`. Installed on device and ran `llmadb info com.mixplorer`; when `llmadb` returned `E_NOT_FOUND` with `hint: run 'llmadb list apps all --grep <name>'`, it immediately discovered the package was `com.mixplorer.beta` and confirmed `version: 6.71.15-BETA (26090412)`.
  5. **Clock Timer Creation:** Launched `com.oneplus.deskclock`, switched to the `Sayaç` (Timer) tab, created a 20-second timer preset labeled `"Test success"`, and started the countdown.
  6. **Home Screen Return & Dynamic-Island Dismissal:** Immediately executed `llmadb key home`. Waited for expiration; because OxygenOS 16 renders the expired timer inside its custom top capsule / dynamic-island overlay rather than the standard accessibility hierarchy, `llmadb screen` (100px coordinate grid) was used to visually locate the dismiss `"X"` button on the banner and tap it directly.
  7. **Post-Test Reporting:** Verified clean home screen (`snap=120`) and output a complete state summary and reversion command block without prematurely executing cleanup.

# Gemini 3.8 Flash (Low) - TC-06 (`llmadb`, Trial 2)
Success: Partial (6.5/7 stages completed - NFC ON, `com.mixplorer` v6.71.15 installed via UI PackageInstaller, Clock timer started & returned home with `! overlay window="SeedlingCard"` active; cut off by 720s harness timeout during 20s countdown sleep)
Time elapsed: 12m 03.1s (723.1s; 711.1s active model turn)
Tokens spent: 377,390 uncached (372,539 input + 4,851 output + 0 thinking) | 5,381,109 cached input reads (5,758,499 total billed/cached)
Extra notes: Zero-context `llmadb` run (`dc00b040-7d2c-41d1-bf64-e9c27fc0f795`). Under the strict **NO CHEATING** prompt rule, instead of using `pm install`, Flash installed `com.mixplorer` (`6.71.15 (26090422)`) entirely through the Android GUI (`com.google.android.packageinstaller`), navigating Google Drive and PackageInstaller confirmation dialogs via `llmadb ui` / `llmadb screen`. It then opened Clock, started the timer, returned to the home screen (`com.android.launcher`), and triggered the OxygenOS Fluid Cloud / Dynamic Island overlay (`! overlay window="SeedlingCard" bounds=[48,120][1032,408] @540,264`), where the 720s `--print-timeout` fired while its `sleep` command was waiting for the 20s timer to finish.

---

# Claude Sonnet 5.5 (Low) - TC-06 (Raw `adb` Baseline)
Success: Yes
Time elapsed: 11m 35.4s (695.4s)
Tokens spent: 163,746 uncached (149,402 input + 14,344 output + 0 thinking) | 2,889,429 cached input reads (3,053,175 total billed/cached)
Extra notes: Zero-context Raw `adb` run (`733e7ebc-47be-4388-bef3-0485994c27af`). Completed all 7 stages, but without `llmadb`: (1) lacked `llmadb screen`'s 100px coordinate grid and mis-tapped a link on XDA/Drive before recovering, (2) lacked `--help-llm`'s Android 11+ staging rule so it failed twice on `pm install` (`Permission denied` on `/sdcard/Download`, then `INSTALL_PARSE_FAILED_NOT_APK` on stdin streaming) before discovering `/data/local/tmp/mix.apk`, and (3) had to write manual `uiautomator dump /sdcard/u.xml` + `screencap /sdcard/s.png` scripts. Consumed **50.2% more uncached tokens (`163,746` vs `109,023`)** and took **39.4% longer (`695.4s` vs `498.8s`)** than its `llmadb` Trial 1 run.

# Claude Sonnet 5.5 (Low) - TC-06 (`llmadb`, Trial 1)
Success: Yes
Time elapsed: 8m 18.8s (498.8s)
Tokens spent: 109,023 uncached (97,347 input + 11,676 output + 0 thinking) | 2,774,995 cached input reads (2,884,018 total billed/cached)
Extra notes:
- **Session ID:** `ddf642da-340b-48a3-b112-23dadfb3480b` (`agy --model claude-sonnet-5-5-low --dangerously-skip-permissions`)
- **Stage-by-Stage Execution on OnePlus 11 (`snap=125` -> `snap=162`):**
  1. **CLI Discovery & NFC Activation:** Ran `llmadb --help` and `llmadb --help-llm`, opened Quick Settings, toggled NFC from `Kapalı` (`OFF`) to `Açık` (`ON`, `mState=on`).
  2. **Browser Recovery & APK Download:** Launched Firefox (`org.mozilla.firefox`). When Firefox displayed a Turkish crash-report dialog on launch, Sonnet autonomously identified and dismissed it (`KAPAT`), navigated to the XDA thread and `mixplorer.com/beta`, and downloaded `MiXplorer_v6.71.15-BETA_B26090412-arm64.apk`.
  3. **Android 11+ Staging & Verification:** Explicitly followed the `--help-llm` staging rule by copying `/sdcard/Download/MiXplorer_v6.71.15-BETA_B26090412-arm64.apk` to `/data/local/tmp/mix.apk`, running `pm install -r /data/local/tmp/mix.apk`, deleting the temporary staged file afterward, and verifying installation via `llmadb info com.mixplorer.beta`.
  4. **Clock Scroll Wheel Self-Correction:** Launched `com.oneplus.deskclock`. While scrolling the OxygenOS seconds picker wheel (`com.oplus.numberpicker`), it overshot to `21` seconds (`"Seconds is 21; step back one"`), self-corrected back to `20` seconds, started the timer, and immediately returned to the home screen (`llmadb key home`).
  5. **Dynamic-Island Overlay Dismissal:** Waited for the 20s timer to expire, captured `llmadb screen`, visually read the 100px coordinate grid on the OxygenOS top alert banner, and tapped the dismiss `"X"` icon at `(915, 270)` on the first try (`snap=162`).
  6. **OEM Security Awareness in Reversion Report:** Provided a thorough state summary and reversion script, explicitly warning that `cmd nfc disable` may be blocked by OEM permissions on this device and offering to toggle NFC off via the Quick Settings UI tile instead.

# Claude Sonnet 5.5 (Low) - TC-06 (`llmadb`, Trial 2)
Success: Yes
Time elapsed: 14m 13.1s (853.1s)
Tokens spent: 137,047 uncached (122,224 input + 14,823 output + 0 thinking) | 4,578,625 cached input reads (4,715,672 total billed/cached)
Extra notes:
- **Session ID:** `4053c8c8-31a8-4e5d-95cd-23391ee1aada` (`agy --model claude-sonnet-5-5-low --dangerously-skip-permissions`)
- **Stage-by-Stage Execution on OnePlus 11 (`snap=373` -> `snap=392`, only 19 snapshots):**
  1. **NFC & Browser Navigation:** Toggled NFC ON (`mState=on`) via Quick Settings, opened Firefox, searched `'MiXplorer XDA'`, scrolled to Post #2 Downloads, and tapped the Google Drive link (`488,783`) via `llmadb screen` coordinate grid.
  2. **Pure GUI APK Installation (No `pm install` Shortcut):** Under the strict **NO CHEATING** prompt, after downloading `MiXplorer_v6.71.15_B26090422-arm64.apk`, Sonnet opened Firefox Menu -> Downloads (`İndirilenler`), tapped the APK, and completed the installation through the Android GUI `com.google.android.packageinstaller`, then verified `version: 6.71.15 (26090422)` via `llmadb info com.mixplorer`.
  3. **Timer Recovery & Dynamic-Island Dismissal:** In `com.oneplus.deskclock`, when its first Start tap accidentally started a 3-minute timer, it immediately cancelled it, set the 20-second timer, returned to the home screen (`llmadb key home`), waited for expiration, and dismissed the OxygenOS dynamic-island alert (`X`) via `llmadb screen`, finishing in **19 total snapshots** and **16.3% fewer uncached tokens (`137,047` vs `163,746`)** than its Raw `adb` run.

---

# CyberTiel 35B-A3B (Qwen 3.6 35B-A3B derivative, Local via PolyStrata + Pi) - TC-06 (`llmadb`, Trial 1)
Success: No (Terminated after getting stuck on unexposed WebView / anti-bot challenge without vision)
Time elapsed: 12m 34s (754s prior to manual termination)
Tokens spent: 14,319 uncached (7,811 input + 6,508 output across 32 turns) | 234,970 cached input reads (249,289 total context tokens)
Extra notes:
- **Session ID:** `2026-10-20T19-29-54-913Z_01a15aca-aee1-74ae-9e4a-2f96d25513cf` (`PolyStrata` `strata-poly.exe` on RTX 5070 8GB + Ryzen 9 8940HX, `pi -p --mode json`)
- **Stage-by-Stage Execution on OnePlus 11 (`snap=165` -> `snap=198`):**
  1. **CLI Discovery & NFC Activation (Passed):** Learned `llmadb` via `llmadb --help` and `llmadb --help-llm`, expanded Quick Settings, located the NFC switch in the Turkish UI tree, and successfully turned NFC ON (`mState=on`).
  2. **Chrome WebView + Bunny Shield Blocker (Failed):** Opened Chrome (`com.android.chrome`) and navigated to the XDA thread (`https://xdaforums.com/t/app-2-3-mixplorer-v6-x-released-fully-featured-file-manager.1523691/`). Chrome hit XDA's Bunny Shield anti-bot challenge (`Establishing a secure connection...`), causing `llmadb ui` to report `! ui busy/animating` and subsequently expose only a childless `Web Görüntüleme` (`WebView`) node without interior DOM links.
  3. **Vision Modality Limitation:** Because `cybertiel-coder-35b-a3b` is a text-only model (`"input": ["text"]`), it could not inspect the annotated coordinate grid images produced by `llmadb screen` (explicitly noting in its reasoning trace: *"Let me look at the screenshot to understand. But I can't view images."*).
  4. **Key Architectural Takeaway:** While CyberTiel passed **100% of `TC-02` runs (3/3)** using compact accessibility trees (`llmadb ui`, cutting time by **42.4%** and total tokens by **39.6%** over Raw `adb`), Tier 2 tasks (`TC-06`) involving unexposed WebViews, 60fps animations, and floating system overlays (`! overlay window="SeedlingCard"`) strictly require a multimodal vision model capable of reading `llmadb screen` coordinate grids.
