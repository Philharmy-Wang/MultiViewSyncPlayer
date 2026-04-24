# MultiViewSyncPlayer (MVSP)

Multi-view video synchronization, alignment & browsing tool — built with PySide6.

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**[中文文档](README_zh.md)** | **[Import Guide](docs/import_guide_zh.md)** | **[Library Spec](docs/library_spec.md)**

---

## Features

- **Media Library** — 4-level structure (Experiment / Date / Subject / View) with tree navigation
- **Import Wizard** — auto-detect view directions, copy/hardlink/move modes
- **Auto Layout** — grid auto-resizes to match loaded view count (1–30+)
- **Sync Playback** — ring-buffer pre-decode for smooth frame-accurate playback
- **Session Files** — `.mvsp.json` preserves offsets, markers & library references
- **Frame-Level Alignment** — per-view offset with 1/25/250 frame stepping
- **Waveform Preview** — audio waveform visualization for clap-board alignment
- **Cross-Platform** — Windows / macOS / Linux

## Quick Start

### One-Click Install (Recommended)

**Windows:** double-click `install.bat`

**macOS / Linux:**
```bash
bash install.sh
./run.sh
```

### Manual Install

```bash
git clone https://github.com/Philharmy-Wang/MultiViewSyncPlayer.git
cd MultiViewSyncPlayer
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

### CLI Options

```bash
python run.py --session session.mvsp.json   # open saved session
python run.py --library /path/to/library     # open media library on startup
python run.py --backend mpv                  # use mpv backend (optional)
```

## Keyboard Shortcuts

| Action | Key |
|---|---|
| Play / Pause | `Space` |
| Step ±1 / ±25 / ±250 frames | `D/A` `W/S` `E/Q` |
| Adjust offset (selected view) | `←/→` ±1, `Shift+←/→` ±25, `Ctrl+←/→` ±250 |
| Mark frame | `M` |
| Reset offsets | `R` |
| Open session | `Ctrl+O` |
| Save session | `Ctrl+S` |
| Import to library | `Ctrl+I` |
| Toggle library dock | `Ctrl+L` |
| Fullscreen | `F` / `F11` |

## Requirements

- Python >= 3.9
- PySide6 >= 6.6, OpenCV-Python >= 4.8, NumPy >= 1.24, SciPy >= 1.10
- 8 GB+ RAM (16 GB for multi-4K)

## Documentation

- [中文完整文档](README_zh.md) — features, setup guide, FAQ
- [Library Specification](docs/library_spec.md) — directory layout & metadata
- [Import Guide (中文)](docs/import_guide_zh.md) — step-by-step import tutorial

## License

[MIT](LICENSE)
