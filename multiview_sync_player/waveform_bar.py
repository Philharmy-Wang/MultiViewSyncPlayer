"""
multiview_sync_player.waveform_bar — Single-view audio waveform bar

Displays amplitude envelope, supports click-to-seek and drag-to-resize.
"""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QCursor, QFont, QPolygon

import numpy as np

from .config import get_view_color, COLOR_TEXT_DIM, COLOR_ACCENT


class WaveformBar(QWidget):
    """Single-view audio waveform bar with click-to-seek and drag-to-resize."""

    position_clicked = Signal(int)       # base frame index
    height_changed = Signal()

    def __init__(self, view_name: str, parent=None):
        super().__init__(parent)
        self.view_name = view_name
        self.setMinimumHeight(30)
        self.setMaximumHeight(200)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

        self.envelope = None
        self.sr = 0
        self.fps = 25.0
        self.total_frames = 0
        self.base_frame = 0
        self.offset = 0
        self.has_audio = False
        self._resizing = False
        self._resize_start_y = 0
        self._resize_start_h = 40
        self.markers = []

    def set_audio(self, envelope, sr):
        self.envelope = envelope
        self.sr = sr
        self.has_audio = envelope is not None
        self.update()

    def set_video_meta(self, fps, total_frames):
        self.fps = fps
        self.total_frames = total_frames

    def set_base_frame(self, frame):
        self.base_frame = frame
        self.update()

    def set_offset(self, offset):
        self.offset = offset
        self.update()

    def set_markers(self, frames):
        self.markers = frames or []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#1a1a1a"))

        # Drag handle
        handle_color = QColor(COLOR_ACCENT) if self._resizing else QColor(80, 80, 80)
        painter.fillRect(0, 0, w, 3, handle_color)

        if not self.has_audio or self.envelope is None:
            painter.setPen(QColor(COLOR_TEXT_DIM))
            painter.setFont(QFont("Microsoft YaHei", 9))
            painter.drawText(QRect(0, 3, w, h - 3), Qt.AlignCenter, "No audio")
            painter.end()
            return

        margin = 4
        plot_y, plot_h = 4, h - 6
        plot_w = w - 2 * margin

        color = get_view_color(self.view_name)
        color.setAlpha(200)
        painter.setPen(QPen(color, 1.0))

        envelope_sr = self.sr / 1600
        offset_sec = self.offset / self.fps if self.fps > 0 else 0
        total_dur = self.total_frames / self.fps if self.fps > 0 else 1

        prev = None
        for i in range(len(self.envelope)):
            t_sec = i / envelope_sr - offset_sec
            x = margin + (t_sec / total_dur) * plot_w
            if x < margin - 1 or x > w - margin + 1:
                prev = None
                continue
            y = plot_y + plot_h / 2 - self.envelope[i] * plot_h * 0.45
            if prev is not None:
                painter.drawLine(int(prev[0]), int(prev[1]), int(x), int(y))
            prev = (x, y)

        # Marker positions (small triangles)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 200, 0, 180))
        for mf in self.markers:
            sec = mf / self.fps if self.fps > 0 else 0
            mx = margin + (sec / total_dur) * plot_w
            if margin <= mx <= w - margin:
                painter.drawPolygon(QPolygon([
                    (int(mx) - 3, plot_y + 1),
                    (int(mx) + 3, plot_y + 1),
                    (int(mx), plot_y + 6),
                ]))

        # Current frame vertical line
        if self.fps > 0 and self.total_frames > 0:
            cur_sec = self.base_frame / self.fps
            lx = margin + (cur_sec / total_dur) * plot_w
            if margin <= lx <= w - margin:
                painter.setPen(QPen(QColor(255, 60, 60), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawLine(int(lx), plot_y, int(lx), plot_y + plot_h)

        painter.end()

    def mousePressEvent(self, event):
        if event.position().y() <= 6:
            self._resizing = True
            self._resize_start_y = event.globalPosition().y()
            self._resize_start_h = self.height()
            self.setCursor(QCursor(Qt.SplitVCursor))
        elif event.button() == Qt.LeftButton and self.has_audio:
            margin = 4
            x = event.position().x()
            total_dur = self.total_frames / self.fps if self.fps > 0 else 1
            ratio = (x - margin) / (self.width() - 2 * margin)
            self.position_clicked.emit(max(0, int(ratio * total_dur * self.fps)))

    def mouseMoveEvent(self, event):
        if self._resizing:
            dy = event.globalPosition().y() - self._resize_start_y
            self.setFixedHeight(max(30, min(200, self._resize_start_h - int(dy))))
            self.height_changed.emit()
        elif event.position().y() <= 6:
            self.setCursor(QCursor(Qt.SplitVCursor))
        else:
            self.setCursor(QCursor(Qt.PointingHandCursor))

    def mouseReleaseEvent(self, event):
        self._resizing = False
        self.setCursor(QCursor(Qt.ArrowCursor))
