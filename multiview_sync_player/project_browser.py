"""
multiview_sync_player.project_browser — 项目模板浏览器对话框

显示扫描结果分组列表，支持选择一组加载到会话。
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QTreeWidget,
    QTreeWidgetItem, QLabel, QLineEdit, QPushButton, QCheckBox, QFrame,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from .config import COLOR_PANEL_BG, COLOR_TEXT, COLOR_ACCENT
from .project_template import ProjectTemplate, GroupEntry


class ProjectBrowser(QDialog):
    """项目模板浏览器：扫描结果分组选择。"""

    entry_chosen = Signal(object, object)  # (ProjectTemplate, GroupEntry)

    def __init__(self, template: ProjectTemplate, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"项目模板 — {template.name}")
        self.setMinimumSize(900, 640)
        self.resize(960, 660)
        self._template = template
        self._entries: list = []
        self._current_entry: GroupEntry | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ---- 顶部信息 ----
        self.lbl_title = QLabel(f"<b>{template.name}</b>")
        self.lbl_title.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 12pt;")
        self.lbl_title.setWordWrap(True)
        layout.addWidget(self.lbl_title)

        if template.description:
            desc = QLabel(template.description)
            desc.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 9pt;")
            desc.setWordWrap(True)
            layout.addWidget(desc)

        # ---- 根目录行 ----
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("根目录:"))
        self.edit_root = QLineEdit(template.root_dir)
        self.edit_root.setPlaceholderText("选择视频所在根目录...")
        dir_row.addWidget(self.edit_root, 1)

        btn_browse = QPushButton("📂 浏览")
        btn_browse.clicked.connect(self._on_browse)
        dir_row.addWidget(btn_browse)

        btn_rescan = QPushButton("🔄 重新扫描")
        btn_rescan.clicked.connect(self._do_scan)
        dir_row.addWidget(btn_rescan)
        layout.addLayout(dir_row)

        # ---- 中部分割器 ----
        splitter = QSplitter(Qt.Horizontal)

        self.list_groups = QListWidget()
        self.list_groups.currentRowChanged.connect(self._on_group_selected)
        self.list_groups.itemDoubleClicked.connect(self._on_load_clicked)
        splitter.addWidget(self.list_groups)

        self.tree_views = QTreeWidget()
        self.tree_views.setHeaderLabels(["视角", "状态", "文件路径"])
        self.tree_views.setColumnWidth(0, 120)
        self.tree_views.setColumnWidth(1, 60)
        splitter.addWidget(self.tree_views)

        splitter.setSizes([300, 600])
        layout.addWidget(splitter, 1)

        # ---- 底部 ----
        bottom_row = QHBoxLayout()

        self.chk_complete = QCheckBox("仅显示完整组")
        self.chk_complete.setChecked(False)
        self.chk_complete.stateChanged.connect(self._do_scan)
        bottom_row.addWidget(self.chk_complete)

        bottom_row.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(btn_cancel)

        self.btn_load = QPushButton("🚀 加载所选到会话")
        self.btn_load.clicked.connect(self._on_load_clicked)
        bottom_row.addWidget(self.btn_load)

        layout.addLayout(bottom_row)

        # 初始扫描
        self._do_scan()

    # ---- 扫描 ----

    def _do_scan(self):
        root = self.edit_root.text().strip()
        self._template.root_dir = root
        all_entries = self._template.scan(root)

        if self.chk_complete.isChecked():
            self._entries = [e for e in all_entries if e.complete]
        else:
            self._entries = all_entries

        self.list_groups.clear()
        self.tree_views.clear()
        self._current_entry = None

        for entry in self._entries:
            check_marks = "".join(
                "✓" if v not in entry.missing_views else "✗"
                for v in [p.view_name for p in self._template.patterns])
            text = f"{entry.display_key}   {check_marks}"
            self.list_groups.addItem(text)

        # 灰色不完整组
        for i, entry in enumerate(self._entries):
            if not entry.complete:
                item = self.list_groups.item(i)
                item.setForeground(Qt.gray)

        if self._entries:
            self.list_groups.setCurrentRow(0)

    def _on_browse(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择视频根目录", self.edit_root.text())
        if path:
            self.edit_root.setText(path)
            self._do_scan()

    # ---- 选择 ----

    def _on_group_selected(self, row):
        self.tree_views.clear()
        if row < 0 or row >= len(self._entries):
            self._current_entry = None
            return
        entry = self._entries[row]
        self._current_entry = entry
        all_vnames = [p.view_name for p in self._template.patterns]
        for vn in all_vnames:
            item = QTreeWidgetItem()
            item.setText(0, vn)
            if vn in entry.videos:
                item.setText(1, "✓")
                item.setText(2, entry.videos[vn])
            else:
                item.setText(1, "✗ 缺失")
                item.setText(2, "—")
                item.setForeground(1, Qt.red)
            self.tree_views.addTopLevelItem(item)

    # ---- 加载 ----

    def _on_load_clicked(self):
        if self._current_entry is None:
            QMessageBox.information(self, "未选择", "请先选择一个分组。")
            return
        self.entry_chosen.emit(self._template, self._current_entry)
        self.accept()
