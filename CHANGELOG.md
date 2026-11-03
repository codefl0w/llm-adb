# Changelog

## 2026-11-03

### Added
- Add screenshot output path routing via `-o` / `--output` and `LLMADB_SCREENSHOT_OUTDIR` env var
- Add multi-quick-tap support via `llmadb tap --count N [--interval MS]` (default 100ms)
- Add optional OCR module (`llmadb[ocr]`) and `llmadb screen --ocr` for text-only traversal
- Add Scenario 2 local agent benchmark results in docs/TEXT_MODELS_TESTS.md

### Fixed
- Support `@idx` prefix syntax in `llmadb tap` target resolution
- Fix stale orientation dimensions on `llmadb screen --no-ui` after device rotation

### Changed
- Update CLI help, README documentation, and non-idle/webview warning hints with `llmadb screen --ocr`, `screen -o`, and `tap --count`
- Bump version to `0.1.2`

## 2026-10-27

### Added
- Add `CHANGELOG.md` to track project changes
- Add regression tests for `type --clear` on 40+ character inputs and `E_UNSUPPORTED` exit code
- Auto-sync package version from git tag (`v*` / `V*`) in GitHub Actions release and PyPI workflows

### Fixed
- Fix `type --clear` leaving residual characters on inputs over 40 characters
- Fix `E_UNSUPPORTED` returning exit code `1` instead of documented exit code `2` (`EXIT_USAGE`)
- Fix PyPI workflow building static `0.1.0` version when triggered by new git tags

### Changed
- Use `Ctrl+A` (`input keycombination 113 29`) selection delete with dynamic `100+` backspace fallback in `type --clear`
- Bump version to `0.1.1`
