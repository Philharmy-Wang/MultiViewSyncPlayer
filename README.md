# MultiViewSyncPlayer (MVSP)

Multi-camera synchronized video alignment and browsing tool · PySide6 · MIT

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**[中文文档](README_zh.md)**

---

## Features

- **One-click import**: Experiment / Date / Subject / View — four-level automatic archiving
- **Library browser**: Tree-view navigation; double-click a subject to load all views instantly
- **Synchronized playback**: Ring-buffer pre-decoding with millisecond-level accuracy
- **Auto layout**: Grid automatically adapts to the number of views (1–30+)
- **Session files**: `.mvsp.json` preserves offsets and annotations; portable across machines
- **Frame-offset fine-tuning**: ±1 / ±25 / ±250 frame adjustment, one-click lock
- **Annotation system**: Hotkey-based keyframe marking with exportable annotation lists
- **Waveform preview**: Audio waveform visualization for clapperboard-based alignment
- **Bilingual UI** (Chinese / English) · MIT License

## Screenshots

<!-- Placeholder: screenshots to be added -->

| Main Window | Import Wizard | Library Browser |
|---|---|---|
| ![Main Window](docs/screenshots/main_window.png) | ![Import Wizard](docs/screenshots/import_wizard.png) | ![Library](docs/screenshots/library_browser.png) |

## Quick Start

### Option A: Windows Portable (.exe) — No Python Required

1. Go to [Releases](https://github.com/Philharmy-Wang/MultiViewSyncPlayer/releases)
2. Download `MultiViewSyncPlayer-v0.2.1-win64.zip`
3. Extract anywhere → double-click `MultiViewSyncPlayer.exe`

Bundled with ffmpeg/ffprobe. Works on any Windows 10/11 machine without Python installed.

### Option B: One-click Script

**Windows:** Double-click `install.bat`

**macOS / Linux:**
```bash
bash install.sh
./run.sh
```

### Option C: Manual Install

```bash
git clone https://github.com/Philharmy-Wang/MultiViewSyncPlayer.git
cd MultiViewSyncPlayer
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Option D: CLI Arguments

```bash
# Open a specific session
python run.py --session my_session.mvsp.json

# Open with a library
python run.py --library /path/to/library_root

# Select backend
python run.py --backend mpv    # or opencv (default)
```

## Requirements

| Item | Requirement |
|---|---|
| OS | Windows 10/11, Ubuntu 20.04+, macOS 12+ |
| Python | >= 3.9 |
| Dependencies | PySide6 >= 6.6, OpenCV-Python >= 4.8, NumPy >= 1.24, SciPy >= 1.10 |
| Optional | mpv (libmpv) for high-performance backend |
| RAM | 8 GB+ recommended (16 GB for multi-4K) |

## Documentation

- [中文完整文档](README_zh.md) — features, setup guide, FAQ
- [Library Specification](docs/library_spec.md) — directory layout & metadata
- [Import Guide (中文)](docs/import_guide_zh.md) — step-by-step import tutorial

## License

[MIT](LICENSE)

## Acknowledgements

- [PySide6](https://www.qt.io/qt-for-python) — Qt for Python
- [OpenCV](https://opencv.org/) — video decoding
- [mpv](https://mpv.io/) — optional high-performance backend
- [ffmpeg](https://ffmpeg.org/) — bundled in Windows release for media processing
