# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-04-24

### Added

- Media library with Experiment / Date / Subject / View four-level directory structure
- Import wizard (5 pages): metadata → sources → view mapping → review → execute
  - Auto-detect view directions from Chinese/English filenames (前/后/左/右/top/bottom...)
  - Copy / hardlink / move import modes with conflict resolution
- Left dock `LibraryBrowser` with tree navigation, fuzzy search & context menus
- Auto layout: grid auto-resizes to match loaded subject's view count (1–30+)
- Session I/O module (`session_io.py`) — extracted from main_window for reuse
- Optional `library_ref` field in `.mvsp.json` session files for library round-trip
- CLI `--library` option to open a media library on startup
- File menu "Import to Library" action with `Ctrl+I` shortcut
- `LibraryBrowserDock.locate()` to navigate tree to a specific subject
- `detect_library_ref()` to auto-detect if session videos share a library subject
- One-click install scripts (`install.bat` / `install.sh`)
- Rewritten Chinese README (`README_zh.md`) with full setup guide and FAQ
- English README.md with quick-start and shortcuts reference
- Import tutorial (`docs/import_guide_zh.md`)

### Changed

- Session `.mvsp.json` format gains optional `library_ref` field (backward-compatible)
- Save/load refactored from inline `main_window` logic into `session_io` module
- `SyncController.load()` is now dead code — all loading goes through `session_io.load_session()`
- Version bumped to 0.2.0

### Tests

- 70 tests passing (was 61): +9 session_io tests covering roundtrip, validation, unicode, library_ref

## [0.1.0] - 2026-01-26

### Added

- Multi-view synchronized video player with configurable NxM grid layout
- Per-view frame offset adjustment with sync lock
- OpenCV and mpv backend support
- Session save/load (`.mvsp.json`) with metadata and layout persistence
- Global toolbar with playback controls and speed adjustment
- Waveform preview for audio-assisted alignment
- Marker system for key frame annotation
- Project template system for batch video loading by naming patterns
- Launch dialog with layout presets
- Dark theme UI
- Metadata bar with inline editing
