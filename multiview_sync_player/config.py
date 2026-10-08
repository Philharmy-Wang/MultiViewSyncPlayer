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
BACKEND_MODE = "Strict"
BACKEND_REQUESTED = "auto"
BACKEND_REASON = ""

# MPV remains an explicitly selected Preview backend until its displayed-frame
# acknowledgement passes the exact-frame gate.  Keeping the hwdec choice
# configurable lets Linux validation compare auto and NVDEC without changing
# the correctness policy or hard-coding a host-specific driver assumption.
MPV_HWDEC = os.environ.get("MVSP_MPV_HWDEC", "auto").strip().lower()
if MPV_HWDEC not in {"auto", "nvdec", "no"}:
    MPV_HWDEC = "auto"
MPV_VO = os.environ.get("MVSP_MPV_VO", "gpu-next").strip() or "gpu-next"

# ---- FFmpeg auto-detect ----


def _find_ffmpeg() -> str:
    """Locate ffmpeg executable."""
    # 0. PyInstaller frozen bundle (_internal/bin/ffmpeg.exe)
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
        candidate = base / "bin" / "ffmpeg.exe"
        if candidate.is_file():
            return str(candidate)
    # 1. Windows source checkout, using the same tools as the portable build.
    if sys.platform == "win32":
        candidate = Path(__file__).resolve().parents[1] / "packaging" / "bin" / "ffmpeg.exe"
        if candidate.is_file():
            return str(candidate)
    # 2. System PATH
    p = shutil.which("ffmpeg")
    if p:
        return p
    # 3. imageio_ffmpeg package
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    # 4. Common conda / system locations
    for candidate in [
        r"C:\ProgramData\miniconda3\Library\bin\ffmpeg.exe",
        r"C:\ProgramData\miniconda3\Scripts\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]:
        if os.path.isfile(candidate):
            return candidate
    return "ffmpeg"  # fallback, may fail


FFMPEG_PATH = _find_ffmpeg()


def _find_ffprobe() -> str:
    """Locate ffprobe executable (used to build keyframe indexes)."""
    # 0. Next to the resolved ffmpeg (bundle / portable layout)
    if FFMPEG_PATH and os.path.isfile(FFMPEG_PATH):
        candidate = Path(FFMPEG_PATH).with_name("ffprobe.exe")
        if candidate.is_file():
            return str(candidate)
    # 1. Source tree packaging/bin (dev checkout)
    candidate = Path(__file__).resolve().parents[1] / "packaging" / "bin" / "ffprobe.exe"
    if candidate.is_file():
        return str(candidate)
    # 2. System PATH
    p = shutil.which("ffprobe")
    if p:
        return p
    return ""


FFPROBE_PATH = _find_ffprobe()

# ---- OpenCV backend params ----
DECODE_TARGET_WIDTH = 720
# OpenCV/FFmpeg otherwise defaults to all logical CPUs per VideoCapture.  Six
# views then create ~96 codec workers on a 16-thread machine.  Four workers per
# view was the best balanced Windows result for the mixed 720p/1440p workload.
DECODE_THREADS_PER_VIEW = max(1, int(os.environ.get("MVSP_DECODE_THREADS", "4")))
OPENCV_INTERNAL_THREADS = max(
    1, int(os.environ.get("MVSP_OPENCV_THREADS", "4")))
DECODE_BUFFER_SIZE = 60   # ring buffer prefetch size
RECENT_FRAME_CACHE_SIZE = 64
SEQUENTIAL_STEP_WINDOW = 16
SEEK_TIMEOUT_MS = 2000
# Session opening may need more time for six cold decoders. This only applies
# to the first seek after an automatic session load; normal seeks stay at the
# short barrier timeout above.
INITIAL_SESSION_LOAD_TIMEOUT_MS = 20000
# After a keyframe-anchored random seek, the last N frames before the
# target are decoded with full read+cache; the bulk is grab()-skipped.
SEEK_KEYFRAME_DECODE_MARGIN = 8

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
