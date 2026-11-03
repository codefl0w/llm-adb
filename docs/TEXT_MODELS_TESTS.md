# Tiny Local LLM Autonomous Agent Benchmark — TC-02 & Scenario 2 (Android 17)

This benchmark evaluates **tiny, low-parameter local language models (1.7B - 35B)** on Android device automation from the [llm-adb Autonomous Agent Test Suite](TEST_SUITE.md):
- **Part 1:** TC-02 (Launcher Navigation & Web Search)
- **Part 2:** Scenario 2 (Busy-UI OCR Traversal & Multi-Tap Developer Unlock via `llmadb screen --ocr` and `llmadb tap --count`)

All models were evaluated in a **zero-context ("clueless") environment** using the Pi Coding Agent harness (`@earendil-works/pi-coding-agent`), running locally on consumer laptop hardware under identical test conditions on an **Android 17** emulator.

---

## 1. Benchmark Environment & Methodology

- **Target Device:** Google Pixel Android Virtual Device (`emulator-5554`), Android 17 (SDK 37), Stock AOSP / Pixel UI, `1080x2400` (420 DPI).
- **Inference Engines:**
  - `PolyStrata v0.1.45-poly.6` (Blackwell sm_120 tuned dynamic VRAM caching) for CyberTiel 35B-A3B.
  - `llama-server` (CUDA 13.4, build 11946) with Flash Attention (`-fa on`), Q8_0 quantized KV cache, and 100% GPU offload for Gemma 4, Spark, and LFM3.
- **Agent Harness:** Pi Coding Agent in non-interactive batch mode (`pi -p --no-context-files --tools powershell`).
- **Enforcement:** Hard **300-second (5-minute)** wall-clock limit per trial enforced via `taskkill /F /T`.
- **Reset Protocol:** Deterministic pre- and post-trial reset via `reset_device.ps1` (restores portrait, light theme, developer settings = 0, and closes background apps).
- **Models Evaluated:**
  1. **CyberTiel 35B-A3B** (`cybertiel`, 35B total MoE / A3B active, UD-Q4_K_XL, 22.4 GB)
  2. **Gemma 4 E4B Uncensored** (`gemma4`, 7.52B total params, Q4_K_M, 4.97 GB)
  3. **Spark X2.6 4B** (`spark`, 4.11B total params, Q4_K_M, 2.42 GB)
  4. **Liquid LFM3 1.7B QAD** (`lfm3`, 1.73B total params, Q4_0, 0.98 GB)

---

## 2. Scenario 2: Busy-UI OCR & Developer Unlock Benchmark Results

Task: Launch Android Settings, navigate to `About emulated device`, use `screen --ocr` to locate `Build number` despite the non-idle live Uptime counter, rapid-tap it 8 times to unlock Developer options, and navigate to `System > Developer options`.

### Aggregate Model Performance Matrix

| Model & Parameters | Toolchain | Completed Stages | Time Elapsed | Turns | In Tokens | Out Tokens | Total Tokens | `llmadb` Advantage vs. Raw `adb` |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **CyberTiel 35B-A3B** (35B) | **Raw `adb`** | 1.0 / 4 | `300.7s` (T/O) | 19 | 96,584 | 4,743 | 802,239 | *Baseline (catastrophic XML bloat, hung on idle state)* |
| **CyberTiel 35B-A3B** (35B) | **`llmadb`** | **3.5 / 4** | `300.8s` (T/O) | **26** | **7,954** | **10,737** | **218,522** | **-91.8% input tokens**, **+36.8% turns**, navigated, OCR'd & fired `tap --count 8` |
| **Gemma 4 E4B** (7.5B) | **Raw `adb`** | 1.0 / 4 | `300.7s` (T/O) | 25 | 16,365 | 19,794 | 279,966 | *Baseline (stalled searching raw XML bounds)* |
| **Gemma 4 E4B** (7.5B) | **`llmadb`** | **3.0 / 4** | `300.7s` (T/O) | **34** | **10,115** | **14,253** | **222,482** | **-38.2% input tokens**, **+36.0% turns (34 vs 25)**, fired `tap ... --count 8` |
| **Spark X2.6** (4.1B) | **Raw `adb`** | 0.5 / 4 | `300.7s` (T/O) | 37 | 16,554 | 17,445 | 562,327 | *Baseline (stuck writing PowerShell regex scripts for XML)* |
| **Spark X2.6** (4.1B) | **`llmadb`** | **1.0 / 4** | `301.1s` (T/O) | **23** | **7,625** | **15,114** | **206,739** | **-53.9% input tokens**, swipe loop on top-level menu |
| **Liquid LFM3** (1.7B) | **Raw `adb`** | 0.5 / 4 | `76.3s` | 41 | 38,742 | 11,551 | 537,980 | *Baseline (stuck on syntax hallucination: bad component)* |
| **Liquid LFM3** (1.7B) | **`llmadb`** | **1.0 / 4** | `300.9s` (T/O) | **18** | **17,120** | **6,378** | **127,115** | **-55.8% input tokens**, zero syntax errors via `--help-llm` |

