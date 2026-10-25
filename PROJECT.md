# llm-adb: Architecture and Implementation Plan

## 1. Purpose and principles

llm-adb (CLI binary: llmadb) is a CLI wrapper around adb whose consumer is an LLM agent, not a human. Goal: replace multi-call discovery and screenshot-guess loops with single calls that return compact, deterministic, pre-digested output.

Principles:
1. One call, one answer. Batch device-side work into a single `adb` invocation.
2. Token cost is the primary metric. Output is line-based text; JSON only for nested objects.
3. Never make the model reason about coordinates, DPI, escaping, or component names.
4. Passthrough is transparent. Unknown subcommands behave exactly like adb.
5. Failures are structured, with a `hint`, so the model can self-correct.
6. Parse bytes, never decoded text, to avoid encoding corruption.

Non-goals (v1): MCP server, screen recording, on-device helper app, multi-display, iOS.

## 2. Technology and packaging

- Python 3.9+, stdlib plus Pillow. Pillow is imported lazily, only by `screen`.
- `pyproject.toml`, console entry point `llmadb`. Install via `pipx install .`.
- Subprocess calls with argument lists, never `shell=True`. Binary-safe I/O (`bytes`).
- On startup: `sys.stdout.reconfigure(encoding="utf-8")` and the same for stderr (Windows consoles default to cp1252).
- Single external dependency at runtime: `adb` on PATH, overridable with `LLMADB_ADB`.

## 3. Module layout

```
llmadb/
  cli.py          argument dispatch, owned-vs-passthrough decision
  adb.py          Adb runner: run(args, serial, timeout, binary) -> Result(stdout: bytes, stderr: bytes, code: int)
  device.py       device listing, selection, state validation
  shellbatch.py   run N shell commands in one call with delimiters, return dict
  errors.py       LlmadbError(code, message, hint), exit codes
  cache.py        per-serial cache dir: snapshots, screenshots, marks
  uitree.py       XML parse, filter, merge, index, format; Snapshot dataclass
  annotate.py     Pillow: downscale, boxes, labels, grid
  commands/
    devices.py hardware.py status.py ui.py screen.py tap.py input.py
    current.py rotate.py cache_cmd.py apps.py info.py launch.py log.py waitfor.py
tests/
  test_*.py       unit tests for CLI, UI tree reduction, batching, commands
```

## 4. Global CLI contract

### 4.1 Device selection (resolved on every call, no session cache)
Precedence: `--device/-s`, `LLMADB_SERIAL`, `ANDROID_SERIAL`, single connected device, otherwise error `E_MULTI_DEVICE` listing serials. Cost of `adb devices` is negligible, so caching is not worth the staleness risk.

State validation happens during selection: `unauthorized`, `offline`, `no permissions` raise `E_DEVICE_STATE` with a hint.

### 4.2 Passthrough
If the first non-option argument is not an owned subcommand, exec `adb [-s SERIAL] <args...>` with inherited stdio and return adb's exit code unchanged. Do not inject `-s` if the user supplied one, or for server-level commands (`start-server`, `kill-server`, `version`, `connect`, `disconnect`, `pair`). Escape hatch for shadowed names: `llmadb -- devices` runs raw `adb devices`.

### 4.3 Output and errors
- stdout: data only. stderr: errors only.
- Error line format: `error: <CODE> <message> | hint: <hint>`.
- Exit codes: 0 ok, 1 generic, 2 usage, 3 device selection, 4 device state, 5 timeout, 6 element not found, 7 secure/blank screen, 8 adb failure.
- Strip adb noise (`* daemon started successfully`, CRLF, trailing newlines) from owned commands.
- Global flags: `--max-lines N` (appends `[truncated: M more lines]`), `--timeout S`.
- `--help-llm` prints a short usage block intended for agent instruction files.

## 5. Command specifications

### 5.1 devices
- Source: `adb devices -l`.
- Output (TSV, one device per line): `serial<TAB>state<TAB>model<TAB>transport`.
- Empty result: `no devices` with exit 3 and hint "check USB, enable USB debugging".

