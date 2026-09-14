"""
multiview_sync_player.main_window — 主窗口

可配置网格 + 全局工具栏 + 元数据栏 + 状态栏。
管理 VideoCell 生命周期，连接信号。
支持同步锁控制、手动视频选择、会话管理、可配置布局、启动向导。
播放采用消费者 pull 模式：定时器 tick 从各解码线程缓冲区取帧。
"""

import json
import collections
import os
import shutil
import tempfile
from pathlib import Path
from time import perf_counter

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox,
    QStatusBar, QFileDialog, QDialog, QMenu, QMenuBar, QLabel, QFrame,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QSettings
from PySide6.QtGui import QShortcut, QKeySequence, QAction

from .config import (
    SPEED_STEPS, PLAYER_CONFIG_PATH, SEEK_TIMEOUT_MS,
    INITIAL_SESSION_LOAD_TIMEOUT_MS,
    COLOR_PANEL_BG, COLOR_ACCENT, COLOR_TEXT, COLOR_TEXT_DIM,
    VIEW_COLORS,
)
from . import config as cfg
from .backend import choose_backend
from .styles import DARK_THEME_QSS
from .video_decoder import probe_video_metadata
from .sync_controller import SyncController
from .playback_sync import SeekBarrier
from .global_toolbar import GlobalToolbar
from .video_cell import VideoCell, DraggableHeader
from .metadata import SessionMetadata
from .layout_manager import LayoutConfig, fit_layout_to_views
from .session_io import (
    SessionData, save_session, load_session, detect_library_ref,
    SessionFormatError, SessionResolutionError, discover_legacy_video_manifests,
    resolve_session_videos,
)
from .library.browser import LibraryBrowserDock
from .library.import_wizard import ImportWizard
from .library.executor import ImportExecutor
from .library.schema import SubjectEntry, ViewEntry