---

## 3. Token Efficiency Comparison (Raw `adb` vs `llmadb`)

```text
Uncached Input Tokens Consumed
======================================================================
CyberTiel 35B [Raw adb] ████████████████████████████████  96,584 tokens
              [llmadb ] ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   7,954 tokens (-91.8%)

Gemma 4 E4B   [Raw adb] █████░░░░░░░░░░░░░░░░░░░░░░░░░░░  16,365 tokens
              [llmadb ] ███░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  10,115 tokens (-38.2%)

Spark 4B      [Raw adb] █████░░░░░░░░░░░░░░░░░░░░░░░░░░░  16,554 tokens
              [llmadb ] ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   7,625 tokens (-53.9%)

Liquid LFM3   [Raw adb] ████████████░░░░░░░░░░░░░░░░░░░░  38,742 tokens
              [llmadb ] █████░░░░░░░░░░░░░░░░░░░░░░░░░░░  17,120 tokens (-55.8%)
======================================================================
Average Input Tokens: Raw adb = 42,061 tokens | llmadb = 10,703 tokens (-74.6%)
```

---

## 4. Key Architectural & Behavioral Insights

1. **Elimination of Catastrophic XML Bloat (-74.6% Average Uncached Input Tokens):**
   Raw `adb` forces models to read full, uncompressed `uiautomator dump` XML trees (30KB–50KB each). Under raw `adb`, CyberTiel consumed an astounding **96,584 input tokens** in just 19 turns. `llmadb ui` and `llmadb screen --ocr` reduced this to **7,954 tokens (-91.8% reduction)**, preventing memory saturation and reasoning degradation.
2. **`screen --ocr` Resolves the Non-Idle / Busy Screen Deadlock:**
   The live Uptime counter on the Android 17 `About emulated device` screen causes `uiautomator` to repeatedly fail with `could not get idle state`. Under raw `adb`, all 4 models were blocked. Under `llmadb`, both CyberTiel and Gemma 4 immediately followed the error hint and invoked `llmadb screen --ocr`, successfully extracting the visual text and coordinates of "Build number".
3. **Multi-Tap Command (`llmadb tap ... --count N`) Proven in Live Agent Context:**
   Unlocking developer options requires tapping the build number 7–8 times in rapid succession. Under raw `adb`, models attempt individual sequential taps that trigger slow UI dumps and miss the rapid-tap timing window. Both CyberTiel (`llmadb tap 208,2079 --count 8 --interval 120`) and Gemma 4 (`llmadb tap 15 --count 8`) leveraged the newly implemented `--count` flag directly from discovery.
4. **Autonomous Navigation vs. Parent Menu Loops (Sub-4B vs. 7B+ Models):**
   A notable behavioral contrast emerged between model parameter tiers: Spark 4B and LFM3 1.7B read the task ("Scroll down to Build number") and repeatedly swiped up/down on the *top-level* Settings list, never tapping the "About emulated device" container. In contrast, Gemma 4 (7.5B) and CyberTiel (35B) correctly identified the container element, tapped into the sub-screen, and performed OCR on the child view.