### 5.2 hardware
One batched `adb shell` call gathering:
- `getprop`: `ro.product.manufacturer`, `ro.product.model`, `ro.build.version.release`, `ro.build.version.sdk`, `ro.build.version.security_patch`, `ro.build.fingerprint`, `ro.product.cpu.abilist`, `ro.boot.hardware`, `ro.board.platform`
- `wm size` (physical and override), `wm density` (physical and override)
- `/proc/meminfo` (MemTotal, MemAvailable)
- `df /data` (size, used)
- `getenforce`
- root probe: `su -c id` with 3 s timeout (report `root: yes/no/unknown`)

Output: Plaintext `key: value` lines by default (token-efficient). Optional `--json` flag emits structured JSON object. Resolution reports both `physical` and `effective`, plus `dpi`.

### 5.3 ui
Pipeline:
1. `adb exec-out uiautomator dump /dev/tty` (no device temp file). The output has a trailing `UI hierarchy dumped to: /dev/tty` after `</hierarchy>`; truncate at the closing tag.
2. Fallback if empty or errored: `uiautomator dump /sdcard/llmadb.xml` then `exec-out cat`, then delete.
3. Retry up to 3 times, 300 ms apart, on `null root node` or empty output.
4. Parse bytes with `ElementTree.fromstring(bytes)`.
5. Filter, merge, index, format (section 6).
6. Store as Snapshot in cache; print header including snapshot id.

Flags: `--full` (no truncation), `--bounds` (full bounds instead of center), `--compressed` (pass `--compressed` to uiautomator; test coverage loss before making it default), `--raw` (raw XML, debugging only).

Header: `screen WxH app=<pkg> rot=<0-3> snap=<n>`. If zero nodes survive or the tree is one empty node, emit `E_SECURE_OR_EMPTY` hint "FLAG_SECURE screen or non-accessible UI; use `screen --grid`".

### 5.4 screen
Pipeline:
1. `adb exec-out screencap -p` into memory. Validate PNG signature (some devices prepend warnings).
2. Unless `--no-ui`, take a `ui` snapshot (so indices match the image).
3. Downscale to a maximum long edge (default 1280, `--max-edge N`). Compute scale factor from actual screenshot size versus tree coordinate space.
4. Annotate in final-resolution space (bounds scaled first, then drawn), so labels remain crisp. This supersedes the earlier "annotate then downscale" suggestion.
5. Write PNG to cache; print one line: `path=<file> size=WxH scale=<f> snap=<n> elements=<n>`.

Annotation: numbered boxes per element, label at top-left inside the box, contrasting outline and fill, collision avoidance (shift label by label height until clear, fall back to box center). `--grid N` draws gridlines every N device pixels with edge labels in device coordinates, for custom-drawn UIs. `--raw` skips annotation. `--region x1,y1,x2,y2` and `--element N` crop and upscale.

Blank-screen detection: if the image is uniformly black (`getextrema`) and the tree is empty, exit 7 with a secure-screen message instead of returning the image.

### 5.5 tap
Targets: `tap N` (index from latest snapshot), `tap --text "X"`, `tap --id <short-id>`, `tap x,y` (device pixels, always device space, never image space).
- Resolution against latest cached snapshot; `--snap N` rejects if snapshot differs (guards against stale indices).
- Text matching: exact first, then case-insensitive contains. Ambiguity returns `E_AMBIGUOUS` with candidate indices. No match returns exit 6 with the closest labels.
- Execute `input tap x y` where x,y is the element center, or `input swipe x y x y <ms>` when `--hold [MS]` is passed (default 500 ms).
- Post-action (default on): wait for UI to settle, then print the new `ui` output. Settle algorithm: sleep 300 ms, dump, compare hash with previous dump, repeat until two consecutive equal or `--settle-timeout` (default 2 s). `--no-ui` disables. Optionally print a diff (added/removed rows) when `--diff` is set; make this the default once stable.

