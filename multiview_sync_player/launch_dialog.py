"""LaunchDialog — 启动时最小对话框，仅询问行×列。替代旧的多步向导。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton,
)


class LaunchDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MultiViewSyncPlayer")
        self.setFixedSize(320, 180)

        self.chosen_rows = 2
        self.chosen_cols = 2

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        title = QLabel("🎬 多视角同步播放器")
        title.setStyleSheet("font-size:14pt; font-weight:bold;")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        root.addSpacing(10)

        picker = QHBoxLayout()
        picker.addStretch()
        picker.addWidget(QLabel("网格："))

        self._row_spin = QSpinBox()
        self._row_spin.setRange(1, 5)
        self._row_spin.setValue(2)
        self._row_spin.setFixedWidth(60)
        picker.addWidget(self._row_spin)

        picker.addWidget(QLabel(" × "))

        self._col_spin = QSpinBox()
        self._col_spin.setRange(1, 5)
        self._col_spin.setValue(2)
        self._col_spin.setFixedWidth(60)
        picker.addWidget(self._col_spin)

        picker.addStretch()
        root.addLayout(picker)

        root.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()

        self._btn_ok = QPushButton("✅ 进入")
        self._btn_ok.setDefault(True)
        self._btn_ok.clicked.connect(self._accept)
        btns.addWidget(self._btn_ok)

        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self._btn_cancel)

        root.addLayout(btns)

    def _accept(self):
        self.chosen_rows = self._row_spin.value()
        self.chosen_cols = self._col_spin.value()
        self.accept()
