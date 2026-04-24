"""multiview_sync_player.library.import_wizard — Four-page import wizard (QWizard).

Pages:
    Meta    — library root, experiment name, date, subject ID, notes.
    Sources — drag-drop / file-picker list of video source files.
    Views   — editable direction / index / colour mapping table.
    Review  — conflict/copy-mode selection, ASCII preview, validation.

Input:  user interactions (dialog).
Output: ImportPlan via get_plan() on accepted.

Generated: 2026-04-23 22:00:00
"""

import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QDate, QMimeData, Qt, QUrl
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from .import_plan import ImportPlan, ViewMapping, autodetect_view_mappings, render_plan_preview
from .paths import sanitize

# ---------------------------------------------------------------------------
# Video extension filter
# ---------------------------------------------------------------------------

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm", ".flv", ".wmv"}


def _is_video(p: Path) -> bool:
    return p.suffix.lower() in VIDEO_EXTS


# ---------------------------------------------------------------------------
# MetaPage — experiment metadata
# ---------------------------------------------------------------------------


class MetaPage(QWizardPage):
    """第一页：库根目录 / 实验名 / 日期 / 个体 ID / 备注。"""

    def __init__(self, default_library_root: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.setTitle("实验元数据")
        self.setSubTitle("填写导入目标的基础信息。")

        form = QFormLayout(self)

        # Library root
        root_row = QHBoxLayout()
        self._root_edit = QLineEdit()
        if default_library_root:
            self._root_edit.setText(str(default_library_root))
        root_row.addWidget(self._root_edit, 1)
        root_btn = QPushButton("浏览...")
        root_btn.clicked.connect(self._browse_root)
        root_row.addWidget(root_btn)
        form.addRow("库根目录 (*):", root_row)
        self.registerField("library_root*", self._root_edit)

        # Experiment name
        self._exp_edit = QLineEdit()
        form.addRow("实验名 (*):", self._exp_edit)
        self.registerField("experiment*", self._exp_edit)

        # Date
        self._date_edit = self._create_date_edit()
        form.addRow("日期 (*):", self._date_edit)
        self.registerField("date", self._date_edit, "date")

        # Subject ID
        self._subj_edit = QLineEdit()
        form.addRow("个体 ID (*):", self._subj_edit)
        self.registerField("subject_id*", self._subj_edit)

        # Notes
        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setMaximumHeight(80)
        form.addRow("备注:", self._notes_edit)
        self.registerField("notes", self._notes_edit, "plainText")

        # Connect changes
        for w in (self._root_edit, self._exp_edit, self._subj_edit):
            w.textChanged.connect(self.completeChanged)
        self._date_edit.dateChanged.connect(self.completeChanged)

    @staticmethod
    def _create_date_edit():
        from PySide6.QtWidgets import QDateEdit

        de = QDateEdit()
        de.setCalendarPopup(True)
        de.setDisplayFormat("yyyy-MM-dd")
        de.setDate(QDate.currentDate())
        return de

    def _browse_root(self):
        d = QFileDialog.getExistingDirectory(self, "选择库根目录")
        if d:
            self._root_edit.setText(d)

    def isComplete(self) -> bool:
        root = self._root_edit.text().strip()
        if not root or not Path(root).is_absolute():
            return False
        exp = self._exp_edit.text().strip()
        if not exp or not sanitize(exp):
            return False
        subj = self._subj_edit.text().strip()
        if not subj or not sanitize(subj):
            return False
        return True


# ---------------------------------------------------------------------------
# SourcesPage — video file selection
# ---------------------------------------------------------------------------


class SourcesPage(QWizardPage):
    """第二页：源视频文件列表（拖拽 / 文件选择）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("选择源视频")
        self.setSubTitle("添加要导入的视频文件（支持拖拽）。")
        self.setAcceptDrops(True)

        layout = QHBoxLayout(self)

        # Left: file list
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.ExtendedSelection)
        self._list.model().rowsInserted.connect(self.completeChanged)
        self._list.model().rowsRemoved.connect(self.completeChanged)
        layout.addWidget(self._list, 1)

        # Right: buttons
        btn_col = QVBoxLayout()
        add_btn = QPushButton("添加文件")
        add_btn.clicked.connect(self._add_files)
        btn_col.addWidget(add_btn)

        dir_btn = QPushButton("添加文件夹")
        dir_btn.clicked.connect(self._add_folder)
        btn_col.addWidget(dir_btn)

        rm_btn = QPushButton("移除选中")
        rm_btn.clicked.connect(self._remove_selected)
        btn_col.addWidget(rm_btn)

        clr_btn = QPushButton("清空")
        clr_btn.clicked.connect(self._clear_all)
        btn_col.addWidget(clr_btn)

        btn_col.addStretch(1)
        layout.addLayout(btn_col)

    # -- public helpers used by tests & get_plan --

    def sources(self) -> List[Path]:
        """返回当前列表中所有源文件路径。"""
        result = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            result.append(item.data(Qt.UserRole))
        return result

    def _add_paths(self, paths: List[Path]) -> None:
        """向列表追加文件路径（去重）。"""
        existing = set(self.sources())
        for p in paths:
            if p not in existing:
                existing.add(p)
                item = QListWidgetItem(p.name)
                item.setData(Qt.UserRole, p)
                item.setToolTip(str(p))
                self._list.addItem(item)

    # -- button handlers --

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择视频文件",
            "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.m4v *.webm *.flv *.wmv);;所有文件 (*)",
        )
        if files:
            self._add_paths([Path(f) for f in files])

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择视频文件夹")
        if d:
            root = Path(d)
            videos = sorted(p for p in root.rglob("*") if _is_video(p))
            self._add_paths(videos)

    def _remove_selected(self):
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))

    def _clear_all(self):
        self._list.clear()

    # -- drag & drop --

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls: list[QUrl] = event.mimeData().urls()
        paths: List[Path] = []
        for url in urls:
            p = Path(url.toLocalFile())
            if p.is_file() and _is_video(p):
                paths.append(p)
            elif p.is_dir():
                paths.extend(
                    sorted(q for q in p.rglob("*") if _is_video(q))
                )
        self._add_paths(paths)
        event.acceptProposedAction()

    # -- completeness --

    def isComplete(self) -> bool:
        return self._list.count() > 0


# ---------------------------------------------------------------------------
# ViewsPage — direction / index / colour mapping table
# ---------------------------------------------------------------------------

COL_SOURCE, COL_VIEW, COL_DIR, COL_IDX, COL_COLOR, COL_INCL = range(6)
_DIR_OPTIONS = ["", "front", "back", "left", "right", "top", "bottom"]


class ViewsPage(QWizardPage):
    """第三页：视角名 / 方向 / 编号 / 颜色映射表。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("视角映射")
        self.setSubTitle("确认或编辑每个视角的方向、编号和颜色。")

        layout = QVBoxLayout(self)

        # Toolbar row
        tb = QHBoxLayout()
        auto_btn = QPushButton("自动推断")
        auto_btn.clicked.connect(self._on_autodetect)
        tb.addWidget(auto_btn)
        self._count_label = QLabel("已导入 0 / 0")
        tb.addWidget(self._count_label)
        tb.addStretch(1)
        layout.addLayout(tb)

        # Table
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["源文件", "视角名", "方向", "编号", "颜色", "包含"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self._table)

    # -- lifecycle --

    def initializePage(self):
        sources_page: SourcesPage = self.wizard().page(
            ImportWizard.PAGE_SOURCES
        )
        sources = sources_page.sources()
        mappings = autodetect_view_mappings(sources)
        self._load_mappings(mappings)

    # -- data helpers --

    def _load_mappings(self, mappings: List[ViewMapping]):
        self._table.setRowCount(len(mappings))
        for row, m in enumerate(mappings):
            # Source (read-only)
            src_item = QTableWidgetItem(m.source.name)
            src_item.setFlags(src_item.flags() & ~Qt.ItemIsEditable)
            src_item.setToolTip(str(m.source))
            src_item.setData(Qt.UserRole, m.source)
            self._table.setItem(row, COL_SOURCE, src_item)

            # View name (editable)
            view_item = QTableWidgetItem(m.view_name)
            self._table.setItem(row, COL_VIEW, view_item)

            # Direction combo
            combo = QComboBox()
            combo.addItems(_DIR_OPTIONS)
            idx = _DIR_OPTIONS.index(m.direction) if m.direction in _DIR_OPTIONS else 0
            combo.setCurrentIndex(idx)
            self._table.setCellWidget(row, COL_DIR, combo)

            # Index spinbox (0 = None)
            spin = QSpinBox()
            spin.setRange(0, 99)
            spin.setValue(m.index if m.index is not None else 0)
            spin.setSpecialValueText("—")
            self._table.setCellWidget(row, COL_IDX, spin)

            # Colour button
            color_btn = QPushButton(m.color or "—")
            if m.color:
                color_btn.setStyleSheet(
                    f"background-color: {m.color}; color: white;"
                )
            color_btn.setProperty("_hex", m.color or "")
            color_btn.clicked.connect(lambda checked, r=row: self._pick_color(r))
            self._table.setCellWidget(row, COL_COLOR, color_btn)

            # Include checkbox (centred via wrapper widget)
            chk = QCheckBox()
            chk.setChecked(m.include)
            chk_wrapper = QWidget()
            chk_layout = QHBoxLayout(chk_wrapper)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(row, COL_INCL, chk_wrapper)

            # Connect per-row changes
            combo.currentIndexChanged.connect(self._on_cell_changed)
            spin.valueChanged.connect(self._on_cell_changed)
            chk.stateChanged.connect(self._on_cell_changed)
            view_item.dataChanged = None  # we use itemChanged signal below

        self._table.itemChanged.connect(self._on_table_item_changed)
        self._update_count()

    def _on_table_item_changed(self, item):
        self.completeChanged.emit()
        self._update_count()

    def _on_cell_changed(self):
        self.completeChanged.emit()
        self._update_count()

    def _update_count(self):
        ms = self.view_mappings()
        included = sum(1 for m in ms if m.include)
        self._count_label.setText(f"已导入 {included} / {len(ms)}")

    def _on_autodetect(self):
        sources_page: SourcesPage = self.wizard().page(
            ImportWizard.PAGE_SOURCES
        )
        sources = sources_page.sources()
        mappings = autodetect_view_mappings(sources)
        self._load_mappings(mappings)

    def _pick_color(self, row: int):
        btn: QPushButton = self._table.cellWidget(row, COL_COLOR)
        current = btn.property("_hex") or "#ffffff"
        color = QColorDialog.getColor(QColor(current), self, "选择视角颜色")
        if color.isValid():
            hex_str = color.name()
            btn.setText(hex_str)
            btn.setStyleSheet(f"background-color: {hex_str}; color: white;")
            btn.setProperty("_hex", hex_str)
            self.completeChanged.emit()

    def view_mappings(self) -> List[ViewMapping]:
        """从表格读回当前状态，构造 List[ViewMapping]。"""
        result: List[ViewMapping] = []
        for row in range(self._table.rowCount()):
            src_item = self._table.item(row, COL_SOURCE)
            source: Path = src_item.data(Qt.UserRole)

            view_item = self._table.item(row, COL_VIEW)
            view_name = view_item.text() if view_item else source.stem

            combo: QComboBox = self._table.cellWidget(row, COL_DIR)
            direction = combo.currentText() or None

            spin: QSpinBox = self._table.cellWidget(row, COL_IDX)
            index = spin.value() if spin.value() > 0 else None

            color_btn: QPushButton = self._table.cellWidget(row, COL_COLOR)
            color = color_btn.property("_hex") or None

            chk_wrapper = self._table.cellWidget(row, COL_INCL)
            chk = chk_wrapper.findChild(QCheckBox)
            include = chk.isChecked() if chk else True

            result.append(
                ViewMapping(
                    source=source,
                    view_name=view_name,
                    direction=direction,
                    index=index,
                    color=color,
                    include=include,
                )
            )
        return result

    def isComplete(self) -> bool:
        ms = self.view_mappings()
        included = [m for m in ms if m.include]
        if not included:
            return False
        for m in included:
            if not sanitize(m.view_name).strip():
                return False
        return True


# ---------------------------------------------------------------------------
# ReviewPage — conflict / copy-mode, preview, validation
# ---------------------------------------------------------------------------

_CONFLICT_ITEMS = [
    ("跳过 (skip)", "skip"),
    ("重命名 (rename)", "rename"),
    ("覆盖 (overwrite)", "overwrite"),
]
_COPY_ITEMS = [
    ("拷贝 (copy)", "copy"),
    ("硬链接 (hardlink)", "hardlink"),
    ("移动 (move)", "move"),
]


class ReviewPage(QWizardPage):
    """第四页：确认策略、预览、校验。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("确认 & 执行")
        self.setSubTitle("检查导入预览，选择冲突策略和拷贝模式。")
        self._plan: Optional[ImportPlan] = None

        layout = QVBoxLayout(self)

        # Strategy combos
        form = QFormLayout()

        self._conflict_combo = QComboBox()
        for label, value in _CONFLICT_ITEMS:
            self._conflict_combo.addItem(label, value)
        self._conflict_combo.currentIndexChanged.connect(self._on_policy_changed)
        form.addRow("冲突策略:", self._conflict_combo)

        self._copy_combo = QComboBox()
        for label, value in _COPY_ITEMS:
            self._copy_combo.addItem(label, value)
        self._copy_combo.currentIndexChanged.connect(self._on_policy_changed)
        form.addRow("拷贝模式:", self._copy_combo)

        layout.addLayout(form)

        # Preview
        self._text = QTextBrowser()
        self._text.setFont(QFont("Consolas", 10))
        self._text.setMaximumHeight(220)
        layout.addWidget(self._text)

        # Size estimate
        self._size_label = QLabel("预计占用 —")
        layout.addWidget(self._size_label)

        # Validation errors
        self._err_label = QLabel("—")
        layout.addWidget(self._err_label)

    def initializePage(self):
        self._plan = self.wizard()._build_plan_from_pages()
        # Apply combo selections
        self._plan.conflict_policy = self._conflict_combo.currentData()
        self._plan.copy_mode = self._copy_combo.currentData()
        self._refresh()

    def _on_policy_changed(self):
        if self._plan is None:
            return
        self._plan.conflict_policy = self._conflict_combo.currentData()
        self._plan.copy_mode = self._copy_combo.currentData()
        self._refresh()

    def _refresh(self):
        preview = render_plan_preview(self._plan)
        self._text.setPlainText(preview)

        # Size estimate
        total_bytes = 0
        file_count = 0
        for m in self._plan.view_mappings:
            if m.include:
                try:
                    total_bytes += m.source.stat().st_size
                    file_count += 1
                except OSError:
                    pass
        if file_count:
            gb = total_bytes / (1024 ** 3)
            self._size_label.setText(f"预计占用 {gb:.2f} GB（{file_count} 个文件）")
        else:
            self._size_label.setText("预计占用 —")

        # Validation
        errs = self._plan.validate()
        if errs:
            self._err_label.setText("\n".join(f"• {e}" for e in errs))
            self._err_label.setStyleSheet("color: #c62828;")
        else:
            self._err_label.setText("—")
            self._err_label.setStyleSheet("")

        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._plan is not None and self._plan.validate() == []


# ---------------------------------------------------------------------------
# ImportWizard — top-level wizard
# ---------------------------------------------------------------------------


class ImportWizard(QWizard):
    """四页导入向导：Meta → Sources → Views → Review。

    >>> import os; os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    """

    PAGE_META, PAGE_SOURCES, PAGE_VIEWS, PAGE_REVIEW = range(4)

    def __init__(self, parent=None, default_library_root: Optional[Path] = None):
        super().__init__(parent)
        self.setWindowTitle("导入到媒体库")
        self.resize(820, 560)

        # Chinese button labels
        self.setButtonText(QWizard.BackButton, "上一步")
        self.setButtonText(QWizard.NextButton, "下一步")
        self.setButtonText(QWizard.FinishButton, "完成导入")
        self.setButtonText(QWizard.CancelButton, "取消")

        # Register pages
        self.setPage(self.PAGE_META, MetaPage(default_library_root))
        self.setPage(self.PAGE_SOURCES, SourcesPage())
        self.setPage(self.PAGE_VIEWS, ViewsPage())
        self.setPage(self.PAGE_REVIEW, ReviewPage())

    def _build_plan_from_pages(self) -> ImportPlan:
        """从各页字段构造 ImportPlan（供 ReviewPage / get_plan 调用）。"""
        meta: MetaPage = self.page(self.PAGE_META)
        views: ViewsPage = self.page(self.PAGE_VIEWS)

        root = Path(self.field("library_root") or meta._root_edit.text())
        exp = self.field("experiment") or meta._exp_edit.text()
        qdate: QDate = meta._date_edit.date()
        date = datetime.date(qdate.year(), qdate.month(), qdate.day())
        subj = self.field("subject_id") or meta._subj_edit.text()
        notes = self.field("notes") or meta._notes_edit.toPlainText() or ""

        mappings = views.view_mappings()

        # Fallback: if ViewsPage was never initialised, autodetect from sources
        if not mappings:
            sources_page: SourcesPage = self.page(self.PAGE_SOURCES)
            mappings = autodetect_view_mappings(sources_page.sources())

        # Read combos from ReviewPage if initialised, else defaults
        review: Optional[ReviewPage] = self.page(self.PAGE_REVIEW)
        conflict = "skip"
        copy_mode = "copy"
        if review and review._plan is not None:
            conflict = review._conflict_combo.currentData()
            copy_mode = review._copy_combo.currentData()

        return ImportPlan(
            library_root=root,
            experiment=exp,
            date=date,
            subject_id=subj,
            notes=notes,
            view_mappings=mappings,
            conflict_policy=conflict,
            copy_mode=copy_mode,
        )

    def get_plan(self) -> ImportPlan:
        """从已填字段构造 ImportPlan。"""
        return self._build_plan_from_pages()