### 5.6 input set
- `type "text"`: ASCII via `input text`, escaping spaces (`%s`), shell metacharacters, quotes, `%`. Non-ASCII: v1 returns `E_UNSUPPORTED` with hint; v2 supports ADBKeyBoard broadcast if installed. Flags: `--enter`, `--clear` (select all, delete).
- `swipe up|down|left|right [--dist 0.5] [--dur 300]`: coordinates computed from effective screen size, with edge margins to avoid system gestures. `swipe x1,y1 x2,y2` for explicit.
- `key <name>`: map `home back enter tab menu power volup voldown recents delete` and numeric codes to `input keyevent`.
- `wait-for --text X | --id Y | --gone X [--timeout 10]`: poll `ui` at 500 ms; exit 5 on timeout.
- All of the above share the post-action state behavior of `tap`.

### 5.7 current
Batched: focused window (`dumpsys window | grep mCurrentFocus`), resumed activity (`dumpsys activity activities | grep -E "ResumedActivity"`), `dumpsys input_method | grep mInputShown`, rotation (`dumpsys window displays` or `settings get system user_rotation`). Multiple parsing strategies per Android version; first success wins. Output: `pkg/activity rot=0 keyboard=hidden`.

### 5.8 list apps
- Command: `llmadb list apps [user|system|vendor|all] [--grep S] [--disabled] [--enabled]`. Default `user`.
- Source: `pm list packages -f` (path included), plus `-3` and `-s` sets for reliable user/system split.
- Strip `package:`. Parse each line by splitting on the last `=` (paths may contain `=`).
- Classify by path prefix: `/data/app` user; `/system/`, `/system_ext/` system; `/vendor/`, `/odm/` vendor; `/product/` product. Packages in `-s` set with `/data/app` path are updated system apps; mark `system*`.
- Output for `all`: section headers (`[user]`, `[system]`, `[vendor]`, `[product]`) followed by bare package names, so the category is not repeated per line.

### 5.9 info
`info <package>`: condensed `dumpsys package <pkg>`: version name/code, target and min SDK, debuggable, installer, first/last update, granted and denied runtime permissions (names shortened), enabled state, launcher activity, running state (`pidof`).

### 5.10 launch
`launch <pkg>`: resolve with `cmd package resolve-activity --brief -c android.intent.category.LAUNCHER <pkg>`, then `am start -n <component>`. Fallback: `monkey -p <pkg> -c android.intent.category.LAUNCHER 1`. Siblings: `stop` (`am force-stop`), `clear` (`pm clear`). Returns `current` output after launch.

### 5.11 log
`log [--pkg P] [--level W] [-n 200] [--since-mark] [--crash]`
- PID resolution via `pidof`; filter with `logcat --pid`. Use `logcat -d -v threadtime`.
- Collapse consecutive duplicate lines (`... x37`). Drop timestamps beyond seconds unless `--full`.
- `mark`: store device time (`date +"%m-%d %H:%M:%S.000"`) in cache; `--since-mark` uses `logcat -T`.
- `--crash`: `logcat -b crash -d`.

## 6. UI tree reduction specification

Input: uiautomator XML. Output: ordered list of elements.

Inclusion (any):
- non-empty `text` or `content-desc`
- `clickable`, `long-clickable`, `checkable`, or `scrollable` is true
- class in {Button, ImageButton, EditText, Switch, CheckBox, RadioButton, ToggleButton, SeekBar, Spinner, TabWidget, ProgressBar}

Exclusions: zero-area bounds, bounds fully outside screen, `visible-to-user=false` where present.

Merging: parent and sole child with identical bounds merge into one row. A clickable container with no own label takes the first descendant text.

Class-to-type map: TextView `text`, Button/ImageButton `button`, EditText `input`, CheckBox `check`, Switch/ToggleButton `switch`, RadioButton `radio`, ImageView `image`, ProgressBar `progress`, ScrollView/RecyclerView/ListView `scroll`, others `view`.

