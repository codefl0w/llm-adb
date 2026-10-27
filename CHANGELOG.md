# Changelog

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
