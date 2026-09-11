"""
multiview_sync_player.video_cell — Single video cell widget

Dual backend support:
  - OpenCV ring-buffer prefetch decode (default, smooth playback)
  - mpv GPU decode (optional, requires DLL)

Contains video display + info overlay + progress bar + control buttons
+ audio waveform bar + sync lock.
Supports double-click to select video file.
"""

import collections
import os
import subprocess
from pathlib import Path
from time import perf_counter

import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QSizePolicy, QFileDialog, QFrame, QApplication,
)
from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QRect, QPoint, QMimeData, QByteArray,
)
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QFont, QPolygon, QCursor, QDrag,
)

from .config import (
    COLOR_BORDER, COLOR_TEXT, COLOR_TEXT_DIM, COLOR_ACCENT,
    COLOR_POSITIVE, COLOR_NEGATIVE, COLOR_PANEL_BG,
    DEFAULT_FPS, DECODE_TARGET_WIDTH, FFMPEG_PATH,
    get_view_color,
)
from . import config as cfg
from .styles import CELL_BTN_STYLE, PROGRESS_SLIDER_STYLE
from .waveform_bar import WaveformBar
from .video_decoder import PrefetchDecoder
from .process_utils import popen_hidden
from .backend import frame_to_time


def _distribution(values):
    samples = sorted(values)
    if not samples:
        return {"median": 0.0, "p95": 0.0, "max": 0.0, "samples": 0}
    at = lambda fraction: samples[min(
        len(samples) - 1, int((len(samples) - 1) * fraction))]
    return {
        "median": round(at(0.5), 3), "p95": round(at(0.95), 3),
        "max": round(samples[-1], 3), "samples": len(samples),
    }