class SessionLoadThread(QThread):
    """Resolve identities and probe media away from Qt's GUI thread."""

    progress = Signal(int, int, str)
    completed = Signal(int, object, object, str)

    def __init__(self, generation: int, data: SessionData, path: str, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.data = data
        self.path = path

    def run(self):
        try:
            discovered = discover_legacy_video_manifests(
                Path(self.path), self.data)
            if discovered != self.data.video_manifests:
                self.data.video_manifests = discovered
                MainWindow._add_cells_for_manifests(self.data)
            initial = resolve_session_videos(self.data, Path(self.path))
            actual = {}
            items = list(initial.items())
            total = len(items)
            for index, (view_name, item) in enumerate(items, 1):
                if self.isInterruptionRequested():
                    self.completed.emit(
                        self.generation, self.data, {}, "cancelled")
                    return
                self.progress.emit(index - 1, total, view_name)
                if item.path is not None:
                    actual[view_name] = probe_video_metadata(str(item.path))
                    self.data.video_manifests.setdefault(view_name, {}).update(
                        actual[view_name])
                    for cell in self.data.cells:
                        if cell.get("view_name") == view_name:
                            cell.update(actual[view_name])
                            cell["_metadata_probed"] = True
                            break
            resolutions = resolve_session_videos(
                self.data, Path(self.path), actual_metadata=actual)
            self.progress.emit(total, total, "")
            self.completed.emit(
                self.generation, self.data, resolutions, "")
        except Exception as exc:
            self.completed.emit(
                self.generation, self.data, {},
                f"{type(exc).__name__}: {exc}")


# ==================== 元数据栏 ====================

class MetadataBar(QFrame):
    """主窗口顶部的元数据摘要栏。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet(
            f"background-color: {COLOR_PANEL_BG}; "
            f"border-left: 3px solid {COLOR_ACCENT};")
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)

        icon = QLabel("📋")
        icon.setStyleSheet("background: transparent; font-size: 12pt;")
        layout.addWidget(icon)

        self.label = QLabel()
        self.label.setStyleSheet(
            f"background: transparent; color: {COLOR_TEXT}; font-size: 9pt;")
        self.label.setWordWrap(False)
        layout.addWidget(self.label, 1)

        self.btn_edit = QLabel("✏️ 编辑")
        self.btn_edit.setStyleSheet(
            f"background: transparent; color: {COLOR_ACCENT}; font-size: 9pt;")
        layout.addWidget(self.btn_edit)

        self._metadata = None
        self.set_metadata(None)

    def set_metadata(self, metadata):
        self._metadata = metadata
        if not metadata or not metadata.names():
            self.label.setText(
                "<span style='color:#888'>尚未设置元数据，点击 ✏️ 编辑</span>")
        else:
            pairs = []
            for k, v in metadata.items():
                if v:
                    pairs.append(f"<b>{k}</b>={v}")
            if pairs:
                self.label.setText(" | ".join(pairs))
            else:
                self.label.setText(
                    "<span style='color:#888'>元数据字段为空，点击 ✏️ 编辑</span>")

    def mousePressEvent(self, event):
        self.clicked.emit()


# ==================== 空格子占位 ====================

class _EmptySlot(QWidget):
    """无视频占位格。双击选视频，右键菜单。"""

    double_clicked = Signal(str)
    remove_requested = Signal(str)
    rename_requested = Signal(str)

    def __init__(self, view_name: str, label="双击此处选择视频",
                 parent=None):
        super().__init__(parent)
        self._view_name = view_name
        self._label = label
        self.grid_pos = (-1, -1)
        self.view_color = ""
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = DraggableHeader(self, "#888888")
        layout.addWidget(self._header)
        layout.addStretch()

    def set_view_color(self, color: str):
        self.view_color = color
        self._header.set_color(color)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen, QFont
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#222222"))
        p.setPen(QPen(QColor(COLOR_ACCENT), 2, Qt.DashLine))
        p.drawRect(4, 4, self.width() - 8, self.height() - 8)
        p.setPen(QColor("#aaaaaa"))
        p.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        p.drawText(self.rect(), Qt.AlignCenter, self._label)
        p.end()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-mvsp-cell-index"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-mvsp-cell-index"):
            raw = bytes(event.mimeData().data(
                "application/x-mvsp-cell-index"))
            parts = raw.decode().split(",")
            src_pos = (int(parts[0]), int(parts[1]))
            mw = self.window()
            if hasattr(mw, '_swap_cells'):
                mw._swap_cells(src_pos, self.grid_pos)
            event.acceptProposedAction()

    def mouseDoubleClickEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择视频 — {self._view_name}", "",
            "视频文件 (*.mp4 *.avi *.mkv *.mov);;所有文件 (*)")
        if path:
            self.double_clicked.emit(path)

    def _show_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        act_remove = menu.addAction("删除此视角")
        act_rename = menu.addAction("重命名视角")
        action = menu.exec(self.mapToGlobal(pos))
        if action == act_remove:
            self.remove_requested.emit(self._view_name)
        elif action == act_rename:
            self.rename_requested.emit(self._view_name)


# ==================== 主窗口 ====================

class MainWindow(QMainWindow):
    """多视角视频同步播放主窗口。"""

    def __init__(self, session_path=None, backend='auto', layout_config=None):
        super().__init__()
        self.setWindowTitle("多视角同步播放器")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 900)

        self.backend_decision = choose_backend(backend)
        cfg.BACKEND = self.backend_decision.active
        cfg.BACKEND_MODE = self.backend_decision.mode
        cfg.BACKEND_REQUESTED = self.backend_decision.requested
        cfg.BACKEND_REASON = self.backend_decision.reason

        self.controller = SyncController()
        self._seek_barrier = SeekBarrier()
        self._last_seek_latency_ms = 0.0
        self._last_seek_error = ""
        self._signal_slot_samples_ms = collections.deque(maxlen=2048)
        self._playback_stall_ticks = 0
        self._displayed_ticks = 0
        self._play_started_at = None
        self._fps_warning = ""
        self._backend_init_complete = True
        self._initial_session_loading = False
        self._pending_review_state = None
        self._session_load_generation = 0
        self._session_load_workers = []
        self._audio_loading_active = False
        self.metadata = SessionMetadata()
        self.cells = {}
        self._slot_widgets = {}
        self.temp_dir = tempfile.mkdtemp(prefix="mvsp_")

        if layout_config:
            self.layout_config = layout_config
        else:
            self.layout_config = LayoutConfig(rows=2, cols=3)
        self._rebuild_view_maps()

        # 媒体库浏览器 dock（需在 _build_menubar 之前创建）
        self.library_dock = LibraryBrowserDock(parent=self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.library_dock)
        self.library_dock.setVisible(False)

        self._build_menubar()
        self._build_ui()
        self._connect_signals()
        self._setup_shortcuts()
        self._connect_library_dock()

        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.PreciseTimer)
        self.play_timer.timeout.connect(self._on_play_tick)

        self._ui_timer = QTimer(self)
        self._ui_timer.setTimerType(Qt.CoarseTimer)
        self._ui_timer.timeout.connect(self._on_ui_refresh)

        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self._sync_correction)

        self._seek_timeout_timer = QTimer(self)
        self._seek_timeout_timer.setSingleShot(True)
        self._seek_timeout_timer.timeout.connect(self._on_seek_timeout)

        self._restore_geometry()

        if session_path:
            QTimer.singleShot(100, lambda: self._load_session(session_path))

        self.setStyleSheet(DARK_THEME_QSS)

        # 首次运行欢迎气泡
        QTimer.singleShot(500, self._show_welcome_if_first_run)

    # ---- 菜单栏 ----

    def _build_menubar(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        a = QAction("打开会话...", self)
        a.setShortcut("Ctrl+O")
        a.triggered.connect(self._on_session_open)
        file_menu.addAction(a)

        a = QAction("从项目模板加载...", self)
        a.setShortcut("Ctrl+Shift+O")
        a.triggered.connect(self._load_from_project_template)
        file_menu.addAction(a)

        self.recent_templates_menu = file_menu.addMenu("最近模板")
        self._rebuild_recent_templates_menu()

        file_menu.addSeparator()

        a = QAction("保存", self)
        a.setShortcut("Ctrl+S")
        a.triggered.connect(self._save)
        file_menu.addAction(a)

        a = QAction("另存为...", self)
        a.triggered.connect(self._save_as)
        file_menu.addAction(a)

        file_menu.addSeparator()

        act_import = QAction("导入视频到库...", self)
        act_import.setShortcut("Ctrl+I")
        act_import.triggered.connect(self._slot_import_requested)
        file_menu.addAction(act_import)

        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")

        a = QAction("显示/隐藏工具栏", self)
        a.setShortcut("Ctrl+T")
        a.triggered.connect(self._toggle_toolbar)
        view_menu.addAction(a)

        a = QAction("显示/隐藏元数据栏", self)
        a.triggered.connect(self._toggle_metadata_bar)
        view_menu.addAction(a)

        view_menu.addSeparator()

        a = QAction("全屏", self)
        a.setShortcut("F11")
        a.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(a)

        view_menu.addSeparator()

        act_toggle_lib = QAction("显示/隐藏媒体库浏览器", self, checkable=True)
        act_toggle_lib.setShortcut("Ctrl+L")
        act_toggle_lib.toggled.connect(self.library_dock.setVisible)
        self.library_dock.visibilityChanged.connect(act_toggle_lib.setChecked)
        view_menu.addAction(act_toggle_lib)

        view_menu.addSeparator()
        self.debug_metrics_action = QAction(
            "Debug playback metrics", self, checkable=True)
        self.debug_metrics_action.toggled.connect(
            self._toggle_debug_metrics)
        view_menu.addAction(self.debug_metrics_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        a = QAction("快速入门", self)
        a.triggered.connect(self._show_quickstart)
        help_menu.addAction(a)

        a = QAction("打开示例会话...", self)
        a.triggered.connect(self._open_example_session)
        help_menu.addAction(a)

        help_menu.addSeparator()

        a = QAction("关于", self)
        a.triggered.connect(self._show_about)
        help_menu.addAction(a)

    # ---- 视角映射 ----

    def _rebuild_view_maps(self):
        self._view_names = list(self.layout_config.view_names)
        self._view_positions = self.layout_config.view_positions()

    # ---- UI 构建 ----

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(4, 4, 4, 4)
        ml.setSpacing(4)

        self.toolbar = GlobalToolbar()
        ml.addWidget(self.toolbar)

        self.metadata_bar = MetadataBar()
        self.metadata_bar.clicked.connect(self._edit_metadata)
        ml.addWidget(self.metadata_bar)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(2)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self._populate_grid()

        ml.addWidget(self.grid_widget, 1)

        self.debug_metrics_label = QLabel()
        self.debug_metrics_label.setWordWrap(True)
        self.debug_metrics_label.setStyleSheet(
            "background:#111; color:#9ee7ff; font-family:Consolas; "
            "font-size:8pt; padding:4px;")
        self.debug_metrics_label.setVisible(False)
        ml.addWidget(self.debug_metrics_label)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status()

    def _populate_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._slot_widgets.clear()

        cfg = self.layout_config
        for c in range(cfg.cols):
            self.grid_layout.setColumnStretch(c, 1)
        for r in range(cfg.rows):
            self.grid_layout.setRowStretch(r, 1)

        for idx, (vn, (r, c)) in enumerate(zip(cfg.view_names, cfg.positions())):
            e = _EmptySlot(vn)
            e.double_clicked.connect(
                lambda path, v=vn: self._on_manual_video_selected(v, path))
            e.remove_requested.connect(self._on_remove_view)
            e.rename_requested.connect(self._on_rename_view)
            e.grid_pos = (r, c)
            e.set_view_color(VIEW_COLORS[idx % len(VIEW_COLORS)])
            self.grid_layout.addWidget(e, r, c)
            self._slot_widgets[(r, c)] = e

    # ---- 信号连接 ----

    def _connect_signals(self):
        t = self.toolbar
        ctrl = self.controller

        t.session_open_requested.connect(self._on_session_open)
        t.session_new_requested.connect(self._on_session_new)
        t.play_toggled.connect(self._toggle_play)
        t.step_requested.connect(self._step_frames)
        t.seek_start.connect(lambda: ctrl.seek_to(0))
        t.speed_set.connect(self._set_speed)
        t.reset_offsets.connect(ctrl.reset_offsets)
        t.save_requested.connect(self._save)
        t.save_as_requested.connect(self._save_as)
        t.mark_frame.connect(self._mark_frame)
        t.metadata_requested.connect(self._edit_metadata)
        t.add_view_requested.connect(self._on_add_view)
        t.help_requested.connect(self._show_help)

        ctrl.base_frame_changed.connect(self._on_base_frame_changed)
        ctrl.offset_changed.connect(self._on_offset_changed)
        ctrl.playback_toggled.connect(self._on_playback_toggled)
        ctrl.markers_changed.connect(self._update_status)

    # ---- 快捷键 ----

    def _setup_shortcuts(self):
        def sc(key, fn):
            QShortcut(QKeySequence(key), self, fn)
        sc(Qt.Key_Space, self._toggle_play)
        sc(Qt.Key_Home, lambda: self.controller.seek_to(0))
        sc(Qt.Key_End, lambda: self.controller.seek_to(999999999))
        sc(Qt.Key_Plus, lambda: self._set_speed(
            min(len(SPEED_STEPS) - 1, self.controller.speed_index + 1)))
        sc(Qt.Key_Equal, lambda: self._set_speed(
            min(len(SPEED_STEPS) - 1, self.controller.speed_index + 1)))
        sc(Qt.Key_Minus, lambda: self._set_speed(
            max(0, self.controller.speed_index - 1)))
        sc(Qt.Key_R, self.controller.reset_offsets)
        sc(Qt.Key_F, lambda: (
            self.showNormal() if self.isFullScreen() else self.showFullScreen()))
        sc(Qt.Key_H, self._show_help)
        sc(Qt.Key_M, self._mark_frame)
        for i in range(1, 10):
            sc(Qt.Key_0 + i, lambda idx=i - 1: self._select_view_by_slot(idx))
        sc(Qt.Key_0, lambda: self._select_view(None))
        sc(Qt.Key_Escape, lambda: self._select_view(None))

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        ctrl = self.controller
        if key in (Qt.Key_D, Qt.Key_Right) and not ctrl.selected_view:
            self._step_frames(1); return
        if key in (Qt.Key_A, Qt.Key_Left) and not ctrl.selected_view:
            self._step_frames(-1); return
        if key == Qt.Key_W: self._step_frames(25); return
        if key == Qt.Key_S and not mods: self._step_frames(-25); return
        if key == Qt.Key_Q: self._step_frames(-250); return
        if key == Qt.Key_E: self._step_frames(250); return
        if ctrl.selected_view:
            if key == Qt.Key_Left:
                d = (-25 if mods & Qt.ShiftModifier
                     else -250 if mods & Qt.ControlModifier else -1)
                self._step_local_view(ctrl.selected_view, d); return
            if key == Qt.Key_Right:
                d = (25 if mods & Qt.ShiftModifier
                     else 250 if mods & Qt.ControlModifier else 1)
                self._step_local_view(ctrl.selected_view, d); return
        super().keyPressEvent(event)

    # ---- 会话回调 ----

    def _on_session_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开会话", "",
            "会话文件 (*.mvsp.json *.mvsp);;JSON 文件 (*.json);;所有文件 (*)")
        if path:
            self._load_session(path)

    def _on_session_new(self):
        if not self.controller.saved and self.cells:
            ret = QMessageBox.question(
                self, "未保存的更改",
                "当前会话有未保存的更改，是否丢弃？",
                QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        from .startup_wizard import StartupWizard
        wizard = StartupWizard(self)
        if wizard.exec() == QDialog.Accepted:
            layout_cfg, metadata = wizard.get_results()
            self._clear_all()
            self.layout_config = layout_cfg
            self._rebuild_view_maps()
            self.metadata = metadata
            self._populate_grid()
            self.metadata_bar.set_metadata(self.metadata)
            self._update_status()
            self._update_title()

    def _load_session(self, path: str):
        path = str(Path(path).resolve())
        try:
            data = load_session(path)
        except SessionFormatError as e:
            QMessageBox.warning(self, "格式错误", f"会话文件格式不兼容:\n{e}")
            return
        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"无法加载会话文件:\n{e}")
            return

        self._session_load_generation += 1
        generation = self._session_load_generation
        for existing in self._session_load_workers:
            if existing.isRunning():
                existing.requestInterruption()
        self._clear_all()
        self.controller.session_path = path
        if data.layout:
            self.layout_config = LayoutConfig.from_dict(data.layout)
            self._rebuild_view_maps()
            self._populate_grid()
        self._initial_session_loading = True
        total = len(data.video_manifests or data.cells)
        self.status_bar.showMessage(f"Loading session metadata… 0/{total}")
        worker = SessionLoadThread(generation, data, path, self)
        self._session_load_workers.append(worker)
        worker.progress.connect(self._on_session_load_progress)
        worker.completed.connect(self._on_session_load_complete)
        worker.finished.connect(
            lambda w=worker: self._session_load_workers.remove(w)
            if w in self._session_load_workers else None)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_session_load_progress(self, completed, total, view_name):
        self.status_bar.showMessage(
            f"Loading session metadata… {completed}/{total} {view_name}")

    def _on_session_load_complete(self, generation, data, resolutions, error):
        if generation != self._session_load_generation or error == "cancelled":
            return
        if error:
            self._initial_session_loading = False
            QMessageBox.warning(self, "加载失败", f"无法初始化会话视频:\n{error}")
            return
        missing = [item for item in resolutions.values() if item.path is None]
        if missing:
            resolutions = self._offer_session_relocation(
                data, self.controller.session_path, resolutions)
            if resolutions is None:
                self._initial_session_loading = False
                return
        mismatches = [item for item in resolutions.values()
                      if item.path is not None and item.identity_ok is False]
        if mismatches:
            summary = "\n".join(
                f"{item.view_name}: {item.identity_message}\n"
                f"相对路径: {item.relative_path or '(无)'}\n"
                f"绝对路径: {item.absolute_path or '(无)'}"
                for item in mismatches)
            answer = QMessageBox.warning(
                self, "视频身份校验不一致",
                "以下文件与会话记录不一致，可能被替换。\n\n" + summary
                + "\n\n是否明确确认仍然打开这些文件？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                self._initial_session_loading = False
                return
            for item in mismatches:
                item.identity_ok = True
        unavailable = [item for item in resolutions.values() if not item.ok]
        if unavailable:
            summary = "\n".join(
                f"{item.view_name}: expected {item.relative_path or '(no relative path)'}"
                f"\n  old absolute: {item.absolute_path or '(none)'}"
                for item in unavailable)
            answer = QMessageBox.warning(
                self, "会话视频不完整",
                f"{len(unavailable)}/{len(resolutions)} 个视频无法安全解析:\n\n"
                + summary
                + "\n\n选择“是”将只打开已解析视角；选择“否”取消。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                self._initial_session_loading = False
                return
        self._apply_resolutions(data, resolutions)
        path = self.controller.session_path
        self._clear_all()
        self.controller.session_path = path
        self._apply_session_data(data)

    @staticmethod
    def _add_cells_for_manifests(data):
        """Materialize compact cell entries for a legacy no-video session."""
        existing = {cell["view_name"] for cell in data.cells}
        offsets = data.global_state.get("offsets", {})
        for vn, manifest in data.video_manifests.items():
            if vn in existing:
                continue
            data.cells.append({
                "view_name": vn,
                "video_path": manifest.get("path", ""),
                "total_frames": manifest.get("total_frames", 0),
                "fps": manifest.get("fps", 0.0),
                "has_audio": manifest.get("has_audio", False),
                "offset": offsets.get(vn, 0),
            })

    def _resolve_session_data(self, data, path, search_root=None):
        """Resolve paths and validate identities after probing actual files."""
        initial = resolve_session_videos(data, path, search_root)
        actual = {}
        for vn, item in initial.items():
            if item.path is not None:
                actual[vn] = probe_video_metadata(str(item.path))
        return resolve_session_videos(data, path, search_root, actual)

    def _offer_session_relocation(self, data, path, resolutions):
        """Offer one subject-root selection and one-file repair when needed."""
        missing = [item for item in resolutions.values() if item.path is None]
        if not missing:
            return resolutions

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("找不到会话视频")
        msg.setText("部分视频无法按相对路径或旧绝对路径找到。")
        locate_root = msg.addButton("定位会话根目录…", QMessageBox.AcceptRole)
        locate_file = msg.addButton("定位一个文件…", QMessageBox.ActionRole)
        partial = msg.addButton("打开部分会话", QMessageBox.DestructiveRole)
        msg.addButton("取消", QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == locate_root:
            root = QFileDialog.getExistingDirectory(
                self, "选择 relocated subject/session 根目录", str(Path(path).parent))
            if root:
                return self._resolve_session_data(data, path, Path(root))
        elif clicked == locate_file:
            target = missing[0]
            selected, _ = QFileDialog.getOpenFileName(
                self, f"定位 {target.view_name}", str(Path(path).parent),
                "视频文件 (*.mp4 *.MP4 *.avi *.mkv *.mov);;所有文件 (*)")
            if selected:
                manifest = data.video_manifests[target.view_name]
                manifest["path"] = selected
                manifest["file_name"] = Path(selected).name
                return self._resolve_session_data(data, path)
        elif clicked == partial:
            return resolutions
        return None

    @staticmethod
    def _apply_resolutions(data, resolutions):
        """Replace manifest/cell paths with the verified path chosen to open."""
        cells = []
        for cell in data.cells:
            item = resolutions.get(cell["view_name"])
            if item is None or not item.ok:
                continue
            cell = dict(cell)
            cell["video_path"] = str(item.path)
            data.video_manifests.setdefault(cell["view_name"], {})["path"] = str(item.path)
            cells.append(cell)
        data.cells = cells

    # ---- 播放控制 ----

    def _toggle_play(self):
        self.controller.toggle_play()

    def _on_playback_toggled(self, playing):
        self.toolbar.set_play_button_text(playing)
        if playing:
            speed = SPEED_STEPS[self.controller.speed_index]
            participants = self._synced_enabled_cells()
            fps = self.controller.master_fps(participants)
            interval = max(1, round(1000 / (fps * speed)))
            self._play_started_at = perf_counter()
            self._displayed_ticks = 0
            for cell in participants.values():
                if cell.synced:
                    cell.play()
                    cell.set_speed(speed)
            QTimer.singleShot(50, lambda: self._start_display_timer(interval))
            self._ui_timer.start(200)
            self.sync_timer.start(200)
        else:
            self.play_timer.stop()
            self._ui_timer.stop()
            self.sync_timer.stop()
            for cell in self.cells.values():
                cell.pause()
            self._on_base_frame_changed(self.controller.base_frame)

    def _start_display_timer(self, interval):
        if not self.controller.is_playing:
            return
        self.play_timer.start(interval)

    def _on_play_tick(self):
        if not self.controller.is_playing:
            return
        if self.controller.base_frame >= self.controller._max_base_frame():
            self.controller.pause()
            return

        participants = self._synced_enabled_cells()
        next_base = self.controller.base_frame + 1
        targets = {
            view: self.controller.get_target_frame_at(view, next_base)
            for view in participants
        }

        # Strict admission: no view consumes or displays until all are ready.
        for view, cell in participants.items():
            if cell.decoder and not cell.decoder.has_frame(targets[view]):
                self._playback_stall_ticks += 1
                return

        frames = {}
        for view, cell in participants.items():
            if cell.decoder:
                image = cell.decoder.get_frame(targets[view])
                if image is None:
                    self._playback_stall_ticks += 1
                    return
                frames[view] = image

        self.controller.base_frame = next_base
        self.controller.saved = False
        for view, image in frames.items():
            participants[view].display_image(image, targets[view])
        for cell in participants.values():
            cell.waveform.set_base_frame(next_base)
        self._displayed_ticks += 1

    def _on_ui_refresh(self):
        if not self.controller.is_playing:
            return
        base = self.controller.base_frame
        for cell in self._synced_enabled_cells().values():
            cell.waveform.set_base_frame(base)
        self._update_debug_metrics()
        self._update_status()
        self._update_title()

    def _set_speed(self, idx):
        self.controller.speed_index = idx
        self.toolbar.highlight_speed(idx)
        speed = SPEED_STEPS[idx]
        if self.controller.is_playing:
            participants = self._synced_enabled_cells()
            fps = self.controller.master_fps(participants)
            self.play_timer.setInterval(
                max(1, round(1000 / (fps * speed))))
            for cell in participants.values():
                if cell.synced:
                    cell.set_speed(speed)

    def _step_frames(self, delta):
        was_playing = self.controller.is_playing
        if was_playing:
            self.controller.pause()
        self.controller.step_frames(delta)

    def _sync_correction(self):
        if cfg.BACKEND != "mpv":
            return
        for vn, cell in self.cells.items():
            if (cell.player and cell.is_enabled and cell.synced
                    and cell.player.time_pos is not None):
                actual_frame = int(cell.player.time_pos * cell.fps)
                expected = (self.controller.base_frame
                            + self.controller.offsets.get(vn, 0))
                if abs(actual_frame - expected) > 2:
                    corrected = actual_frame - self.controller.offsets.get(vn, 0)
                    self.controller.base_frame = max(0, corrected)
                    return

    # ---- 帧偏移更新 ----

    def _on_base_frame_changed(self, frame):
        if self.controller.is_playing:
            self.controller.pause()
            return
        self._begin_seek_request(frame)
        self._update_title()

    def _on_offset_changed(self, view, offset):
        cell = self.cells.get(view)
        if cell is None or not cell.synced:
            return
        cell.set_offset(offset)
        self._on_base_frame_changed(self.controller.base_frame)

    def _step_local_view(self, view_name, delta):
        """Step one enabled view according to its linked/local state."""
        cell = self.cells.get(view_name)
        if cell is None or not cell.is_enabled:
            return
        if cell.synced:
            self.controller.adjust_offset(view_name, delta)
            return
        last = max(0, cell.total_frames - 1)
        target = max(0, min(cell.local_frame + delta, last))
        cell.local_frame = target
        cell.seek_to_frame(target)
        cell.waveform.set_base_frame(target)
        self._update_status()

    def _synced_enabled_cells(self):
        return {
            view: cell for view, cell in self.cells.items()
            if cell.synced and self.controller.is_view_enabled(view)
        }

    def _begin_seek_request(self, base_frame, retry_count=0):
        participants = self._synced_enabled_cells()
        targets = {
            view: self.controller.get_target_frame_at(view, base_frame)
            for view in participants
        }
        request = self._seek_barrier.begin(
            base_frame, targets, retry_count=retry_count)
        self._last_seek_error = ""

        if not targets:
            self._seek_barrier.cancel(request.generation)
            self._update_status()
            return

        timeout = (INITIAL_SESSION_LOAD_TIMEOUT_MS
                   if self._initial_session_loading else SEEK_TIMEOUT_MS)
        self._seek_timeout_timer.start(timeout)
        for view, target in targets.items():
            participants[view].set_seek_pending(True)
            participants[view].seek_to_frame(
                target, request_id=request.generation)
        self._update_status()

    def _set_all_seek_pending(self, pending):
        for cell in self.cells.values():
            cell.set_seek_pending(pending)

    def _on_seek_frame_ready(self, view, generation, frame_number, image):
        callback_started = perf_counter()
        complete = self._seek_barrier.accept(
            generation, view, frame_number, image)
        if not complete:
            self._signal_slot_samples_ms.append(
                (perf_counter() - callback_started) * 1000.0)
            self._update_status()
            return

        request = self._seek_barrier.finish(generation)
        if request is None:
            return
        self._seek_timeout_timer.stop()
        self._set_all_seek_pending(False)
        self._initial_session_loading = False
        self._last_seek_latency_ms = request.latency_ms

        # All QPixmap/overlay/slider writes happen in this one UI callback.
        for participant, target in request.targets.items():
            cell = self.cells.get(participant)
            image = request.frames.get(participant)
            if cell is None:
                continue
            if image is not None:
                cell.display_image(image, target)
            cell.waveform.set_base_frame(request.base_frame)
        for cell in self.cells.values():
            if cell.synced and not cell.is_enabled:
                cell.waveform.set_base_frame(request.base_frame)
        self._update_debug_metrics()
        self._update_status()
        self._update_title()
        self._signal_slot_samples_ms.append(
            (perf_counter() - callback_started) * 1000.0)

    def _on_seek_frame_failed(self, view, generation, frame_number, message):
        request = self._seek_barrier.active
        if request is None or request.generation != generation:
            return
        self._last_seek_error = f"{view} frame {frame_number}: {message}"
        self._update_status()

    def _on_seek_timeout(self):
        request = self._seek_barrier.active
        if request is None:
            return
        missing = request.missing_views
        base = request.base_frame
        if request.retry_count < 1:
            self._begin_seek_request(base, retry_count=request.retry_count + 1)
            return
        self._last_seek_error = (
            "Seek timeout after retry: " + ", ".join(missing))
        self._seek_barrier.cancel(request.generation)
        self._set_all_seek_pending(False)
        self._initial_session_loading = False
        self._update_status()

    def _toggle_debug_metrics(self, visible):
        self.debug_metrics_label.setVisible(visible)
        if visible:
            self._update_debug_metrics()

    def _update_debug_metrics(self):
        if not hasattr(self, "debug_metrics_label"):
            return
        participants = self._synced_enabled_cells()
        master = self.controller.master_view(participants) or "--"
        fps = self.controller.master_fps(participants)
        speed = SPEED_STEPS[self.controller.speed_index]
        elapsed = ((perf_counter() - self._play_started_at)
                   if self._play_started_at else 0.0)
        effective_fps = self._displayed_ticks / elapsed if elapsed > 0 else 0.0
        lines = [
            f"Backend={cfg.BACKEND} Mode=Strict Master={master} "
            f"FPS={fps:.3f} Base={self.controller.base_frame} "
            f"Speed={speed:.2f}x Effective={effective_fps:.2f}fps "
            f"Stalls={self._playback_stall_ticks} "
            f"Seek={self._last_seek_latency_ms:.1f}ms",
        ]
        for view, cell in participants.items():
            target = self.controller.get_target_frame(view)
            if cell.decoder:
                metrics = cell.decoder.metrics()
                lines.append(
                    f"{view}: target={target} displayed={cell.current_frame} "
                    f"lag={target-cell.current_frame:+d} "
                    f"buffer={metrics['buffer_occupancy']}/"
                    f"{metrics['buffer_capacity']} cache="
                    f"{metrics['cache_occupancy']}/{metrics['cache_capacity']} "
                    f"decoder={metrics['decoder_position']} "
                    f"seek={metrics['seek_latency_ms']:.1f}ms")
            else:
                lines.append(
                    f"{view}: target={target} displayed={cell.current_frame}")
        if self._fps_warning:
            lines.append(self._fps_warning)
        if self._last_seek_error:
            lines.append("ERROR: " + self._last_seek_error)
        self.debug_metrics_label.setText("\n".join(lines))

    def _refresh_fps_warning(self):
        participants = self._synced_enabled_cells()
        mismatches = self.controller.fps_mismatches(participants)
        if not mismatches:
            self._fps_warning = ""
            return
        master = self.controller.master_view(participants)
        master_fps = self.controller.master_fps(participants)
        detail = ", ".join(
            f"{view}={fps:.3f}" for view, fps in mismatches.items())
        self._fps_warning = (
            f"FPS WARNING: master {master}={master_fps:.3f}; {detail}. "
            "Strict frame mode remains enabled; time drift may accumulate.")

    # ---- 手动选视频 ----

    def _on_manual_video_selected(self, view_name: str, file_path: str):
        pos = self._view_positions.get(view_name)
        if pos is None:
            return
        meta = probe_video_metadata(file_path)
        if meta["total_frames"] <= 0:
            QMessageBox.warning(self, "无法打开", f"无法读取视频: {file_path}")
            return
        self.controller.video_info[view_name] = {
            "path": file_path,
            "total_frames": meta["total_frames"],
            "fps": meta["fps"],
            "has_audio": meta["has_audio"],
            "width": meta.get("width", 0),
            "height": meta.get("height", 0),
            "duration_sec": meta.get("duration_sec", 0.0),
            "codec": meta.get("codec", ""),
        }
        self.controller.offsets.setdefault(view_name, 0)
        self.controller.enabled_views.add(view_name)
        if view_name in self.cells:
            old = self.cells.pop(view_name)
            old.cleanup()
            self.grid_layout.removeWidget(old)
            old.deleteLater()
        self._create_cell(view_name, pos[0], pos[1])
        QTimer.singleShot(100, lambda: self._init_single_cell(view_name))

    def _create_cell(self, view_name: str, row: int, col: int):
        cell = VideoCell(view_name, self.temp_dir)
        cell.offset = self.controller.offsets.get(view_name, 0)
        cell.view_clicked.connect(
            lambda vn=view_name: self._on_view_clicked(vn))
        cell.offset_changed.connect(self.controller.adjust_offset)
        cell.position_jump.connect(self.controller.seek_to)
        cell.solo_stepping.connect(self._step_local_view)
        cell.enable_toggled.connect(self._on_view_enabled)
        cell.sync_toggled.connect(self._on_sync_toggled)
        cell.solo_position_jump.connect(self._on_solo_position_jump)
        cell.video_file_selected.connect(self._on_manual_video_selected)
        cell.seek_frame_ready.connect(self._on_seek_frame_ready)
        cell.seek_frame_failed.connect(self._on_seek_frame_failed)
        cell.audio_load_finished.connect(self._on_audio_load_finished)
        cell.grid_pos = (row, col)
        linear_idx = row * self.layout_config.cols + col
        cell.set_view_color(VIEW_COLORS[linear_idx % len(VIEW_COLORS)])
        self.cells[view_name] = cell
        self.grid_layout.addWidget(cell, row, col)
        self._slot_widgets[(row, col)] = cell

    # ---- Cell swap (drag & drop) ----

    def _swap_cells(self, src_pos, dst_pos):
        print(f"[SWAP-DIAG] src={src_pos} dst={dst_pos}")
        if src_pos == dst_pos:
            return
        src_widget = self._slot_widgets.get(src_pos)
        dst_widget = self._slot_widgets.get(dst_pos)
        if not src_widget or not dst_widget:
            print(f"[SWAP-DIAG]  skipped: src={src_widget is not None} dst={dst_widget is not None}")
            return

        # Move widgets in the grid layout (colors move with widgets automatically)
        self.grid_layout.removeWidget(src_widget)
        self.grid_layout.removeWidget(dst_widget)
        self.grid_layout.addWidget(src_widget, dst_pos[0], dst_pos[1])
        self.grid_layout.addWidget(dst_widget, src_pos[0], src_pos[1])

        # Sync grid_pos so future drags report correct source positions
        src_widget.grid_pos = dst_pos
        dst_widget.grid_pos = src_pos

        # Update _slot_widgets mapping
        self._slot_widgets[src_pos] = dst_widget
        self._slot_widgets[dst_pos] = src_widget

        # Force layout recalculation — QGridLayout doesn't repaint moved
        # widgets automatically after remove+add, they stay at old geometry.
        self.grid_layout.invalidate()
        self.grid_layout.activate()
        src_widget.updateGeometry()
        dst_widget.updateGeometry()
        print(f"[SWAP-DIAG]  geometry src@{dst_pos}={src_widget.geometry().getRect()} dst@{src_pos}={dst_widget.geometry().getRect()}")

        print(f"[SWAP-DIAG]  done; slot_widgets keys = {list(self._slot_widgets.keys())}")

    # ---- 后端初始化 ----

    def _init_single_cell(self, view_name):
        cell = self.cells.get(view_name)
        info = self.controller.video_info.get(view_name, {})
        if cell and info:
            cell.init_backend(info["path"], info["total_frames"], info["fps"])
            cell.set_offset(self.controller.offsets.get(view_name, 0))
            cell.waveform.set_video_meta(info["fps"], info["total_frames"])
            cell.waveform.set_offset(self.controller.offsets.get(view_name, 0))
            self._refresh_fps_warning()
            self._on_base_frame_changed(self.controller.base_frame)

    def _init_next_backend(self):
        if not self._backend_queue:
            self._backend_init_complete = True
            pending = self._pending_review_state
            if pending is None:
                desired_base = 0
            else:
                max_base = self.controller._max_base_frame()
                desired_base = max(
                    0, min(int(pending.get("base_frame", 0)), max_base))
                # A fast decoder can make controls usable before the queued
                # initializer reaches this final callback.  Never rewind a
                # frame the user already selected during that short window.
                user_moved_during_load = self.controller.base_frame != desired_base
                if not user_moved_during_load:
                    self.controller.base_frame = desired_base
                for vn, state in pending.get("per_view", {}).items():
                    cell = self.cells.get(vn)
                    if cell is None or cell.synced or user_moved_during_load:
                        continue
                    last = max(0, cell.total_frames - 1)
                    target = state.get("local_frame", state.get(
                        "displayed_frame", self.controller.base_frame
                        + self.controller.offsets.get(vn, 0)))
                    target = max(0, min(int(target), last))
                    cell.local_frame = target
                    cell.waveform.set_base_frame(target)
                    cell.seek_to_frame(target)
            self._pending_review_state = None
            self._refresh_fps_warning()
            self._on_base_frame_changed(self.controller.base_frame)
            self._start_audio_loading()
            self._update_title()
            return
        vn = self._backend_queue.pop(0)
        cell = self.cells.get(vn)
        info = self.controller.video_info.get(vn, {})
        if cell and info:
            cell.init_backend(info["path"], info["total_frames"], info["fps"])
            cell.set_offset(self.controller.offsets.get(vn, 0))
            cell.waveform.set_video_meta(info["fps"], info["total_frames"])
            cell.waveform.set_offset(self.controller.offsets.get(vn, 0))
            cell.waveform.set_markers(
                [m["frame"] for m in self.controller.markers])
        QTimer.singleShot(100, self._init_next_backend)

    def _start_audio_loading(self):
        self._audio_queue = list(self.cells.keys())
        self._audio_loading_active = True
        self._load_next_audio()

    def _load_next_audio(self):
        if not hasattr(self, '_audio_queue') or not self._audio_queue:
            self._audio_loading_active = False
            self._update_status()
            return
        vn = self._audio_queue.pop(0)
        info = self.controller.video_info.get(vn, {})
        if vn in self.cells and info.get("path"):
            self.status_bar.showMessage(
                f"Loading audio waveform… {len(self.cells) - len(self._audio_queue)}/"
                f"{len(self.cells)} {vn}")
            self.cells[vn].load_audio(info["path"])
        else:
            QTimer.singleShot(0, self._load_next_audio)

    def _on_audio_load_finished(self, view_name):
        if self._audio_loading_active:
            QTimer.singleShot(0, self._load_next_audio)

    # ---- 同步锁回调 ----

    def _on_sync_toggled(self, view_name, synced):
        cell = self.cells.get(view_name)
        if cell is None:
            return
        # Anchor both transitions to the currently committed image. Unlink
        # captures it as local state; relink derives the fresh offset from it.
        visible_frame = max(0, min(
            cell.current_frame, max(0, cell.total_frames - 1)))
        cell.local_frame = visible_frame
        if synced:
            new_offset = visible_frame - self.controller.base_frame
            self.controller.offsets[view_name] = new_offset
            self.controller.saved = False
            cell.set_offset(new_offset)
        else:
            cell.pause()
            cell.update_offset_label(cell.offset)
        self._refresh_fps_warning()
        self._on_base_frame_changed(self.controller.base_frame)

    def _on_view_enabled(self, view_name, enabled):
        self.controller.set_view_enabled(view_name, enabled)
        self._refresh_fps_warning()
        self._on_base_frame_changed(self.controller.base_frame)

    def _on_solo_position_jump(self, view_name, frame):
        cell = self.cells.get(view_name)
        if cell and cell.is_enabled:
            last = max(0, cell.total_frames - 1)
            target = max(0, min(frame, last))
            cell.local_frame = target
            cell.seek_to_frame(target)
            cell.waveform.set_base_frame(target)

    # ---- 视角选择 ----

    def _select_view(self, vn):
        self.controller.selected_view = vn
        for v, cell in self.cells.items():
            cell.set_selected(v == vn)
        self._update_status()

    def _select_view_by_slot(self, idx):
        if idx < len(self._view_names):
            vn = self._view_names[idx]
            self._select_view(vn if vn in self.cells else None)
        else:
            self._select_view(None)

    def _on_view_clicked(self, vn):
        if self.controller.selected_view == vn:
            self._select_view(None)
        else:
            self._select_view(vn)

    # ---- 视角增删改 ----

    def _on_add_view(self):
        for vn in self._view_names:
            if vn not in self.controller.video_info:
                path, _ = QFileDialog.getOpenFileName(
                    self, f"选择视频 — {vn}", "",
                    "视频文件 (*.mp4 *.avi *.mkv *.mov);;所有文件 (*)")
                if path:
                    self._on_manual_video_selected(vn, path)
                return
        self.controller.pause()
        self.play_timer.stop()
        self.layout_config.cols += 1
        new_idx = self.layout_config.slots_count()
        new_name = f"View {new_idx}"
        self.layout_config.view_names.append(new_name)
        self._rebuild_view_maps()
        self._populate_grid()
        self._update_status()
        self._update_title()

    def _on_remove_view(self, view_name: str):
        if len(self.layout_config.view_names) <= 1:
            QMessageBox.information(self, "无法删除", "至少需要保留一个视角格子。")
            return
        if view_name in self.cells:
            cell = self.cells.pop(view_name)
            cell.cleanup()
            self.grid_layout.removeWidget(cell)
            cell.deleteLater()
        self.controller.video_info.pop(view_name, None)
        self.controller.offsets.pop(view_name, None)
        self.controller.enabled_views.discard(view_name)
        self.layout_config.view_names.remove(view_name)
        count = len(self.layout_config.view_names)
        rows = self.layout_config.rows
        cols = max(1, (count + rows - 1) // rows)
        self.layout_config.cols = cols
        while len(self.layout_config.view_names) > rows * cols:
            self.layout_config.view_names.pop()
        self._rebuild_view_maps()
        self._populate_grid()
        self._update_status()
        self._update_title()

    def _on_rename_view(self, view_name: str):
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "重命名视角", f"'{view_name}' 的新名称:", text=view_name)
        if ok and new_name.strip():
            new_name = new_name.strip()
            idx = self.layout_config.view_names.index(view_name)
            self.layout_config.view_names[idx] = new_name
            if view_name in self.controller.video_info:
                self.controller.video_info[new_name] = self.controller.video_info.pop(view_name)
            if view_name in self.controller.offsets:
                self.controller.offsets[new_name] = self.controller.offsets.pop(view_name)
            if view_name in self.controller.enabled_views:
                self.controller.enabled_views.discard(view_name)
                self.controller.enabled_views.add(new_name)
            if self.controller.selected_view == view_name:
                self.controller.selected_view = new_name
            if view_name in self.cells:
                cell = self.cells.pop(view_name)
                cell.view_name = new_name
                cell.overlay.view_name = new_name
                self.cells[new_name] = cell
            self._rebuild_view_maps()
            self._update_status()
            self._update_title()

    # ---- 标记 ----

    def _mark_frame(self):
        self.controller.add_marker()
        self._update_status()

    # ---- 元数据 ----

    def _edit_metadata(self):
        from .metadata_editor import MetadataEditor
        dlg = MetadataEditor(self.metadata, self)
        if dlg.exec() == QDialog.Accepted:
            self.metadata = dlg.get_metadata()
            self.metadata_bar.set_metadata(self.metadata)
            self._update_title()

    # ---- 保存 ----

    def _save(self):
        if (not self.controller.session_path
                or not str(self.controller.session_path).lower().endswith(".mvsp.json")):
            self._save_as()
        else:
            data = self._collect_session_data()
            save_session(self.controller.session_path, data)
            self.controller.saved = True

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存会话", "",
            "会话文件 (*.mvsp.json *.mvsp);;JSON 文件 (*.json);;所有文件 (*)")
        if path:
            if path.lower().endswith(".json") and not path.lower().endswith(".mvsp.json"):
                path = path[:-5] + ".mvsp.json"
            elif path.lower().endswith(".mvsp"):
                path += ".json"
            elif not path.lower().endswith(".mvsp.json"):
                path += ".mvsp.json"
            data = self._collect_session_data()
            save_session(path, data)
            self.controller.session_path = path
            self.controller.saved = True
            self._update_title()

    def _collect_session_data(self) -> SessionData:
        """从当前 UI 状态采集 SessionData。"""
        c = self.controller
        cells = []
        for vn, info in c.video_info.items():
            cells.append({
                "view_name": vn,
                "video_path": info["path"],
                "total_frames": info["total_frames"],
                "fps": info["fps"],
                "has_audio": info.get("has_audio", False),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "duration_sec": info.get("duration_sec", 0.0),
                "codec": info.get("codec", ""),
                "offset": c.offsets.get(vn, 0),
            })
        layout = self.layout_config.to_dict()
        synced = {vn: bool(cell.synced) for vn, cell in self.cells.items()}
        review_per_view = {}
        for vn, cell in self.cells.items():
            review_per_view[vn] = {
                "local_frame": int(cell.local_frame),
                "displayed_frame": int(cell.current_frame),
            }
        global_state = {
            "version": "0.2.0",
            "offsets": dict(c.offsets),
            "synced": synced,
            "markers": c.markers,
            "metadata": self.metadata.to_dict(),
            "base_frame": int(c.base_frame),
            "review_state": {
                "base_frame": int(c.base_frame),
                "per_view": review_per_view,
            },
        }
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        global_state["created"] = now
        global_state["updated"] = now

        data = SessionData(cells=cells, layout=layout, global_state=global_state)
        data.library_ref = detect_library_ref(
            [c["video_path"] for c in cells if c.get("video_path")],
            self._get_known_libraries(),
        )
        return data

    def _get_known_libraries(self) -> list:
        """返回当前已打开的 library root 列表。"""
        root = self.library_dock.library_root()
        return [root] if root else []

    def _apply_session_data(self, data: SessionData):
        """将 SessionData 应用到当前窗口。"""
        if data.layout:
            self.layout_config = LayoutConfig.from_dict(data.layout)
            self._rebuild_view_maps()
            self._populate_grid()

        offsets = data.global_state.get("offsets", {})
        markers = data.global_state.get("markers", [])
        synced = data.global_state.get("synced", {})
        review = data.global_state.get("review_state", {}) or {}
        desired_base = data.global_state.get(
            "base_frame", review.get("base_frame", 0))
        self._pending_review_state = {
            "base_frame": int(desired_base or 0),
            "per_view": review.get("per_view", {}),
        }
        # Establish the saved logical position before asynchronous backend
        # creation.  The final initialization callback may then distinguish a
        # genuine user move from the intended restored position.
        self.controller.base_frame = int(desired_base or 0)
        self._initial_session_loading = True

        for cell in data.cells:
            vn = cell["view_name"]
            video_path = cell["video_path"]
            if not video_path or not Path(video_path).exists():
                print(f"[会话] 视频未找到，跳过: {video_path}")
                continue
            pos = self._view_positions.get(vn)
            if pos is None:
                for slot_vn in self._view_names:
                    if slot_vn not in self.controller.video_info:
                        pos = self._view_positions[slot_vn]
                        vn = slot_vn
                        break
                if pos is None:
                    continue
            if cell.get("_metadata_probed"):
                meta = cell
            else:
                meta = probe_video_metadata(video_path)
            if meta["total_frames"] <= 0:
                continue
            self.controller.video_info[vn] = {
                "path": video_path,
                "total_frames": meta["total_frames"],
                "fps": meta["fps"],
                "has_audio": meta["has_audio"],
                "width": meta.get("width", 0),
                "height": meta.get("height", 0),
                "duration_sec": meta.get("duration_sec", 0.0),
                "codec": meta.get("codec", ""),
            }
            self.controller.offsets[vn] = offsets.get(vn, 0)
            self.controller.enabled_views.add(vn)
            self._create_cell(vn, pos[0], pos[1])
            cell_widget = self.cells[vn]
            cell_widget.synced = bool(synced.get(vn, True))
            cell_widget.overlay.synced = cell_widget.synced
            cell_widget._update_sync_style()

        self.controller.markers = markers
        meta_data = data.global_state.get("metadata", {})
        self.metadata = SessionMetadata.from_dict(meta_data)
        self.metadata_bar.set_metadata(self.metadata)

        self._backend_queue = list(self.cells.keys())
        self._backend_init_complete = False
        QTimer.singleShot(200, self._init_next_backend)

        # library_ref handling
        if data.library_ref:
            root = Path(data.library_ref["root"])
            self._slot_library_root_changed(root)
            self.library_dock.set_library_root(root)
            self.library_dock.locate(
                experiment=data.library_ref["experiment"],
                date=data.library_ref["date"],
                subject=data.library_ref["subject"],
            )
        else:
            self.statusBar().showMessage("此 session 无库引用", 5000)

    # ---- 状态栏 / 标题 ----

    def _update_status(self):
        c = self.controller
        speed = SPEED_STEPS[c.speed_index]
        sel = c.selected_view or "无"
        mark = "Y" if c.saved else "X"
        nm = len(c.markers)
        synced_n = sum(1 for cell in self.cells.values() if cell.synced)
        total_n = len(self.cells)
        layout_str = f"{self.layout_config.rows}x{self.layout_config.cols}"
        participants = self._synced_enabled_cells()
        master = c.master_view(participants) or "--"
        fps = c.master_fps(participants)
        runtime = None
        runtime_view = c.selected_view or master
        if runtime_view in self.cells:
            runtime = self.cells[runtime_view].backend_status(
                c.video_info.get(runtime_view, {}).get("codec", ""))
        runtime_text = ""
        if runtime:
            runtime_text = (
                f"Codec: {runtime['codec']} | HW: {runtime['hwdec_current']} | "
                f"GPU decode: {'yes' if runtime['gpu_decode_active'] else 'no'} | "
                f"Dropped: {runtime['dropped_frames']} | ")
        prefix = ""
        request = self._seek_barrier.active
        if request is not None:
            prefix = (
                f"Seeking frame {request.base_frame}… "
                f"{len(request.frames)}/{len(request.targets)} views ready | ")
        elif self._last_seek_error:
            prefix = f"SEEK ERROR: {self._last_seek_error} | "
        elif self._fps_warning:
            prefix = self._fps_warning + " | "
        self.status_bar.showMessage(
            prefix +
            f"Backend: {cfg.BACKEND_REQUESTED}→{cfg.BACKEND} "
            f"{cfg.BACKEND_MODE} | {runtime_text}Master: {master} {fps:.3f} FPS | "
            f"基准帧: {c.base_frame} | "
            f"速度: {speed:.2f}x | 布局: {layout_str} | "
            f"选中: {sel} | 同步: {synced_n}/{total_n} | "
            f"标记: {nm} | 已保存: {mark}")

    def _update_title(self):
        c = self.controller
        total = c._max_base_frame()
        speed = SPEED_STEPS[c.speed_index]
        session = Path(c.session_path).name if c.session_path else "未命名"
        meta_summary = ""
        if self.metadata:
            s = self.metadata.summary(max_items=3)
            if s:
                meta_summary = f" — {s}"
        self.setWindowTitle(
            f"多视角同步播放器 — {session}{meta_summary} — "
            f"帧 {c.base_frame}/{total} — {speed}x")

    # ---- 清空 ----

    def _clear_all(self):
        self.controller.pause()
        self.play_timer.stop()
        self._ui_timer.stop()
        self.sync_timer.stop()
        self._seek_timeout_timer.stop()
        self._initial_session_loading = False
        self._pending_review_state = None
        if self._seek_barrier.active:
            self._seek_barrier.cancel(self._seek_barrier.active.generation)
        for vn, cell in self.cells.items():
            cell.cleanup()
            self.grid_layout.removeWidget(cell)
            cell.deleteLater()
        self.cells.clear()
        self._slot_widgets.clear()
        self.controller.video_info.clear()
        self.controller.offsets.clear()
        self.controller.enabled_views.clear()
        self.controller.markers.clear()
        self.controller.base_frame = 0
        self.controller.session_path = None
        self.controller.saved = True
        self.metadata = SessionMetadata()

    # ---- 帮助 / 关于 ----

    def _show_help(self):
        view_list = "  ".join(
            f"{i+1}={vn}" for i, vn in enumerate(self._view_names))
        QMessageBox.information(self, "快捷键帮助", f"""
        <h3>键盘快捷键</h3>
        <table cellpadding='3' style='font-size:10pt'>
        <tr><td><b>空格</b></td><td>播放/暂停</td></tr>
        <tr><td><b>D/A/W/S/Q/E</b></td><td>全局步进帧</td></tr>
        <tr><td><b>Home/End</b></td><td>跳到开头/结尾</td></tr>
        <tr><td><b>1~9</b></td><td>选中格子视角</td></tr>
        <tr><td><b>0/Esc</b></td><td>取消选择</td></tr>
        <tr><td><b>←/→ (选中时)</b></td><td>偏移 +-1/+-25/+-250</td></tr>
        <tr><td><b>M</b></td><td>标记当前帧</td></tr>
        <tr><td><b>R</b></td><td>重置所有偏移</td></tr>
        <tr><td><b>Ctrl+S</b></td><td>保存会话</td></tr>
        <tr><td><b>+/-</b></td><td>播放速度</td></tr>
        <tr><td><b>F</b></td><td>全屏</td></tr>
        </table>
        <h3>同步锁</h3>
        <table cellpadding='3' style='font-size:10pt'>
        <tr><td><b>🔗 锁定</b></td><td>跟随全局播放/暂停/步进</td></tr>
        <tr><td><b>🔓 解锁</b></td><td>独立播放/拖进度条</td></tr>
        </table>
        <p style='color:#888'>视角编号: {view_list}<br>
        双击格子选择视频文件。右键格子可删除或重命名。</p>""")

    def _show_quickstart(self):
        QMessageBox.information(self, '快速入门',
            '欢迎使用多视角同步播放器！\n\n'
            '📌 快速上手：\n'
            '1. 双击任意格子选择视频文件\n'
            '2. 播放所有视频，用视频上方的同步声（拍板/关门声）对齐\n'
            '3. 拖动「偏移」按钮调整每个视角的帧偏移\n'
            '4. 按 Ctrl+S 保存会话为 .mvsp.json 文件\n\n'
            '💡 从菜单「帮助 → 打开示例会话」查看完整示例。')

    def _toggle_toolbar(self):
        self.toolbar.setVisible(not self.toolbar.isVisible())

    def _toggle_metadata_bar(self):
        self.metadata_bar.setVisible(not self.metadata_bar.isVisible())

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _show_about(self):
        from . import __version__
        QMessageBox.about(self, "关于",
            f"<h3>多视角同步播放器</h3>"
            f"<p>版本 {__version__}</p>"
            f"<p>通用多视角视频同步对齐工具</p>"
            f"<p><a href='https://github.com/Philharmy-Wang/MultiViewSyncPlayer'>"
            f"GitHub: Philharmy-Wang/MultiViewSyncPlayer</a></p>")

    def _open_example_session(self):
        examples_dir = Path(__file__).parent.parent / "examples"
        if not examples_dir.exists():
            examples_dir = Path(".")
        path, _ = QFileDialog.getOpenFileName(
            self, "打开示例会话", str(examples_dir),
            "会话文件 (*.mvsp.json *.mvsp);;JSON 文件 (*.json);;所有文件 (*)")
        if path:
            self._load_session(path)

    # ---- 项目模板 ----

    def _load_from_project_template(self):
        from .project_template import ProjectTemplate
        from .project_browser import ProjectBrowser
        default_dir = str((Path(__file__).parent.parent / 'examples').resolve())
        path, _ = QFileDialog.getOpenFileName(
            self, '选择项目模板文件', default_dir,
            '项目模板 (*.mvsp.project.json);;JSON (*.json);;所有文件 (*.*)')
        if not path:
            return
        try:
            template = ProjectTemplate.load(path)
        except Exception as e:
            QMessageBox.critical(self, '打开失败', f'无法解析模板:\n{e}')
            return
        self._add_recent_template(path)
        self._open_template_browser(template)

    def _open_template_file(self, path):
        from .project_template import ProjectTemplate
        try:
            template = ProjectTemplate.load(path)
        except Exception as e:
            QMessageBox.critical(self, '打开失败', f'无法解析模板:\n{e}')
            return
        self._add_recent_template(path)
        self._open_template_browser(template)

    def _open_template_browser(self, template):
        from .project_browser import ProjectBrowser
        browser = ProjectBrowser(template, self)
        browser.entry_chosen.connect(self._apply_template_entry)
        browser.exec()

    def _apply_template_entry(self, template, entry):
        """把扫描结果应用到当前会话：重建布局 + 合并元数据 + 加载视频。"""
        from .layout_manager import LayoutConfig
        view_names = [p.view_name for p in template.patterns]
        n = len(view_names)
        rows, cols = template.layout_rows, template.layout_cols
        while rows * cols < n:
            cols += 1
        layout_cfg = LayoutConfig(rows=rows, cols=cols, view_names=view_names)
        self._apply_layout_config(layout_cfg)

        # 合并元数据：模板默认值 + 分组键（分组键覆盖同名）
        md = SessionMetadata()
        for k, v in template.metadata_template.items():
            if v:
                md.set(k, v)
        for k, v in entry.keys.items():
            md.set(k, v)
        self.metadata = md
        self.metadata_bar.set_metadata(md)
        self._update_title()

        # 按 patterns 顺序加载视频到对应格子
        self.controller.pause()
        for slot_idx, vname in enumerate(view_names):
            fpath = entry.videos.get(vname)
            if not fpath or not Path(fpath).exists():
                continue
            pos = self._view_positions.get(vname)
            if pos is None:
                continue
            meta = probe_video_metadata(fpath)
            if meta["total_frames"] <= 0:
                continue
            self.controller.video_info[vname] = {
                "path": fpath,
                "total_frames": meta["total_frames"],
                "fps": meta["fps"],
                "has_audio": meta["has_audio"],
                "width": meta.get("width", 0),
                "height": meta.get("height", 0),
                "duration_sec": meta.get("duration_sec", 0.0),
                "codec": meta.get("codec", ""),
            }
            self.controller.offsets.setdefault(vname, 0)
            self.controller.enabled_views.add(vname)

            # 清理旧格子
            if vname in self.cells:
                old = self.cells.pop(vname)
                old.cleanup()
                self.grid_layout.removeWidget(old)
                old.deleteLater()

            self._create_cell(vname, pos[0], pos[1])

        # 按顺序初始化后端
        self._backend_queue = list(self.cells.keys())
        self._backend_init_complete = False
        QTimer.singleShot(200, self._init_next_backend)

        self.statusBar().showMessage(
            f"已加载模板「{template.name}」: {entry.display_key}, "
            f"{len(entry.videos)}/{n} 个视角", 5000)

    def _apply_layout_config(self, layout_cfg):
        """应用新的布局配置：清空并重建网格。"""
        self.controller.pause()
        self.play_timer.stop()
        self._ui_timer.stop()
        self.sync_timer.stop()

        for vn, cell in self.cells.items():
            cell.cleanup()
            self.grid_layout.removeWidget(cell)
            cell.deleteLater()
        self.cells.clear()
        self._slot_widgets.clear()
        self.controller.video_info.clear()
        self.controller.offsets.clear()
        self.controller.enabled_views.clear()
        self.controller.markers.clear()
        self.controller.base_frame = 0
        self.controller.session_path = None
        self.controller.saved = True

        self.layout_config = layout_cfg
        self._rebuild_view_maps()
        self._populate_grid()
        self._update_status()
        self._update_title()

    def _add_recent_template(self, path):
        s = QSettings('MultiViewSyncPlayer', 'App')
        recent = list(s.value('recent_templates', [], type=list) or [])
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        s.setValue('recent_templates', recent[:5])
        self._rebuild_recent_templates_menu()

    def _rebuild_recent_templates_menu(self):
        self.recent_templates_menu.clear()
        s = QSettings('MultiViewSyncPlayer', 'App')
        recent = list(s.value('recent_templates', [], type=list) or [])
        if not recent:
            a = QAction('（无）', self)
            a.setEnabled(False)
            self.recent_templates_menu.addAction(a)
            return
        for p in recent:
            a = QAction(Path(p).name, self)
            a.setToolTip(p)
            a.triggered.connect(lambda _=False, pp=p: self._open_template_file(pp))
            self.recent_templates_menu.addAction(a)

    # ---- 媒体库浏览器 ----

    def _connect_library_dock(self):
        d = self.library_dock
        d.open_subject.connect(self._slot_open_subject)
        d.open_view.connect(self._slot_open_view)
        d.import_requested.connect(self._slot_import_requested)
        d.library_root_changed.connect(self._slot_library_root_changed)

    def _slot_open_subject(self, subject: SubjectEntry):
        lib_root = self.library_dock.library_root()
        if not lib_root:
            return

        views = self._sort_views_by_direction(subject.views)
        n = len(views)

        # 确保布局足够，然后完全重建
        cfg = fit_layout_to_views(self.layout_config, n)
        self._apply_layout_config(cfg)

        # 按顺序将视角加载到 slot
        loaded = []
        for i, view in enumerate(views):
            if i >= len(self._view_names):
                break
            vn = self._view_names[i]
            abs_path = lib_root / view.video_path
            if not abs_path.exists():
                continue
            meta = probe_video_metadata(str(abs_path))
            if meta["total_frames"] <= 0:
                continue
            pos = self._view_positions.get(vn)
            if pos is None:
                continue
            self.controller.video_info[vn] = {
                "path": str(abs_path),
                "total_frames": meta["total_frames"],
                "fps": meta["fps"],
                "has_audio": meta["has_audio"],
                "width": meta.get("width", 0),
                "height": meta.get("height", 0),
                "duration_sec": meta.get("duration_sec", 0.0),
                "codec": meta.get("codec", ""),
            }
            self.controller.offsets[vn] = 0
            self.controller.enabled_views.add(vn)
            self._create_cell(vn, pos[0], pos[1])
            loaded.append(vn)

        if loaded:
            self._backend_queue = loaded
            self._backend_init_complete = False
            QTimer.singleShot(200, self._init_next_backend)
        self._update_status()
        self._update_title()

    def _sort_views_by_direction(self, views):
        order = {"front": 0, "back": 1, "left": 2, "right": 3,
                 "top": 4, "bottom": 5}
        return sorted(views,
                      key=lambda v: (order.get(v.direction or "", 99),
                                     v.index or 0))

    def _slot_open_view(self, view: ViewEntry):
        lib_root = self.library_dock.library_root()
        if not lib_root:
            return
        abs_path = lib_root / view.video_path
        if not abs_path.exists():
            return
        vn = self._find_empty_slot()
        if vn is None:
            vn = self._view_names[0] if self._view_names else None
        if vn is None:
            return
        self._on_manual_video_selected(vn, str(abs_path))

    def _find_empty_slot(self):
        for vn in self._view_names:
            if vn not in self.controller.video_info:
                return vn
        return None

    def _slot_import_requested(self):
        wizard = ImportWizard(parent=self)
        if wizard.exec() == QDialog.Accepted:
            plan = wizard.get_plan()
            ImportExecutor(plan).run(dry_run=False)
            self.library_dock.set_library_root(plan.library_root)

    def _slot_library_root_changed(self, root):
        self.setWindowTitle(f"多视角同步播放器 — [library: {root.name}]")

    # ---- 首次运行欢迎 ----

    def _show_welcome_if_first_run(self):
        settings = QSettings('MultiViewSyncPlayer', 'App')
        if not settings.value('welcomed', False, type=bool):
            self._show_quickstart()
            settings.setValue('welcomed', True)

    # ---- 窗口几何持久化 ----

    def _restore_geometry(self):
        try:
            if PLAYER_CONFIG_PATH.exists():
                with open(PLAYER_CONFIG_PATH, "r") as f:
                    cfg = json.load(f)
                geo = cfg.get("geometry")
                if geo and len(geo) == 4:
                    self.setGeometry(*geo)
                if cfg.get("maximized"):
                    self.showMaximized()
        except Exception:
            pass

    def _save_geometry(self):
        try:
            PLAYER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            cfg = {}
            if PLAYER_CONFIG_PATH.exists():
                with open(PLAYER_CONFIG_PATH, "r") as f:
                    cfg = json.load(f)
            g = self.geometry()
            cfg["geometry"] = [g.x(), g.y(), g.width(), g.height()]
            cfg["maximized"] = self.isMaximized()
            with open(PLAYER_CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    # ---- 清理 ----

    def closeEvent(self, event):
        self.controller.pause()
        self.play_timer.stop()
        self._ui_timer.stop()
        self.sync_timer.stop()
        for cell in self.cells.values():
            cell.cleanup()
        self._save_geometry()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        super().closeEvent(event)
