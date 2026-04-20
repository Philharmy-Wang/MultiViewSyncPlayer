"""
multiview_sync_player.video_cell — Single video cell widget

Dual backend support:
  - OpenCV ring-buffer prefetch decode (default, smooth playback)
  - mpv GPU decode (optional, requires DLL)

Contains video display + info overlay + progress bar + control buttons
+ audio waveform bar + sync lock.
Supports double-click to select video file.
"""

import os
import subprocess
from pathlib import Path

import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QSizePolicy, QFileDialog,
)
from PySide6.QtCore import Qt, QTimer, Signal, QRect
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QFont, QPolygon, QCursor
)

from .config import (
    COLOR_BORDER, COLOR_TEXT, COLOR_TEXT_DIM, COLOR_ACCENT,
    COLOR_POSITIVE, COLOR_NEGATIVE, COLOR_PANEL_BG,
    DEFAULT_FPS, BACKEND, DECODE_TARGET_WIDTH, FFMPEG_PATH,
    get_view_color,
)
from .styles import CELL_BTN_STYLE, PROGRESS_SLIDER_STYLE
from .waveform_bar import WaveformBar
from .video_decoder import PrefetchDecoder


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
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if not self.is_enabled:
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))
            painter.setPen(QColor(COLOR_TEXT_DIM))
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.drawText(QRect(0, 0, w, h), Qt.AlignCenter, "Disabled")
            painter.end()
            return

        bg = QColor(0, 0, 0, 165)
        th = 20
        font = QFont("Consolas", 10)
        painter.setFont(font)
        fm = painter.fontMetrics()

        # Border
        if self.is_selected:
            bc = QColor(COLOR_ACCENT)
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

        # Bottom-right: offset
        if self.offset > 0:
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
        self.setMinimumSize(200, 120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background: #1a1a1a;")

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self._cached_scaled = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1a1a1a"))
        if self._pixmap:
            w, h = self.width(), self.height()
            size = (w, h)
            if self._cached_size != size or self._cached_scaled is None:
                self._cached_scaled = self._pixmap.scaled(
                    w, h, Qt.KeepAspectRatio, Qt.FastTransformation)
                self._cached_size = size
            scaled = self._cached_scaled
            x = (w - scaled.width()) // 2
            y = (h - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        painter.end()

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

    def __init__(self, view_name: str, temp_dir: str, parent=None):
        super().__init__(parent)
        self.view_name = view_name
        self.temp_dir = temp_dir
        self.offset = 0
        self.current_frame = 0
        self.total_frames = 0
        self.fps = DEFAULT_FPS
        self.is_enabled = True
        self.has_audio = False
        self._pixmap = None
        self.synced = True

        # Backend objects
        self.decoder = None   # PrefetchDecoder
        self.player = None    # mpv.MPV
        self._display_counter = 0  # throttle non-critical UI updates

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

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

        self.btn_sync = btn("🔗", "Sync lock: locked",
                            self._toggle_sync, fixed_width=26)
        self._update_sync_style()
        self.btn_enable = btn("👁", "Enable/Disable",
                              self._toggle_enable, fixed_width=26)
        cl.addSpacing(2)

        btn("◀◀", "Offset -25 frames",
            lambda: self.offset_changed.emit(self.view_name, -25))
        btn("◀", "Offset -1 frame",
            lambda: self.offset_changed.emit(self.view_name, -1))
        self.btn_solo = btn("▶/⏸", "Solo play/pause", self._toggle_solo)
        self._solo_timer = QTimer(self)
        self._solo_timer.timeout.connect(self._on_solo_tick)
        self._solo_playing = False
        btn("▶", "Offset +1 frame",
            lambda: self.offset_changed.emit(self.view_name, 1))
        btn("▶▶", "Offset +25 frames",
            lambda: self.offset_changed.emit(self.view_name, 25))
        cl.addSpacing(4)
        btn("-", "Offset -1 frame",
            lambda: self.offset_changed.emit(self.view_name, -1), fixed_width=20)
        self.lbl_offset = QLabel("0")
        self.lbl_offset.setAlignment(Qt.AlignCenter)
        self.lbl_offset.setFixedWidth(36)
        self.lbl_offset.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 9pt; font-family: Consolas;")
        cl.addWidget(self.lbl_offset)
        btn("+", "Offset +1 frame",
            lambda: self.offset_changed.emit(self.view_name, 1), fixed_width=20)
        cl.addStretch()
        layout.addWidget(ctrl)

        # ---- Waveform bar ----
        self.waveform = WaveformBar(view_name)
        self.waveform.position_clicked.connect(self.position_jump.emit)
        layout.addWidget(self.waveform)

    # ---- Sync lock ----

    def _toggle_sync(self):
        self.synced = not self.synced
        self.overlay.synced = self.synced
        self.overlay.update()
        self._update_sync_style()
        self.sync_toggled.emit(self.view_name, self.synced)

    def _update_sync_style(self):
        if self.synced:
            self.btn_sync.setText("🔗")
            self.btn_sync.setToolTip("Sync lock: locked (follows global)")
            self.btn_sync.setStyleSheet(
                CELL_BTN_STYLE +
                "QPushButton { background: #2a5a3a; border-color: #4CAF50; }")
        else:
            self.btn_sync.setText("🔓")
            self.btn_sync.setToolTip("Sync lock: unlocked (independent)")
            self.btn_sync.setStyleSheet(
                CELL_BTN_STYLE +
                "QPushButton { background: #5a3a2a; border-color: #FF9800; }")

    # ---- Double-click select video ----

    def _on_double_click(self):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select video — {self.view_name}", "",
            "Video files (*.mp4 *.avi *.mkv *.mov);;All files (*)")
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

        if BACKEND == "mpv":
            self._init_mpv(video_path)
        else:
            self._init_opencv(video_path)

        self._update_time_label(0)

    def _init_opencv(self, video_path: str):
        self.decoder = PrefetchDecoder(video_path, DECODE_TARGET_WIDTH)
        self.decoder.frame_ready.connect(self._on_seek_frame_ready)
        self.decoder.start()
        self.decoder.seek(0)

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

    def _on_seek_frame_ready(self, frame_number, qimg):
        """First frame push after seek: display immediately."""
        self.display_image(qimg, frame_number)

    # ---- Display frame (main thread) ----

    def display_image(self, qimg, frame_idx, fast=False):
        """Main thread: display QImage to VideoDisplay.
        fast=True skips non-critical UI updates (throttled during playback).
        """
        pixmap = QPixmap.fromImage(qimg)
        self._pixmap = pixmap
        self.current_frame = frame_idx

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

    def seek_to_frame(self, frame: int):
        """Seek to specified frame (called during pause/step)."""
        frame = max(0, min(frame, self.total_frames - 1)) if self.total_frames > 0 else 0
        self.current_frame = frame
        self.overlay.current_frame = frame
        self.overlay.update()
        if BACKEND == "mpv" and self.player and self.fps > 0:
            self.player.pause = True
            self.player.time_pos = frame / self.fps
        elif self.decoder:
            self.decoder.seek(frame)
        self.slider.blockSignals(True)
        self.slider.setValue(frame)
        self.slider.blockSignals(False)
        self._update_time_label(frame)

    def play(self):
        """Start continuous decoding."""
        if self.decoder:
            self.decoder.set_playing(True)
        if BACKEND == "mpv" and self.player and self.is_enabled:
            self.player.pause = False

    def pause(self):
        """Pause decoding."""
        if self.decoder:
            self.decoder.set_playing(False)
        if BACKEND == "mpv" and self.player:
            self.player.pause = True

    def set_speed(self, speed: float):
        if BACKEND == "mpv" and self.player:
            self.player.speed = speed

    def set_selected(self, selected: bool):
        self.overlay.is_selected = selected
        self.overlay.update()

    def set_offset(self, offset: int):
        self.offset = offset
        self.overlay.offset = offset
        self.update_offset_label(offset)
        self.waveform.set_offset(offset)

    def update_offset_label(self, offset: int):
        if offset > 0:
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

    # ---- Paint / resize ----

    def paintEvent(self, event):
        pass

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
            if BACKEND == "mpv" and self.player:
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
        try:
            cmd = [FFMPEG_PATH, "-y", "-i", video_path,
                   "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                   str(wav_path)]
            subprocess.run(cmd, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
            if wav_path.exists() and wav_path.stat().st_size > 0:
                import scipy.io.wavfile as wavfile
                sr, data = wavfile.read(str(wav_path))
                if data.ndim > 1:
                    data = data[:, 0]
                data = data.astype(np.float64)
                mx = np.max(np.abs(data))
                if mx > 0:
                    data = data / mx
                spp = 1600
                n = max(1, len(data) // spp)
                env = np.zeros(n)
                for i in range(n):
                    env[i] = np.max(np.abs(data[i * spp:(i + 1) * spp]))
                self.has_audio = True
                self.waveform.set_audio(env, sr)
        except Exception as e:
            print(f"Audio load failed [{self.view_name}]: {e}")

    # ---- Cleanup ----

    def cleanup(self):
        if self._solo_playing:
            self._solo_timer.stop()
            self._solo_playing = False
        if self.decoder:
            self.decoder.stop()
            self.decoder = None
        if self.player:
            try:
                self.player.pause = True
                self.player.terminate()
            except Exception:
                pass
            self.player = None