Row format:
```
<idx> <type> "<label>" id=<short-id> [flags] @<cx>,<cy>
```
- `short-id`: resource-id with `package:id/` stripped when the package equals the foreground package; omitted if empty.
- label: `text`, else `content-desc`; escape `"` and newlines; truncate at 120 chars with an ellipsis unless `--full`.
- Flags, only when non-default: `-enabled`, `checked`, `focused`, `password`, `scroll`, `!clickable`. `!clickable` is emitted only for types that should be interactive (button, input, switch, check, radio) when the tree reports `clickable=false`; it signals the tree flag is unreliable, not that the tap will fail.
- Indices assigned in document order starting at 1, per snapshot.

Target for the One UI sample dump: about 150 tokens, 4 rows.

## 7. Cache

Location: user cache dir, `llmadb/<serial>/`. Contents: `snap.json` (latest Snapshot: id, timestamp, screen size, rotation, elements with bounds and center, content hash), `screens/<snap>.png`, `mark`. Prune screenshots older than 1 hour or beyond 20 files. Snapshot ids are monotonically increasing integers.

## 8. Error codes

`E_NO_DEVICE`, `E_MULTI_DEVICE`, `E_DEVICE_STATE` (unauthorized: "accept RSA prompt on device"; offline: "replug or `adb kill-server`"), `E_TIMEOUT`, `E_NOT_FOUND`, `E_AMBIGUOUS`, `E_SECURE_OR_EMPTY`, `E_UNSUPPORTED`, `E_ADB` (carries adb stderr). Every error carries a hint.

## 9. Testing

Unit (no device):
- `uitree`: fixtures from real dumps, starting with the One UI Turkish sample. Assert row output, index stability, mojibake absence, merge rules.
- `shellbatch` delimiter parsing, `apps` classification (paths containing `=`), input escaping table, error mapping, selection precedence.
- Fake `Adb` runner returning canned bytes for command-level tests.

Integration (real devices, manual matrix): emulator (stock), Pixel (AOSP-like), One UI device, a device with a non-ASCII locale, one with a secure screen (banking app or password field), one running Android 9 and one 14+ for `current` parsing. Record dumps and getprop output as new fixtures when a device exposes a parsing difference.

Token acceptance: `ui` on fixture under 200 tokens, `hardware` under 150, `devices` under 40.

## 10. Milestones

| Phase | Scope | Acceptance |
|---|---|---|
| 0 | Skeleton, `Adb` runner, device selection, passthrough, error model, `devices` | Passthrough byte-identical to adb for `install`, `shell`, `logcat`; exit codes preserved |
| 1 | `hardware`, `ui` (parsed), `tap`, `screen --annotate` and `--grid`, snapshot cache | Agent completes a 3-screen navigation on a real device with no raw adb calls |
| 2 | `key`, `swipe`, `type` (ASCII), `wait-for`, post-action settle and diff, `current` | Login-form flow runs end to end with one call per action |
| 3 | `list apps`, `info`, `launch`/`stop`/`clear`, `log` with `mark` and `--crash` | Crash reproduction loop: mark, action, `log --crash` |
| 4 | `--help-llm`, README, non-ASCII `type`, performance pass, release | Install via pipx on Windows and Linux; fixtures cover 5+ devices |

## 11. Risks and open decisions

- uiautomator latency (1-2 s) and failures during animations or when another accessibility client is active. Mitigation: retries, `--compressed` experiment; fallback plan is an on-device helper (deferred).
- Unreliable `clickable` flags (observed on Samsung). Mitigation: class-based inclusion, `!clickable` flag, tap-by-center.
- Compose and WebView content may be missing from the tree. Mitigation: `screen --grid`, coordinate tap.
- `dumpsys` output varies across Android versions. Mitigation: multiple parsers, fixture per version.
- Stale indices after UI changes. Mitigation: snapshot ids, `--snap`, post-action snapshots refresh the cache automatically.
- Open: default for post-action output (full list versus diff); whether `--compressed` becomes default; ADBKeyBoard dependency for non-ASCII input; project name collision check on PyPI before release.