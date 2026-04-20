"""
multiview_sync_player.metadata_editor — Metadata field editor dialog

QDialog with preset template selector, editable table with drag-to-reorder,
add/remove/move buttons, and OK/Cancel.
"""

from collections import OrderedDict

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QTableWidget,
    QTableWidgetItem, QPushButton, QDialogButtonBox, QLabel, QHeaderView,
    QAbstractItemView, QFrame,
)
from PySide6.QtCore import Qt

from .config import COLOR_WINDOW_BG, COLOR_PANEL_BG, COLOR_TEXT, COLOR_ACCENT
from .metadata import SessionMetadata
from .metadata_presets import get_preset_names, get_preset_by_name


class MetadataEditor(QDialog):
    """Dialog for editing session metadata fields."""

    def __init__(self, metadata: SessionMetadata, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Session Metadata")
        self.setMinimumSize(520, 400)
        self.resize(600, 480)
        self._result_metadata = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ---- Preset selector ----
        preset_row = QHBoxLayout()
        lbl = QLabel("Preset template:")
        lbl.setStyleSheet("color: " + COLOR_TEXT + ";")
        preset_row.addWidget(lbl)

        self.combo_preset = QComboBox()
        self.combo_preset.addItems(get_preset_names())
        self.combo_preset.currentTextChanged.connect(self._on_preset_selected)
        preset_row.addWidget(self.combo_preset, 1)

        self.btn_apply_preset = QPushButton("Apply")
        self.btn_apply_preset.setToolTip("Replace current fields with preset template")
        self.btn_apply_preset.clicked.connect(self._apply_preset)
        preset_row.addWidget(self.btn_apply_preset)
        layout.addLayout(preset_row)

        # ---- Separator ----
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #555;")
        layout.addWidget(sep)

        # ---- Table ----
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Field Name", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setDragDropMode(QAbstractItemView.InternalMove)
        self.table.setDefaultDropAction(Qt.MoveAction)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        # ---- Button row ----
        btn_row = QHBoxLayout()

        self.btn_add = QPushButton("➕ Add Field")
        self.btn_add.clicked.connect(self._add_field)
        btn_row.addWidget(self.btn_add)

        self.btn_remove = QPushButton("➖ Remove Selected")
        self.btn_remove.clicked.connect(self._remove_selected)
        btn_row.addWidget(self.btn_remove)

        btn_row.addSpacing(16)

        self.btn_up = QPushButton("⬆ Move Up")
        self.btn_up.clicked.connect(self._move_up)
        btn_row.addWidget(self.btn_up)

        self.btn_down = QPushButton("⬇ Move Down")
        self.btn_down.clicked.connect(self._move_down)
        btn_row.addWidget(self.btn_down)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ---- OK / Cancel ----
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # Populate from existing metadata
        self._populate_from_metadata(metadata)

    # ---- Populate ----

    def _populate_from_metadata(self, meta: SessionMetadata):
        self.table.setRowCount(0)
        for name, value in meta.items():
            self._add_row(name, value)

    def _add_row(self, name: str = "", value: str = ""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(name)
        value_item = QTableWidgetItem(value)
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, value_item)
        self.table.selectRow(row)

    # ---- Preset ----

    def _on_preset_selected(self, text):
        pass  # Only apply on button click

    def _apply_preset(self):
        preset_name = self.combo_preset.currentText()
        preset = get_preset_by_name(preset_name)
        if not preset:
            return
        self.table.setRowCount(0)
        for name, default_val in preset["fields"].items():
            self._add_row(name, default_val)

    # ---- Row operations ----

    def _add_field(self):
        self._add_row("new_field", "")
        # Select the name cell for immediate editing
        row = self.table.rowCount() - 1
        self.table.editItem(self.table.item(row, 0))

    def _remove_selected(self):
        rows = sorted(set(i.row() for i in self.table.selectedItems()),
                      reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _move_up(self):
        row = self._current_row()
        if row is None or row == 0:
            return
        self._swap_rows(row, row - 1)

    def _move_down(self):
        row = self._current_row()
        if row is None or row >= self.table.rowCount() - 1:
            return
        self._swap_rows(row, row + 1)

    def _swap_rows(self, r1, r2):
        # Swap both columns
        for col in range(2):
            item1 = self.table.takeItem(r1, col)
            item2 = self.table.takeItem(r2, col)
            self.table.setItem(r1, col, item2)
            self.table.setItem(r2, col, item1)
        self.table.selectRow(r2)

    def _current_row(self):
        items = self.table.selectedItems()
        if not items:
            return None
        return items[0].row()

    # ---- Accept ----

    def _on_accept(self):
        """Validate and build result SessionMetadata."""
        meta = SessionMetadata()
        seen = set()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            if not name_item:
                continue
            name = name_item.text().strip()
            value = value_item.text() if value_item else ""

            if not name:
                continue  # skip empty field names

            # Validate identifier
            from .metadata import _FIELD_RE
            if not _FIELD_RE.match(name):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "Invalid Field Name",
                    f"Row {row + 1}: '{name}' is not a valid field name.\n"
                    f"Use only letters, digits, underscores. "
                    f"Cannot start with a digit.")
                return

            if name in seen:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "Duplicate Field",
                    f"Row {row + 1}: field '{name}' is defined more than once.")
                return
            seen.add(name)

            meta.set(name, value)

        self._result_metadata = meta
        self.accept()

    def get_metadata(self) -> SessionMetadata:
        """Return the edited metadata (only valid after accept)."""
        return self._result_metadata
