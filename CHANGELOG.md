# Changelog

## 2026-10-27

### Added
- Add `CHANGELOG.md` to track project changes
- Add regression tests for `type --clear` on 40+ character inputs and `E_UNSUPPORTED` exit code

### Fixed
- Fix `type --clear` leaving residual characters on inputs over 40 characters
- Fix `E_UNSUPPORTED` returning exit code `1` instead of documented exit code `2` (`EXIT_USAGE`)

### Changed
- Use `Ctrl+A` (`input keycombination 113 29`) selection delete with dynamic `100+` backspace fallback in `type --clear`
