"""
multiview_sync_player.global_toolbar — Global toolbar

Session buttons, playback controls, speed steps, offset reset, save, markers, help.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PySide6.QtCore import Signal

from .config import COLOR_PANEL_BG, SPEED_STEPS
from .styles import SPEED_BTN_ACTIVE


class GlobalToolbar(QWidget):
    """Global toolbar widget."""

    # ---- Signals ----
    session_open_requested = Signal()
    session_new_requested = Signal()
    play_toggled = Signal()
    step_requested = Signal(int)            # delta frames
    seek_start = Signal()                   # back to start
    speed_set = Signal(int)                 # speed_index
    reset_offsets = Signal()
    save_requested = Signal()
    save_as_requested = Signal()
    mark_frame = Signal()
    metadata_requested = Signal()
    add_view_requested = Signal()
    help_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setStyleSheet(f"background-color: {COLOR_PANEL_BG};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        # ---- Session buttons ----
        self.btn_open = QPushButton("📂 Open Session")
        self.btn_open.setToolTip("Open a saved session file")
        self.btn_open.clicked.connect(self.session_open_requested.emit)
        layout.addWidget(self.btn_open)

        self.btn_new = QPushButton("➕ New Session")
        self.btn_new.setToolTip("Start a new session (clear current)")
        self.btn_new.clicked.connect(self.session_new_requested.emit)
        layout.addWidget(self.btn_new)

        self._sep(layout)

        # ---- Playback controls ----
        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setObjectName("btn_play")
        self.btn_play.clicked.connect(self.play_toggled.emit)
        layout.addWidget(self.btn_play)

        btn_back_start = QPushButton("⏮")
        btn_back_start.setToolTip("Back to start (preserve offsets)")
        btn_back_start.clicked.connect(self.seek_start.emit)
        layout.addWidget(btn_back_start)

        for text, delta in [("⏪", -250), ("◀", -1), ("▶", 1), ("⏩", 250)]:
            b = QPushButton(text)
            b.clicked.connect(lambda _, d=delta: self.step_requested.emit(d))
            layout.addWidget(b)

        self._sep(layout)

        # ---- Speed ----
        layout.addWidget(self._lbl("Speed:"))
        self.speed_buttons = []
        for i, sp in enumerate(SPEED_STEPS):
            b = QPushButton(f"{sp}x")
            b.setFixedWidth(42)
            b.clicked.connect(lambda _, idx=i: self._set_speed(idx))
            if i == 2:
                b.setStyleSheet(SPEED_BTN_ACTIVE)
            self.speed_buttons.append(b)
            layout.addWidget(b)

        self._sep(layout)

        # ---- Action buttons ----
        b = QPushButton("🔄 Reset Offsets")
        b.clicked.connect(self.reset_offsets.emit)
        layout.addWidget(b)

        b = QPushButton("💾 Save")
        b.clicked.connect(self.save_requested.emit)
        layout.addWidget(b)

        b = QPushButton("💾 Save As...")
        b.clicked.connect(self.save_as_requested.emit)
        layout.addWidget(b)

        b = QPushButton("📋 Metadata")
        b.setToolTip("Edit session metadata fields")
        b.clicked.connect(self.metadata_requested.emit)
        layout.addWidget(b)

        b = QPushButton("➕ Add View")
        b.setToolTip("Add a new view slot to the grid")
        b.clicked.connect(self.add_view_requested.emit)
        layout.addWidget(b)

        b = QPushButton("📌 Mark Frame")
        b.setToolTip("Mark current frame (shortcut M)")
        b.clicked.connect(self.mark_frame.emit)
        layout.addWidget(b)

        b = QPushButton("❓")
        b.setFixedWidth(32)
        b.clicked.connect(self.help_requested.emit)
        layout.addWidget(b)

        layout.addStretch()

    # ---- Public interface ----

    def set_play_button_text(self, playing: bool):
        self.btn_play.setText("⏸ Pause" if playing else "▶ Play")

    def highlight_speed(self, idx: int):
        for i, b in enumerate(self.speed_buttons):
            b.setStyleSheet(SPEED_BTN_ACTIVE if i == idx else "")

    # ---- Internal ----

    def _set_speed(self, idx):
        self.highlight_speed(idx)
        self.speed_set.emit(idx)

    @staticmethod
    def _lbl(text):
        l = QLabel(text)
        l.setStyleSheet("background: transparent; font-size: 10pt;")
        return l

    @staticmethod
    def _sep(layout):
        s = QFrame()
        s.setFrameShape(QFrame.VLine)
        s.setStyleSheet("color: #555; background: transparent;")
        layout.addWidget(s)
