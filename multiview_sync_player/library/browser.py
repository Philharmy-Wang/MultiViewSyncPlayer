"""multiview_sync_player.library.browser — 左侧导航 LibraryBrowserDock。

提供 Experiment > Date > Subject > View 四层树形浏览、
实时模糊搜索、右键菜单、双击打开。
"""

import datetime
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtGui import QStandardItemModel, QStandardItem

from .index import LibraryIndex, load_index, rebuild_index
from .schema import DateEntry, ExperimentEntry, SubjectEntry, ViewEntry

# ---------------------------------------------------------------------------
# Node roles
# ---------------------------------------------------------------------------

# Data stored at Qt.UserRole + 1
_NODE_ENTRY_ROLE = Qt.UserRole + 1

# Level identifiers stored at Qt.UserRole + 2
LEVEL_EXPERIMENT = "experiment"
LEVEL_DATE = "date"
LEVEL_SUBJECT = "subject"
LEVEL_VIEW = "view"

_LEVEL_ROLE = Qt.UserRole + 2

# Icons per level
_LEVEL_ICONS = {
    LEVEL_EXPERIMENT: "\U0001f9ea",  # 🧪
    LEVEL_DATE: "\U0001f4c5",        # 📅
    LEVEL_SUBJECT: "\U0001f412",     # 🐒
    LEVEL_VIEW: "\U0001f3ac",        # 🎬
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_descendants(entry) -> str:
    """返回次级计数摘要字符串。"""
    if isinstance(entry, ExperimentEntry):
        n_dates = len(entry.dates)
        n_subj = sum(len(d.subjects) for d in entry.dates)
        return f"({n_dates} 日期, {n_subj} 个体)"
    if isinstance(entry, DateEntry):
        n = len(entry.subjects)
        return f"({n} 个体)"
    if isinstance(entry, SubjectEntry):
        n = len(entry.views)
        return f"({n} 视角)"
    return ""


def _make_item(text: str, entry, level: str) -> QStandardItem:
    """构建单行 QStandardItem，携带 entry / level 数据。"""
    icon = _LEVEL_ICONS.get(level, "")
    label = f"{icon} {text}" if icon else text
    item = QStandardItem(label)
    item.setData(entry, _NODE_ENTRY_ROLE)
    item.setData(level, _LEVEL_ROLE)
    item.setEditable(False)
    return item


# ---------------------------------------------------------------------------
# Tree model builder
# ---------------------------------------------------------------------------


def _build_model(index: LibraryIndex) -> QStandardItemModel:
    """从 LibraryIndex 构建四层 QStandardItemModel。"""
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(["媒体库"])
    root = model.invisibleRootItem()

    for exp in index.experiments:
        exp_text = f"{exp.name}  {_count_descendants(exp)}"
        exp_item = _make_item(exp_text, exp, LEVEL_EXPERIMENT)

        for date_entry in exp.dates:
            date_text = f"{date_entry.date.isoformat()}  {_count_descendants(date_entry)}"
            date_item = _make_item(date_text, date_entry, LEVEL_DATE)

            for subj in date_entry.subjects:
                subj_text = f"{subj.subject_id}  {_count_descendants(subj)}"
                subj_item = _make_item(subj_text, subj, LEVEL_SUBJECT)

                for view in subj.views:
                    view_text = view.name
                    view_item = _make_item(view_text, view, LEVEL_VIEW)
                    subj_item.appendRow(view_item)

                date_item.appendRow(subj_item)
            exp_item.appendRow(date_item)
        root.appendRow(exp_item)

    return model


# ---------------------------------------------------------------------------
# Fuzzy filter proxy
# ---------------------------------------------------------------------------


class _FuzzyFilterProxy(QSortFilterProxyModel):
    """跨层级模糊匹配：如果后代匹配则保留整条路径。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pattern = ""

    def set_pattern(self, text: str):
        self._pattern = text.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        if not self._pattern:
            return True
        return self._accepts_row_recursive(source_row, source_parent)

    def _accepts_row_recursive(self, row, parent) -> bool:
        idx = self.sourceModel().index(row, 0, parent)
        if not idx.isValid():
            return False
        # 检查当前节点文本
        text = idx.data(Qt.DisplayRole)
        if text and self._pattern in text.lower():
            return True
        # 检查后代
        child_count = self.sourceModel().rowCount(idx)
        for r in range(child_count):
            if self._accepts_row_recursive(r, idx):
                return True
        return False


# ---------------------------------------------------------------------------
# LibraryBrowserDock
# ---------------------------------------------------------------------------


class LibraryBrowserDock(QDockWidget):
    """左侧媒体库浏览器。"""

    open_subject = Signal(SubjectEntry)
    open_view = Signal(ViewEntry)
    import_requested = Signal()
    library_root_changed = Signal(Path)

    def __init__(self, parent=None):
        super().__init__("媒体库", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)

        self._library_root: Optional[Path] = None
        self._index: Optional[LibraryIndex] = None
        self._model: Optional[QStandardItemModel] = None
        self._proxy = _FuzzyFilterProxy(self)

        self._build_ui()

    # ---- UI ----

    def _build_ui(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        btn_open = QToolButton()
        btn_open.setText("\U0001f4c2 打开库")
        btn_open.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_open.clicked.connect(self._on_open_library)
        toolbar.addWidget(btn_open)

        btn_refresh = QToolButton()
        btn_refresh.setText("\U0001f504 刷新")
        btn_refresh.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_refresh.clicked.connect(self._on_refresh)
        toolbar.addWidget(btn_refresh)

        btn_import = QToolButton()
        btn_import.setText("\u2795 导入")
        btn_import.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_import.clicked.connect(self.import_requested.emit)
        toolbar.addWidget(btn_import)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # 搜索框
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 搜索...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._proxy.set_pattern)
        self._search.returnPressed.connect(self._on_search_return)
        layout.addWidget(self._search)

        # 树
        self._tree = QTreeView()
        self._tree.setHeaderHidden(True)
        self._tree.setDragEnabled(False)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.doubleClicked.connect(self._on_double_click)
        self._tree.setEditTriggers(QTreeView.NoEditTriggers)
        self._tree.setUniformRowHeights(True)
        self._tree.setModel(self._proxy)
        layout.addWidget(self._tree, 1)

        self.setWidget(container)

    # ---- Public API ----

    def set_library_root(self, root: Path):
        """设置库根目录并加载索引。"""
        root = Path(root)
        if not root.is_dir():
            return
        self._library_root = root
        self._index = rebuild_index(root)
        self._model = _build_model(self._index)
        self._proxy.setSourceModel(self._model)
        self._proxy.set_pattern("")
        self._search.clear()
        self._tree.expandToDepth(0)
        self.library_root_changed.emit(root)

    def library_root(self) -> Optional[Path]:
        return self._library_root

    def current_index(self) -> Optional[LibraryIndex]:
        return self._index

    def refresh(self):
        """刷新当前库索引。"""
        if self._library_root:
            self.set_library_root(self._library_root)

    # ---- Slots ----

    def _on_open_library(self):
        start_dir = str(self._library_root) if self._library_root else ""
        path = QFileDialog.getExistingDirectory(self, "选择媒体库目录", start_dir)
        if path:
            self.set_library_root(Path(path))

    def _on_refresh(self):
        if not self._library_root:
            QMessageBox.information(self, "提示", "请先打开一个媒体库。")
            return
        self.refresh()

    def _on_search_return(self):
        """回车定位到首个匹配项。"""
        proxy = self._proxy
        for row in range(proxy.rowCount()):
            idx = proxy.index(row, 0)
            self._tree.setExpanded(idx, True)
            self._tree.scrollTo(idx)
            self._tree.setCurrentIndex(idx)
            return

    def _on_double_click(self, proxy_idx):
        entry, level = self._entry_at(proxy_idx)
        if level == LEVEL_VIEW and isinstance(entry, ViewEntry):
            self.open_view.emit(entry)
        elif level == LEVEL_SUBJECT and isinstance(entry, SubjectEntry):
            self.open_subject.emit(entry)

    def _on_context_menu(self, pos):
        proxy_idx = self._tree.indexAt(pos)
        if not proxy_idx.isValid():
            return
        entry, level = self._entry_at(proxy_idx)
        if entry is None:
            return

        menu = QMenu(self)

        if level == LEVEL_VIEW:
            menu.addAction("在播放器打开此视频", lambda: self.open_view.emit(entry))
            menu.addAction("在资源管理器中显示", lambda: self._reveal_file(entry))
            menu.addSeparator()
            menu.addAction("重命名", lambda: self._rename_node(proxy_idx))
            menu.addAction("删除", lambda: self._delete_node(proxy_idx))

        elif level == LEVEL_SUBJECT:
            menu.addAction("\U0001f3ac 打开所有视频", lambda: self.open_subject.emit(entry))
            menu.addAction("打开文件夹", lambda: self._open_subject_dir(entry))
            menu.addSeparator()
            menu.addAction("重命名", lambda: self._rename_node(proxy_idx))
            menu.addAction("删除", lambda: self._delete_node(proxy_idx))

        elif level in (LEVEL_DATE, LEVEL_EXPERIMENT):
            menu.addAction("打开文件夹", lambda: self._open_folder(entry, level))
            menu.addSeparator()
            menu.addAction("重命名", lambda: self._rename_node(proxy_idx))
            menu.addAction("删除", lambda: self._delete_node(proxy_idx))

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    # ---- Helpers ----

    def _entry_at(self, proxy_idx):
        """从 proxy index 取 (entry, level)。"""
        source_idx = self._proxy.mapToSource(proxy_idx)
        entry = source_idx.data(_NODE_ENTRY_ROLE)
        level = source_idx.data(_LEVEL_ROLE)
        return entry, level

    def _resolve_absolute(self, rel_path: Path) -> Optional[Path]:
        if not self._library_root:
            return None
        abs_path = self._library_root / rel_path
        return abs_path if abs_path.exists() else None

    def _reveal_file(self, view: ViewEntry):
        abs_path = self._resolve_absolute(view.video_path)
        if abs_path:
            self._show_in_explorer(abs_path)

    def _open_subject_dir(self, subject: SubjectEntry):
        if not subject.views:
            return
        # 向上定位到 subject 文件夹
        abs_path = self._resolve_absolute(subject.views[0].video_path)
        if abs_path:
            self._show_in_explorer(abs_path.parent)

    def _open_folder(self, entry, level: str):
        if level == LEVEL_DATE and isinstance(entry, DateEntry):
            if not self._library_root:
                return
            # 需要从父节点获取 experiment 名
            # 简化处理：尝试扫描
            QMessageBox.information(self, "提示", "请在资源管理器中手动定位。")
        elif level == LEVEL_EXPERIMENT and isinstance(entry, ExperimentEntry):
            if self._library_root:
                exp_dir = self._library_root / entry.name
                if exp_dir.exists():
                    self._show_in_explorer(exp_dir)

    def _show_in_explorer(self, path: Path):
        import subprocess
        import platform
        path_str = str(path)
        system = platform.system()
        try:
            if system == "Windows":
                subprocess.Popen(f'explorer /select,"{path_str}"')
            elif system == "Darwin":
                subprocess.Popen(["open", "-R", path_str])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except Exception:
            pass

    def _rename_node(self, proxy_idx):
        from PySide6.QtWidgets import QInputDialog
        entry, level = self._entry_at(proxy_idx)
        if entry is None:
            return

        if level == LEVEL_VIEW:
            old_name = entry.name
        elif level == LEVEL_SUBJECT:
            old_name = entry.subject_id
        elif level == LEVEL_DATE:
            old_name = entry.date.isoformat()
        else:
            old_name = entry.name

        new_name, ok = QInputDialog.getText(
            self, "重命名", f"新名称:", text=old_name)
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        QMessageBox.information(self, "重命名",
                                "重命名功能将在后续版本实现。")

    def _delete_node(self, proxy_idx):
        entry, level = self._entry_at(proxy_idx)
        if entry is None:
            return
        ret = QMessageBox.question(
            self, "确认删除",
            f"确定要删除此节点吗？\n此操作将在后续版本生效。",
            QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            # 将在后续版本实现文件系统操作
            pass


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------


def _build_mini_library(root: Path):
    """构建一个小型测试库。"""
    from .import_plan import ImportPlan, ViewMapping, autodetect_view_mappings
    from .executor import ImportExecutor

    raw = root / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    videos = ["前-1.mp4", "top.mp4", "cam03.mp4"]
    for v in videos:
        (raw / v).write_bytes(b"\x00" * 64)

    mappings = autodetect_view_mappings([raw / v for v in videos])
    plan = ImportPlan(
        library_root=root / "lib",
        experiment="ThreeChamber",
        date=datetime.date(2026, 1, 26),
        subject_id="24332",
        notes="browser test",
        view_mappings=mappings,
    )
    ImportExecutor(plan).run()

    # 第二个实验
    raw2 = root / "raw2"
    raw2.mkdir(parents=True, exist_ok=True)
    for v in ["left.mp4", "right.mp4"]:
        (raw2 / v).write_bytes(b"\x00" * 64)
    mappings2 = autodetect_view_mappings([raw2 / "left.mp4", raw2 / "right.mp4"])
    plan2 = ImportPlan(
        library_root=root / "lib",
        experiment="OpenField",
        date=datetime.date(2026, 2, 14),
        subject_id="Baboon-01",
        notes="second experiment",
        view_mappings=mappings2,
    )
    ImportExecutor(plan2).run()

    return root / "lib"


def main():
    """python -m multiview_sync_player.library.browser"""
    import tempfile
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    # 构建测试库
    tmp = Path(tempfile.mkdtemp(prefix="mvsp_browser_test_"))
    lib_root = _build_mini_library(tmp)

    from PySide6.QtWidgets import QMainWindow
    win = QMainWindow()
    dock = LibraryBrowserDock(win)
    win.addDockWidget(Qt.LeftDockWidgetArea, dock)
    dock.set_library_root(lib_root)

    # 连接信号以便观察
    dock.open_view.connect(
        lambda v: print(f"[signal] open_view: {v.name} -> {v.video_path}"))
    dock.open_subject.connect(
        lambda s: print(f"[signal] open_subject: {s.subject_id} ({len(s.views)} views)"))
    dock.library_root_changed.connect(
        lambda p: print(f"[signal] library_root_changed: {p}"))

    win.setWindowTitle("LibraryBrowser 测试")
    win.resize(600, 500)
    win.show()

    import shutil
    app.aboutToQuit.connect(lambda: shutil.rmtree(tmp, ignore_errors=True))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