class AudioLoadThread(QThread):
    """Extract and reduce one audio stream without blocking Qt's GUI thread."""

    audio_ready = Signal(object, int, bool, str)

    def __init__(self, video_path: str, wav_path: Path, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.wav_path = wav_path
        self._process = None

    def run(self):
        try:
            cmd = [FFMPEG_PATH, "-y", "-i", self.video_path,
                   "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                   str(self.wav_path)]
            self._process = popen_hidden(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while self._process.poll() is None:
                if self.isInterruptionRequested():
                    self._process.terminate()
                    self._process.wait(timeout=3)
                    self.audio_ready.emit(None, 0, False, "cancelled")
                    return
                self.msleep(50)
            if self._process.returncode != 0 or not self.wav_path.is_file():
                self.audio_ready.emit(None, 0, False, "ffmpeg extraction failed")
                return
            import scipy.io.wavfile as wavfile
            sr, data = wavfile.read(str(self.wav_path))
            if data.ndim > 1:
                data = data[:, 0]
            data = data.astype(np.float64)
            mx = np.max(np.abs(data)) if len(data) else 0
            if mx > 0:
                data = data / mx
            spp = 1600
            n = max(1, len(data) // spp)
            env = np.zeros(n)
            for index in range(n):
                chunk = data[index * spp:(index + 1) * spp]
                env[index] = np.max(np.abs(chunk)) if len(chunk) else 0
            self.audio_ready.emit(env, sr, True, "")
        except Exception as exc:
            self.audio_ready.emit(None, 0, False, str(exc))
        finally:
            self._process = None


# ==================== Draggable color header ====================

class DraggableHeader(QFrame):
    """8px color strip at the top of each grid cell. Drag to swap cells."""

    def __init__(self, parent_cell, color: str):
        super().__init__(parent_cell)
        self._parent_cell = parent_cell
        self._color = color
        self._drag_start = None
        self.setFixedHeight(8)
        self.setCursor(Qt.OpenHandCursor)
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background-color: {color};")

    def set_color(self, color: str):
        self._color = color
        self.setStyleSheet(f"background-color: {color};")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is None or not (event.buttons() & Qt.LeftButton):
            return
        delta = event.position().toPoint() - self._drag_start
        if delta.manhattanLength() < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mime = QMimeData()
        r, c = self._parent_cell.grid_pos
        mime.setData("application/x-mvsp-cell-index",
                     f"{r},{c}".encode())
        drag.setMimeData(mime)

        pixmap = self._parent_cell.grab()
        scaled = pixmap.scaled(160, 90, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
        drag.setPixmap(scaled)
        drag.setHotSpot(QPoint(min(self._drag_start.x(), scaled.width()),
                               min(self._drag_start.y(), scaled.height())))

        self._drag_start = None
        drag.exec(Qt.MoveAction)
        self.setCursor(Qt.OpenHandCursor)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


# ==================== Info overlay ====================

class OverlayWidget(QWidget):
    """Transparent overlay: view name / frame / time / offset / sync state / disabled mask."""

    clicked = Signal()
    double_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view_name = ""
        self.offset = 0
        self.current_frame = 0
        self.total_frames = 0
        self.fps = DEFAULT_FPS
        self.is_selected = False
        self.is_enabled = True
        self.synced = True
        self.seek_pending = False
        self._paint_samples_ms = collections.deque(maxlen=2048)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        started = perf_counter()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if not self.is_enabled:
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))
            painter.setPen(QColor(COLOR_TEXT_DIM))
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.drawText(QRect(0, 0, w, h), Qt.AlignCenter, "已禁用")
            painter.end()
            self._paint_samples_ms.append((perf_counter() - started) * 1000.0)
            return

        bg = QColor(0, 0, 0, 165)
        th = 20
        font = QFont("Consolas", 10)
        painter.setFont(font)
        fm = painter.fontMetrics()

        # Border (lightweight seek hint: orange border, no occlusion)
        if self.is_selected:
            bc = QColor(COLOR_ACCENT)
        elif self.seek_pending:
            bc = QColor(255, 152, 0)
        elif not self.synced:
            bc = QColor(255, 152, 0)
        else:
            bc = QColor(COLOR_BORDER)
        painter.setPen(QPen(bc, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(1, 1, w - 2, h - 2)

        # Top-left: view name
        color = QColor(COLOR_ACCENT) if self.is_selected else QColor(COLOR_TEXT)
        tw = fm.horizontalAdvance(self.view_name) + 10
        painter.fillRect(4, 4, tw, th, bg)
        painter.setPen(color)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(9, 4 + th - 5, self.view_name)
        font.setBold(False)
        painter.setFont(font)

        # Top-right: frame number
        fs = f"F: {self.current_frame:06d}"
        tw = fm.horizontalAdvance(fs) + 10
        painter.fillRect(w - tw - 4, 4, tw, th, bg)
        painter.setPen(QColor(COLOR_TEXT))
        painter.drawText(w - tw + 1, 4 + th - 5, fs)

        # Bottom-left: time
        if self.fps > 0 and self.total_frames > 0:
            sec = self.current_frame / self.fps
            mm, ss = divmod(int(sec), 60)
            ff = int((sec - int(sec)) * 100)
            ts = f"{mm:02d}:{ss:02d}.{ff:02d}"
        else:
            ts = "--:--.--"
        tw = fm.horizontalAdvance(ts) + 10
        painter.fillRect(4, h - th - 8, tw, th, bg)
        painter.drawText(9, h - th - 8 + th - 5, ts)

        # Bottom-right: offset for linked views; local mode is explicit so a
        # stale pre-unlink offset cannot be mistaken for the visible frame.
        if not self.synced:
            os_ = "LOCAL"
            oc = QColor(255, 152, 0)
        elif self.offset > 0:
            os_ = f"offset: +{self.offset}"
            oc = QColor(COLOR_POSITIVE)
        elif self.offset < 0:
            os_ = f"offset: {self.offset}"
            oc = QColor(COLOR_NEGATIVE)
        else:
            os_ = "offset: 0"
            oc = QColor(COLOR_TEXT)
        tw = fm.horizontalAdvance(os_) + 10
        painter.fillRect(w - tw - 4, h - th - 8, tw, th, bg)
        painter.setPen(oc)
        painter.drawText(w - tw + 1, h - th - 8 + th - 5, os_)

        # Bottom progress bar
        if self.total_frames > 0:
            prog = self.current_frame / self.total_frames
            bh = 3
            by = h - bh - 1
            painter.fillRect(1, by, w - 2, bh, QColor(0, 0, 0, 120))
            painter.fillRect(1, by, int((w - 2) * prog), bh, QColor(COLOR_ACCENT))

        painter.end()
        self._paint_samples_ms.append((perf_counter() - started) * 1000.0)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()


# ==================== Video display area ====================

class VideoDisplay(QWidget):
    """Video frame display area with paintEvent. Caches scaled pixmap."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._cached_scaled = None
        self._cached_size = None
        self._paint_samples_ms = collections.deque(maxlen=2048)
        self._scale_samples_ms = collections.deque(maxlen=2048)
        self.setMinimumSize(200, 120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background: #1a1a1a;")

    def set_pixmap(self, pixmap):
        """Display a pixmap; keeps the last good frame on None/invalid.

        The video area must never be cleared to a gray/black placeholder
        while a seek is pending — the previous frame stays visible until
        the new frame is committed atomically.
        """
        if pixmap is None or pixmap.isNull():
            return
        if (self._pixmap is not None
                and self._pixmap.cacheKey() == pixmap.cacheKey()):
            return
        self._pixmap = pixmap
        self._cached_scaled = None
        self.update()

    def paintEvent(self, event):
        started = perf_counter()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1a1a1a"))
        if self._pixmap:
            w, h = self.width(), self.height()
            size = (w, h)
            if self._cached_size != size or self._cached_scaled is None:
                scale_started = perf_counter()
                self._cached_scaled = self._pixmap.scaled(
                    w, h, Qt.KeepAspectRatio, Qt.FastTransformation)
                self._scale_samples_ms.append(
                    (perf_counter() - scale_started) * 1000.0)
                self._cached_size = size
            scaled = self._cached_scaled
            x = (w - scaled.width()) // 2
            y = (h - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        painter.end()
        self._paint_samples_ms.append((perf_counter() - started) * 1000.0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._cached_scaled = None


# ==================== Video cell ====================

class VideoCell(QWidget):
    """
    A complete video cell widget.
    Supports OpenCV ring-buffer prefetch backend / mpv GPU backend.
    Supports sync lock and double-click video selection.
    """

    view_clicked = Signal(str)
    offset_changed = Signal(str, int)
    position_jump = Signal(int)
    enable_toggled = Signal(str, bool)
    solo_stepping = Signal(str, int)
    sync_toggled = Signal(str, bool)
    solo_position_jump = Signal(str, int)
    video_file_selected = Signal(str, str)
    seek_frame_ready = Signal(str, int, int, object)
    seek_frame_failed = Signal(str, int, int, str)
    audio_load_finished = Signal(str)

    def __init__(self, view_name: str, temp_dir: str, parent=None):
        super().__init__(parent)
        self.view_name = view_name
        self.temp_dir = temp_dir
        self.offset = 0
        self.current_frame = 0
        self.local_frame = 0
        self.total_frames = 0
        self.fps = DEFAULT_FPS
        self.is_enabled = True
        self.has_audio = False
        self._pixmap = None
        self._last_good_pixmap = None
        self.synced = True
        self.grid_pos = (-1, -1)
        self.view_color = ""
        self.setAcceptDrops(True)

        # Backend objects
        self.decoder = None   # PrefetchDecoder
        self.player = None    # mpv.MPV
        self._display_counter = 0  # throttle non-critical UI updates
        self._latest_seek_request_id = 0
        self._local_seek_generation = 0
        self._audio_worker = None
        self._pixmap_samples_ms = collections.deque(maxlen=2048)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        # ---- Color header strip ----
        self._header = DraggableHeader(self, "#888888")
        layout.addWidget(self._header)

        # ---- Video area ----
        self.video_frame = VideoDisplay()
        self.overlay = OverlayWidget(self.video_frame)
        self.overlay.view_name = view_name
        self.overlay.clicked.connect(lambda: self.view_clicked.emit(self.view_name))
        self.overlay.double_clicked.connect(self._on_double_click)
        layout.addWidget(self.video_frame, 1)

        # ---- Progress slider ----
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setFixedHeight(14)
        self.slider.setStyleSheet(PROGRESS_SLIDER_STYLE)
        self.slider.setRange(0, 1000)
        self.slider.setValue(0)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        layout.addWidget(self.slider)

        # ---- Time label ----
        self.time_label = QLabel("00:00.00 / 00:00.00")
        self.time_label.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 8pt; font-family: Consolas; "
            f"background: transparent; padding: 0 4px;")
        self.time_label.setFixedHeight(14)
        layout.addWidget(self.time_label)

        # ---- Control button row ----
        ctrl = QWidget()
        ctrl.setFixedHeight(22)
        ctrl.setStyleSheet(f"background: {COLOR_PANEL_BG};")
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(2, 0, 2, 0)
        cl.setSpacing(2)

        def btn(text, tooltip, callback, fixed_width=None):
            b = QPushButton(text)
            b.setStyleSheet(CELL_BTN_STYLE)
            b.setToolTip(tooltip)
            b.clicked.connect(callback)
            if fixed_width:
                b.setFixedWidth(fixed_width)
            cl.addWidget(b)
            return b

        self.btn_sync = btn("🔗", "同步锁定（与其他格子共同播放）",
                            self._toggle_sync, fixed_width=26)
        self._update_sync_style()
        self.btn_enable = btn("👁", "启用/禁用此视角",
                              self._toggle_enable, fixed_width=26)
        cl.addSpacing(2)

        btn("◀◀", "本视角 -25 帧",
            lambda: self._request_local_step(-25))
        btn("◀", "本视角 -1 帧",
            lambda: self._request_local_step(-1))
        self.btn_solo = btn("▶/⏸", "独立播放此视角", self._toggle_solo)
        self._solo_timer = QTimer(self)
        self._solo_timer.timeout.connect(self._on_solo_tick)
        self._solo_playing = False
        btn("▶", "本视角 +1 帧",
            lambda: self._request_local_step(1))
        btn("▶▶", "本视角 +25 帧",
            lambda: self._request_local_step(25))
        cl.addSpacing(4)
        btn("-", "本视角 -1 帧",
            lambda: self._request_local_step(-1), fixed_width=20)
        self.lbl_offset = QLabel("0")
        self.lbl_offset.setAlignment(Qt.AlignCenter)
        self.lbl_offset.setFixedWidth(36)
        self.lbl_offset.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 9pt; font-family: Consolas;")
        cl.addWidget(self.lbl_offset)
        btn("+", "本视角 +1 帧",
            lambda: self._request_local_step(1), fixed_width=20)
        cl.addStretch()
        layout.addWidget(ctrl)

        # ---- Waveform bar ----
        self.waveform = WaveformBar(view_name)
        self.waveform.position_clicked.connect(self._on_slider_moved)
        layout.addWidget(self.waveform)

    # ---- Sync lock ----

    def _toggle_sync(self):
        self.synced = not self.synced
        self.overlay.synced = self.synced
        self.overlay.update()
        self._update_sync_style()
        self.sync_toggled.emit(self.view_name, self.synced)

    def _request_local_step(self, delta: int):
        """Route a per-view step without conflating it with master sync."""
        self.solo_stepping.emit(self.view_name, delta)

    def _update_sync_style(self):
        if self.synced:
            self.btn_sync.setText("🔗")
            self.btn_sync.setToolTip("同步锁定：跟随全局播放/暂停/步进")
            self.btn_sync.setStyleSheet(
                CELL_BTN_STYLE +
                "QPushButton { background: #2a5a3a; border-color: #4CAF50; }")
        else:
            self.btn_sync.setText("🔓")
            self.btn_sync.setToolTip("同步解锁：独立播放/拖进度条")
            self.btn_sync.setStyleSheet(
                CELL_BTN_STYLE +
                "QPushButton { background: #5a3a2a; border-color: #FF9800; }")
        if hasattr(self, "lbl_offset"):
            self.update_offset_label(self.offset)

    # ---- Double-click select video ----

    def _on_double_click(self):
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择视频 — {self.view_name}", "",
            "视频文件 (*.mp4 *.avi *.mkv *.mov);;所有文件 (*)")
        if path:
            self.video_file_selected.emit(self.view_name, path)

    # ---- Backend init ----

    def init_backend(self, video_path: str, total_frames: int, fps: float):
        self.cleanup()
        self.total_frames = total_frames
        self.fps = fps
        self.overlay.total_frames = total_frames
        self.overlay.fps = fps
        self.slider.setRange(0, max(1, total_frames - 1))
        self.current_frame = 0
        self.local_frame = 0

        if cfg.BACKEND == "mpv":
            self._init_mpv(video_path)
        else:
            self._init_opencv(video_path)

        self._update_time_label(0)

    def _init_opencv(self, video_path: str):
        self.decoder = PrefetchDecoder(video_path, DECODE_TARGET_WIDTH)
        self.decoder.frame_ready.connect(self._on_seek_frame_ready)
        self.decoder.frame_failed.connect(self._on_seek_frame_failed)
        self.decoder.start()
        self.decoder.seek(0, request_id=0)

    def _init_mpv(self, video_path: str):
        try:
            import mpv
        except OSError:
            print("[Warning] mpv DLL not found, falling back to OpenCV backend")
            self._init_opencv(video_path)
            return

        old = self.video_frame
        self.video_frame = QWidget()
        self.video_frame.setMinimumSize(200, 120)
        self.video_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_frame.setStyleSheet("background: #1a1a1a;")
        self.layout().replaceWidget(old, self.video_frame)
        old.deleteLater()
        self.overlay.setParent(self.video_frame)

        self.video_frame.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.video_frame.setAttribute(Qt.WA_NativeWindow)
        _ = self.video_frame.winId()

        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        wid = str(int(self.video_frame.winId()))
        self.player = mpv.MPV(
            wid=wid, hwdec='auto', vo='gpu', pause=True, audio=False,
            keep_open='yes', loop='no', hr_seek='yes',
            hr_seek_framedrop='no', demuxer_max_bytes='50MiB', quiet=True,
        )
        self.player.play(video_path)
        self.player.pause = True

    # ---- Seek first frame push callback ----

    def _on_seek_frame_ready(self, request_id, frame_number, qimg):
        """Drop stale callbacks; global requests are committed by the barrier."""
        if request_id != self._latest_seek_request_id:
            return
        if request_id > 0:
            self.seek_frame_ready.emit(
                self.view_name, request_id, frame_number, qimg)
        else:
            self.display_image(qimg, frame_number)

    def _on_seek_frame_failed(self, request_id, frame_number, message):
        if request_id != self._latest_seek_request_id:
            return
        if request_id > 0:
            self.seek_frame_failed.emit(
                self.view_name, request_id, frame_number, message)

    # ---- Display frame (main thread) ----

    def display_image(self, qimg, frame_idx, fast=False):
        """Main thread: display QImage to VideoDisplay.
        fast=True skips non-critical UI updates (throttled during playback).
        """
        if qimg is None or qimg.isNull():
            return  # keep last good frame visible
        pixmap_started = perf_counter()
        pixmap = QPixmap.fromImage(qimg)
        self._pixmap_samples_ms.append(
            (perf_counter() - pixmap_started) * 1000.0)
        self._pixmap = pixmap
        self._last_good_pixmap = pixmap
        self.current_frame = frame_idx
        self.local_frame = frame_idx

        if fast:
            self._display_counter += 1
            if self._display_counter % 5 == 0:
                self.overlay.current_frame = frame_idx
                self.overlay.update()
                self.slider.blockSignals(True)
                self.slider.setValue(frame_idx)
                self.slider.blockSignals(False)
                self._update_time_label(frame_idx)
        else:
            self.overlay.current_frame = frame_idx
            self.overlay.update()
            self.slider.blockSignals(True)
            self.slider.setValue(frame_idx)
            self.slider.blockSignals(False)
            self._update_time_label(frame_idx)

        if hasattr(self.video_frame, 'set_pixmap'):
            self.video_frame.set_pixmap(pixmap)

    # ---- Public interface ----

    def seek_to_frame(self, frame: int, request_id: int = None):
        """Seek to specified frame (called during pause/step)."""
        frame = max(0, min(frame, self.total_frames - 1)) if self.total_frames > 0 else 0
        self.local_frame = frame
        if request_id is None:
            self._local_seek_generation += 1
            request_id = -self._local_seek_generation
        self._latest_seek_request_id = request_id
        if cfg.BACKEND == "mpv" and self.player and self.fps > 0:
            self.player.pause = True
            self.player.time_pos = frame_to_time(frame, self.fps)
            self.current_frame = frame
            self.overlay.current_frame = frame
            self.overlay.update()
            self.slider.blockSignals(True)
            self.slider.setValue(frame)
            self.slider.blockSignals(False)
            self._update_time_label(frame)
            if request_id > 0:
                self.seek_frame_ready.emit(
                    self.view_name, request_id, frame, None)
        elif self.decoder:
            self.decoder.request_frame(frame, request_id)

    def play(self):
        """Start continuous decoding."""
        if self.decoder:
            self.decoder.set_playing(True)
        if cfg.BACKEND == "mpv" and self.player and self.is_enabled:
            self.player.pause = False

    def pause(self):
        """Pause decoding."""
        if self.decoder:
            self.decoder.set_playing(False)
        if cfg.BACKEND == "mpv" and self.player:
            self.player.pause = True

    def set_speed(self, speed: float):
        if cfg.BACKEND == "mpv" and self.player:
            self.player.speed = speed

    def backend_status(self, fallback_codec=""):
        """Return runtime decode facts suitable for the status bar."""
        if not self.player:
            return {
                "backend": "opencv", "codec": fallback_codec or "unknown",
                "hwdec_current": "none", "gpu_decode_active": False,
                "dropped_frames": 0,
            }
        def value(name, default=None):
            try:
                result = getattr(self.player, name)
                return default if result is None else result
            except Exception:
                return default
        hwdec = str(value("hwdec_current", "none"))
        decoder_drops = int(value("decoder_frame_drop_count", 0) or 0)
        vo_drops = int(value("vo_drop_frame_count", 0) or 0)
        return {
            "backend": "mpv",
            "codec": str(value("video_codec", fallback_codec or "unknown")),
            "hwdec_current": hwdec,
            "gpu_decode_active": hwdec.lower() not in {"", "no", "none"},
            "dropped_frames": decoder_drops + vo_drops,
        }

    def performance_metrics(self):
        return {
            "qimage_to_qpixmap_ms": _distribution(self._pixmap_samples_ms),
            "widget_scale_ms": _distribution(
                getattr(self.video_frame, "_scale_samples_ms", ())),
            "widget_paint_ms": _distribution(
                getattr(self.video_frame, "_paint_samples_ms", ())),
            "overlay_paint_ms": _distribution(self.overlay._paint_samples_ms),
        }

    def set_selected(self, selected: bool):
        self.overlay.is_selected = selected
        self.overlay.update()

    def set_seek_pending(self, pending: bool):
        self.overlay.seek_pending = pending
        self.overlay.update()

    def set_offset(self, offset: int):
        self.offset = offset
        self.overlay.offset = offset
        self.update_offset_label(offset)
        self.waveform.set_offset(offset)

    def update_offset_label(self, offset: int):
        if not self.synced:
            self.lbl_offset.setText("LOCAL")
            c = "#FF9800"
        elif offset > 0:
            self.lbl_offset.setText(f"+{offset}")
            c = COLOR_POSITIVE
        elif offset < 0:
            self.lbl_offset.setText(str(offset))
            c = COLOR_NEGATIVE
        else:
            self.lbl_offset.setText("0")
            c = COLOR_TEXT
        self.lbl_offset.setStyleSheet(
            f"color: {c}; font-size: 9pt; font-family: Consolas;")

    def update_overlay_for_base(self, base_frame: int):
        target = base_frame + self.offset
        target = max(0, min(target, self.total_frames - 1)) if self.total_frames > 0 else 0
        self.overlay.current_frame = target
        self.overlay.update()
        self.waveform.set_base_frame(base_frame)

    # ---- Drag & drop swap ----

    def set_view_color(self, color: str):
        self.view_color = color
        self._header.set_color(color)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-mvsp-cell-index"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-mvsp-cell-index"):
            raw = bytes(event.mimeData().data(
                "application/x-mvsp-cell-index"))
            parts = raw.decode().split(",")
            src_pos = (int(parts[0]), int(parts[1]))
            mw = self.window()
            if hasattr(mw, '_swap_cells'):
                mw._swap_cells(src_pos, self.grid_pos)
            event.acceptProposedAction()

    # ---- Paint / resize ----

    def paintEvent(self, event):
        super().paintEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.setGeometry(self.video_frame.rect())

    # ---- Solo play ----

    def _toggle_solo(self):
        if self._solo_playing:
            self._solo_timer.stop()
            self._solo_playing = False
            self.btn_solo.setText("▶/⏸")
            if self.decoder:
                self.decoder.set_playing(False)
        else:
            if self.decoder:
                self.decoder.set_playing(True)
            self._solo_timer.start(40)
            self._solo_playing = True
            self.btn_solo.setText("⏸")

    def _on_solo_tick(self):
        """Solo play tick: pull frame from buffer."""
        if self.total_frames > 0 and self.decoder:
            nxt = self.current_frame + 1
            if nxt >= self.total_frames:
                self._toggle_solo()
                return
            qimg = self.decoder.get_frame(nxt)
            if qimg:
                self.display_image(qimg, nxt)
                self.waveform.set_base_frame(nxt)

    # ---- Internal ----

    def _toggle_enable(self):
        self.is_enabled = not self.is_enabled
        self.overlay.is_enabled = self.is_enabled
        self.overlay.update()
        self.enable_toggled.emit(self.view_name, self.is_enabled)
        if not self.is_enabled:
            if cfg.BACKEND == "mpv" and self.player:
                self.player.pause = True

    def _on_slider_moved(self, value):
        if self.synced:
            self.position_jump.emit(value)
        else:
            self.solo_position_jump.emit(self.view_name, value)

    def _update_time_label(self, frame: int):
        if self.fps <= 0:
            return
        cur = frame / self.fps
        tot = self.total_frames / self.fps
        def fmt(s):
            m, sec = divmod(int(s), 60)
            ms = int((s - int(s)) * 100)
            return f"{m:02d}:{sec:02d}.{ms:02d}"
        self.time_label.setText(f"{fmt(cur)} / {fmt(tot)}")

    # ---- Audio loading ----

    def load_audio(self, video_path: str):
        wav_path = Path(self.temp_dir) / f"{self.view_name}.wav"
        if self._audio_worker and self._audio_worker.isRunning():
            return
        self._audio_worker = AudioLoadThread(video_path, wav_path, self)
        self._audio_worker.audio_ready.connect(self._on_audio_ready)
        self._audio_worker.start()

    def _on_audio_ready(self, envelope, sr, ok, message):
        if ok:
            self.has_audio = True
            self.waveform.set_audio(envelope, sr)
        elif message not in ("", "cancelled"):
            print(f"音频加载失败 [{self.view_name}]: {message}")
        self.audio_load_finished.emit(self.view_name)

    # ---- Cleanup ----

    def cleanup(self):
        if self._solo_playing:
            self._solo_timer.stop()
            self._solo_playing = False
        if self.decoder:
            self.decoder.stop()
            self.decoder = None
        if self._audio_worker and self._audio_worker.isRunning():
            self._audio_worker.requestInterruption()
            self._audio_worker.wait(4000)
        self._audio_worker = None
        if self.player:
            try:
                self.player.pause = True
                self.player.terminate()
            except Exception:
                pass
            self.player = None
