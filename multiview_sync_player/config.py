"""
multiview_sync_player.config — Default constants

Color scheme, playback speed, decode params, backend settings.
"""

import shutil
import os
import sys
from pathlib import Path

from PySide6.QtGui import QColor

# ---- Cross-platform config directory ----
if sys.platform == "win32":
    _CONFIG_DIR = Path(os.environ.get(
        "APPDATA", Path.home() / "AppData" / "Roaming")) / "MultiViewSyncPlayer"
else:
    _CONFIG_DIR = Path.home() / ".config" / "MultiViewSyncPlayer"

PLAYER_CONFIG_PATH = _CONFIG_DIR / "config.json"

# ---- Backend selection ----
# "opencv" = OpenCV multi-threaded decode (default, no DLL needed)
# "mpv" = mpv GPU hardware decode (requires libmpv DLL)
BACKEND = "opencv"

# ---- FFmpeg auto-detect ----


def _find_ffmpeg() -> str:
    """Locate ffmpeg executable."""
    # 1. System PATH
    p = shutil.which("ffmpeg")
    if p:
        return p
    # 2. imageio_ffmpeg package
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    # 3. Common conda / system locations
    for candidate in [
        r"C:\ProgramData\miniconda3\Library\bin\ffmpeg.exe",
        r"C:\ProgramData\miniconda3\Scripts\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]:
        if os.path.isfile(candidate):
            return candidate
    return "ffmpeg"  # fallback, may fail


FFMPEG_PATH = _find_ffmpeg()

# ---- OpenCV backend params ----
DECODE_TARGET_WIDTH = 720
DECODE_BUFFER_SIZE = 60   # ring buffer prefetch size

# ---- Color scheme (DaVinci Resolve style) ----
COLOR_WINDOW_BG = "#1e1e1e"
COLOR_PANEL_BG = "#2b2b2b"
COLOR_BORDER = "#3c3c3c"
COLOR_TEXT = "#e0e0e0"
COLOR_TEXT_DIM = "#888888"
COLOR_ACCENT = "#4A9EFF"
COLOR_POSITIVE = "#4CAF50"
COLOR_NEGATIVE = "#F44336"
COLOR_BTN_NORMAL = "#3c3c3c"
COLOR_BTN_HOVER = "#4c4c4c"
COLOR_BTN_PRESSED = "#2a2a2a"

# ---- View color palette (auto-assigned by slot order) ----
VIEW_COLOR_PALETTE = [
    QColor(66, 165, 245),   # Blue
    QColor(102, 187, 106),  # Green
    QColor(255, 167, 38),   # Orange
    QColor(239, 83, 80),    # Red
    QColor(171, 71, 188),   # Purple
    QColor(38, 198, 218),   # Cyan
    QColor(255, 235, 59),   # Yellow
    QColor(139, 195, 74),   # Light Green
    QColor(255, 112, 67),   # Deep Orange
]

DEFAULT_VIEW_COLOR = QColor(200, 200, 200)

# ---- View header strip colors (hex strings for QSS) ----
VIEW_COLORS = [
    "#FF6B6B",  # 珊瑚红
    "#4ECDC4",  # 青绿
    "#FFE66D",  # 明黄
    "#95E1D3",  # 薄荷
    "#C7A2E4",  # 淡紫
    "#FFB6C1",  # 浅粉
    "#87CEEB",  # 天蓝
    "#F4A460",  # 沙棕
    "#A8D8EA",  # 雾蓝
]

_view_color_cache = {}


def get_view_color(view_name: str) -> QColor:
    """Get a consistent color for a view name from the palette."""
    if view_name not in _view_color_cache:
        idx = len(_view_color_cache) % len(VIEW_COLOR_PALETTE)
        _view_color_cache[view_name] = VIEW_COLOR_PALETTE[idx]
    return _view_color_cache[view_name]


# ---- Default grid layout ----
DEFAULT_GRID_ROWS = 2
DEFAULT_GRID_COLS = 3

# ---- Playback speed ----
SPEED_STEPS = [0.25, 0.5, 1.0, 2.0, 4.0]

# ---- Default FPS ----
DEFAULT_FPS = 25.0
