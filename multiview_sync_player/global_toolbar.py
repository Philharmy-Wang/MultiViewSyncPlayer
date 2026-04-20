"""
multiview_sync_player.global_toolbar — 全局工具栏

会话按钮、播放控制、速度档位、偏移重置、保存、标记、帮助。
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PySide6.QtCore import Signal

from .config import COLOR_PANEL_BG, SPEED_STEPS
from .styles import SPEED_BTN_ACTIVE


class GlobalToolbar(QWidget):
    """全局工具栏。"""

    # ---- 信号 ----
    session_open_requested = Signal()
    session_new_requested = Signal()
    play_toggled = Signal()
    step_requested = Signal(int)
    seek_start = Signal()
    speed_set = Signal(int)
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

        # ---- 会话按钮 ----
        self.btn_open = QPushButton("📂 打开会话")
        self.btn_open.setToolTip("打开已保存的会话文件")
        self.btn_open.clicked.connect(self.session_open_requested.emit)
        layout.addWidget(self.btn_open)

        self.btn_new = QPushButton("➕ 新建会话")
        self.btn_new.setToolTip("清空当前会话，新建一个")
        self.btn_new.clicked.connect(self.session_new_requested.emit)
        layout.addWidget(self.btn_new)

        self._sep(layout)

        # ---- 播放控制 ----
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setObjectName("btn_play")
        self.btn_play.clicked.connect(self.play_toggled.emit)
        layout.addWidget(self.btn_play)

        btn_back_start = QPushButton("⏮")
        btn_back_start.setToolTip("回到起点（保留偏移）")
        btn_back_start.clicked.connect(self.seek_start.emit)
        layout.addWidget(btn_back_start)

        for text, delta in [("⏪", -250), ("◀", -1), ("▶", 1), ("⏩", 250)]:
            b = QPushButton(text)
            b.clicked.connect(lambda _, d=delta: self.step_requested.emit(d))
            layout.addWidget(b)

        self._sep(layout)

        # ---- 速度 ----
        layout.addWidget(self._lbl("速度:"))
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

        # ---- 功能按钮 ----
        b = QPushButton("🔄 重置偏移")
        b.clicked.connect(self.reset_offsets.emit)
        layout.addWidget(b)

        b = QPushButton("💾 保存")
        b.clicked.connect(self.save_requested.emit)
        layout.addWidget(b)

        b = QPushButton("💾 另存为...")
        b.clicked.connect(self.save_as_requested.emit)
        layout.addWidget(b)

        b = QPushButton("📋 元数据")
        b.setToolTip("编辑会话元数据字段")
        b.clicked.connect(self.metadata_requested.emit)
        layout.addWidget(b)

        b = QPushButton("➕ 添加视角")
        b.setToolTip("添加一个新的视角格子")
        b.clicked.connect(self.add_view_requested.emit)
        layout.addWidget(b)

        b = QPushButton("📌 标记帧")
        b.setToolTip("标记当前帧（快捷键 M）")
        b.clicked.connect(self.mark_frame.emit)
        layout.addWidget(b)

        b = QPushButton("❓")
        b.setFixedWidth(32)
        b.clicked.connect(self.help_requested.emit)
        layout.addWidget(b)

        layout.addStretch()

    # ---- 公共接口 ----

    def set_play_button_text(self, playing: bool):
        self.btn_play.setText("⏸ 暂停" if playing else "▶ 播放")

    def highlight_speed(self, idx: int):
        for i, b in enumerate(self.speed_buttons):
            b.setStyleSheet(SPEED_BTN_ACTIVE if i == idx else "")

    # ---- 内部 ----

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
