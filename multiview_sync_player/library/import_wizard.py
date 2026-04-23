"""multiview_sync_player.library.import_wizard — Four-page import wizard (QWizard).

Pages:
    Meta    — library root, experiment name, date, subject ID, notes.
    Sources — drag-drop / file-picker list of video source files.
    Views   — placeholder (Step 3c).
    Review  — placeholder (Step 3c).

Input:  user interactions (dialog).
Output: ImportPlan via get_plan() on accepted.

Generated: 2026-04-23 21:30:00
"""

import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QDate, QMimeData, Qt, QUrl
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from .import_plan import ImportPlan, autodetect_view_mappings
from .paths import sanitize

# ---------------------------------------------------------------------------
# Video extension filter
# ---------------------------------------------------------------------------

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm", ".flv", ".wmv"}


def _is_video(p: Path) -> bool:
    return p.suffix.lower() in VIDEO_EXTS


# ---------------------------------------------------------------------------
# Placeholder page (for pages implemented in Step 3c)
# ---------------------------------------------------------------------------


class PlaceholderPage(QWizardPage):
    """占位页：显示标题和描述文本，始终 isComplete=True。"""

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(description))
        self._complete = True

    def isComplete(self) -> bool:
        return True


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
# ImportWizard — top-level wizard
# ---------------------------------------------------------------------------


class ImportWizard(QWizard):
    """四页导入向导：Meta → Sources → Views（占位）→ Review（占位）。

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
        self.setPage(
            self.PAGE_VIEWS,
            PlaceholderPage(
                "视角映射", "Step 3c 将实现此页（视角名、方向、颜色映射表）"
            ),
        )
        self.setPage(
            self.PAGE_REVIEW,
            PlaceholderPage(
                "确认 & 执行", "Step 3c 将实现此页（冲突策略、拷贝模式、预览）"
            ),
        )

    def get_plan(self) -> ImportPlan:
        """从已填字段构造 ImportPlan。

        view_mappings 通过 autodetect_view_mappings 默认填充。
        conflict_policy='skip'，copy_mode='copy'。
        """
        meta: MetaPage = self.page(self.PAGE_META)
        sources_page: SourcesPage = self.page(self.PAGE_SOURCES)

        root = Path(self.field("library_root") or meta._root_edit.text())
        exp = self.field("experiment") or meta._exp_edit.text()
        qdate: QDate = meta._date_edit.date()
        date = datetime.date(qdate.year(), qdate.month(), qdate.day())
        subj = self.field("subject_id") or meta._subj_edit.text()
        notes = self.field("notes") or meta._notes_edit.toPlainText() or ""

        mappings = autodetect_view_mappings(sources_page.sources())

        return ImportPlan(
            library_root=root,
            experiment=exp,
            date=date,
            subject_id=subj,
            notes=notes,
            view_mappings=mappings,
            conflict_policy="skip",
            copy_mode="copy",
        )
