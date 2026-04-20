"""
multiview_sync_player.startup_wizard — Startup wizard dialog

Three-page QWizard:
  Page 1: Layout preset selection (or custom rows/cols)
  Page 2: Metadata template selection (optional)
  Page 3: View naming and color assignment

Returns (LayoutConfig, SessionMetadata) on accept.
"""

from PySide6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QGridLayout,
    QComboBox, QSpinBox, QLabel, QLineEdit, QPushButton, QGroupBox,
    QWidget, QScrollArea,
)
from PySide6.QtCore import Qt

from .config import COLOR_WINDOW_BG, COLOR_TEXT, VIEW_COLOR_PALETTE
from .layout_manager import LAYOUT_PRESETS, LayoutConfig, _default_view_names
from .metadata import SessionMetadata
from .metadata_presets import get_preset_names, get_preset_by_name


# ==================== Page 1: Layout ====================

class _LayoutPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Layout Selection")
        self.setSubTitle("Choose a grid layout for your views.")

        layout = QVBoxLayout(self)

        # Preset combo
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Preset:"))
        self.combo_preset = QComboBox()
        for name, r, c in LAYOUT_PRESETS:
            self.combo_preset.addItem(name)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        row1.addWidget(self.combo_preset, 1)
        layout.addLayout(row1)

        # Custom rows/cols
        self.custom_group = QGroupBox("Custom Layout")
        custom_lay = QHBoxLayout(self.custom_group)
        custom_lay.addWidget(QLabel("Rows:"))
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 9)
        self.spin_rows.setValue(2)
        custom_lay.addWidget(self.spin_rows)
        custom_lay.addWidget(QLabel("Cols:"))
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 9)
        self.spin_cols.setValue(3)
        custom_lay.addWidget(self.spin_cols)
        self.custom_group.setVisible(False)
        layout.addWidget(self.custom_group)

        # Preview
        self.preview_label = QLabel("2 × 3 = 6 slots")
        self.preview_label.setStyleSheet(
            f"font-size: 11pt; color: {COLOR_TEXT}; padding: 8px;")
        layout.addWidget(self.preview_label)
        layout.addStretch()

        # Default to "2x3 Six-view"
        self.combo_preset.setCurrentIndex(4)
        self._on_preset_changed(4)

    def _on_preset_changed(self, idx):
        if idx < 0 or idx >= len(LAYOUT_PRESETS):
            return
        name, rows, cols = LAYOUT_PRESETS[idx]
        if rows == 0 and cols == 0:
            self.custom_group.setVisible(True)
            self._update_preview(self.spin_rows.value(), self.spin_cols.value())
        else:
            self.custom_group.setVisible(False)
            self._update_preview(rows, cols)

    def _update_preview(self, rows, cols):
        self.preview_label.setText(f"{rows} × {cols} = {rows * cols} slots")

    def get_layout_config(self) -> LayoutConfig:
        idx = self.combo_preset.currentIndex()
        name, rows, cols = LAYOUT_PRESETS[idx]
        if rows == 0:
            rows = self.spin_rows.value()
            cols = self.spin_cols.value()
        return LayoutConfig(rows=rows, cols=cols)


# ==================== Page 2: Metadata ====================

class _MetadataPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Session Metadata")
        self.setSubTitle("Choose a metadata template, or skip to use empty defaults.")

        layout = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Template:"))
        self.combo_template = QComboBox()
        self.combo_template.addItem("(Skip — no metadata)")
        self.combo_template.addItems(get_preset_names())
        self.combo_template.currentTextChanged.connect(self._on_template_changed)
        row1.addWidget(self.combo_template, 1)
        layout.addLayout(row1)

        self.preview_label = QLabel("")
        self.preview_label.setStyleSheet(
            f"font-size: 10pt; color: {COLOR_TEXT}; padding: 8px;")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        layout.addStretch()

    def _on_template_changed(self, text):
        if text == "(Skip — no metadata)":
            self.preview_label.setText("No metadata fields will be set.")
            return
        preset = get_preset_by_name(text)
        if preset:
            fields = ", ".join(preset["fields"].keys())
            self.preview_label.setText(f"Fields: {fields}")

    def get_metadata(self) -> SessionMetadata:
        text = self.combo_template.currentText()
        if text == "(Skip — no metadata)":
            return SessionMetadata()
        preset = get_preset_by_name(text)
        if not preset:
            return SessionMetadata()
        meta = SessionMetadata()
        for name, default in preset["fields"].items():
            meta.set(name, default)
        return meta


# ==================== Page 3: View Naming ====================

class _ViewNamingPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("View Names")
        self.setSubTitle("Customize names for each view slot.")
        self._editors = []

        self._main_layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._grid_layout = QGridLayout(self._scroll_content)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(self._scroll_content)
        self._main_layout.addWidget(scroll)

    def initializePage(self):
        """Called when this page is shown. Reads layout from page 1."""
        # Clear previous editors
        for editor, label, color_btn in self._editors:
            editor.deleteLater()
            label.deleteLater()
            color_btn.deleteLater()
        self._editors.clear()

        # Get layout from page 1
        layout_page: _LayoutPage = self.wizard().page(0)
        config = layout_page.get_layout_config()

        header = QLabel("Slot")
        header.setStyleSheet("font-weight: bold;")
        self._grid_layout.addWidget(header, 0, 0)
        header2 = QLabel("View Name")
        header2.setStyleSheet("font-weight: bold;")
        self._grid_layout.addWidget(header2, 0, 1)
        header3 = QLabel("Color")
        header3.setStyleSheet("font-weight: bold;")
        self._grid_layout.addWidget(header3, 0, 2)

        for i, vn in enumerate(config.view_names):
            row = i + 1
            lbl = QLabel(f"  {i + 1}  ")
            lbl.setStyleSheet(f"color: {COLOR_TEXT};")
            editor = QLineEdit(vn)
            editor.setPlaceholderText(f"View {i + 1}")
            color = VIEW_COLOR_PALETTE[i % len(VIEW_COLOR_PALETTE)]
            color_btn = QPushButton()
            color_btn.setFixedSize(28, 24)
            color_btn.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid #666;")
            color_btn._color = color
            # Color picker on click
            color_btn.clicked.connect(
                lambda checked, btn=color_btn: self._pick_color(btn))

            self._grid_layout.addWidget(lbl, row, 0)
            self._grid_layout.addWidget(editor, row, 1)
            self._grid_layout.addWidget(color_btn, row, 2)
            self._editors.append((editor, lbl, color_btn))

    def _pick_color(self, btn):
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor
        current = getattr(btn, '_color', QColor(200, 200, 200))
        color = QColorDialog.getColor(current, self, "Select View Color")
        if color.isValid():
            btn._color = color
            btn.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid #666;")

    def get_view_names(self) -> list:
        names = []
        for editor, _, _ in self._editors:
            text = editor.text().strip()
            names.append(text if text else editor.placeholderText())
        return names

    def get_view_colors_hex(self) -> list:
        return [btn._color.name() for _, _, btn in self._editors]


# ==================== Wizard ====================

class StartupWizard(QWizard):
    """Three-page startup wizard returning (LayoutConfig, SessionMetadata)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Session Setup")
        self.setMinimumSize(560, 480)
        self.setWizardStyle(QWizard.ModernStyle)

        self.addPage(_LayoutPage())
        self.addPage(_MetadataPage())
        self.addPage(_ViewNamingPage())

    def get_results(self):
        """Call after exec() returns Accepted. Returns (LayoutConfig, SessionMetadata)."""
        layout_page: _LayoutPage = self.page(0)
        meta_page: _MetadataPage = self.page(1)
        naming_page: _ViewNamingPage = self.page(2)

        config = layout_page.get_layout_config()
        config.view_names = naming_page.get_view_names()

        metadata = meta_page.get_metadata()
        return config, metadata
