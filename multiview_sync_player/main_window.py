"""
multiview_sync_player.main_window — 主窗口

可配置网格 + 全局工具栏 + 元数据栏 + 状态栏。
管理 VideoCell 生命周期，连接信号。
支持同步锁控制、手动视频选择、会话管理、可配置布局、启动向导。
播放采用消费者 pull 模式：定时器 tick 从各解码线程缓冲区取帧。
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox,
    QStatusBar, QFileDialog, QDialog, QMenu, QMenuBar, QLabel, QFrame,
)
from PySide6.QtCore import Qt, QTimer, Signal, QPoint, QSettings
from PySide6.QtGui import QShortcut, QKeySequence, QAction

from .config import (
    SPEED_STEPS, PLAYER_CONFIG_PATH, DEFAULT_FPS, BACKEND,
    COLOR_PANEL_BG, COLOR_ACCENT, COLOR_TEXT, COLOR_TEXT_DIM,
    VIEW_COLORS,
)
from .styles import DARK_THEME_QSS
from .video_decoder import probe_video_metadata
from .sync_controller import SyncController
from .global_toolbar import GlobalToolbar
from .video_cell import VideoCell, DraggableHeader
from .metadata import SessionMetadata
from .layout_manager import LayoutConfig


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

    def __init__(self, session_path=None, backend='opencv', layout_config=None):
        super().__init__()
        self.setWindowTitle("多视角同步播放器")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 900)

        from . import config as cfg
        cfg.BACKEND = backend

        self.controller = SyncController()
        self.metadata = SessionMetadata()
        self.cells = {}
        self._slot_widgets = {}
        self.temp_dir = tempfile.mkdtemp(prefix="mvsp_")

        if layout_config:
            self.layout_config = layout_config
        else:
            self.layout_config = LayoutConfig(rows=2, cols=3)
        self._rebuild_view_maps()

        self._build_menubar()
        self._build_ui()
        self._connect_signals()
        self._setup_shortcuts()

        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.PreciseTimer)
        self.play_timer.timeout.connect(self._on_play_tick)

        self._ui_timer = QTimer(self)
        self._ui_timer.setTimerType(Qt.CoarseTimer)
        self._ui_timer.timeout.connect(self._on_ui_refresh)

        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self._sync_correction)

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
                ctrl.adjust_offset(ctrl.selected_view, d); return
            if key == Qt.Key_Right:
                d = (25 if mods & Qt.ShiftModifier
                     else 250 if mods & Qt.ControlModifier else 1)
                ctrl.adjust_offset(ctrl.selected_view, d); return
        super().keyPressEvent(event)

    # ---- 会话回调 ----

    def _on_session_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开会话", "",
            "会话文件 (*.mvsp.json);;JSON 文件 (*.json);;所有文件 (*)")
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
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"无法加载会话文件:\n{e}")
            return

        self._clear_all()
        self.controller.session_path = path

        layout_data = data.get("layout", {})
        if layout_data:
            self.layout_config = LayoutConfig.from_dict(layout_data)
            self._rebuild_view_maps()
            self._populate_grid()

        videos = data.get("videos", {})
        offsets = data.get("offsets", {})
        markers = data.get("markers", [])

        for vn, vinfo in videos.items():
            video_path = vinfo.get("path", "")
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
            meta = probe_video_metadata(video_path)
            if meta["total_frames"] <= 0:
                continue
            self.controller.video_info[vn] = {
                "path": video_path,
                "total_frames": meta["total_frames"],
                "fps": meta["fps"],
                "has_audio": meta["has_audio"],
            }
            self.controller.offsets[vn] = offsets.get(vn, 0)
            self.controller.enabled_views.add(vn)
            self._create_cell(vn, pos[0], pos[1])

        self.controller.markers = markers
        meta_data = data.get("metadata", {})
        self.metadata = SessionMetadata.from_dict(meta_data)
        self.metadata_bar.set_metadata(self.metadata)

        self._backend_queue = list(self.cells.keys())
        QTimer.singleShot(200, self._init_next_backend)

    # ---- 播放控制 ----

    def _toggle_play(self):
        self.controller.toggle_play()

    def _on_playback_toggled(self, playing):
        self.toolbar.set_play_button_text(playing)
        if playing:
            speed = SPEED_STEPS[self.controller.speed_index]
            interval = max(16, int(1000 / (DEFAULT_FPS * speed)))
            for cell in self.cells.values():
                if cell.synced:
                    cell.play()
                    cell.set_speed(speed)
            QTimer.singleShot(150, lambda: self._start_display_timer(interval))
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
        self.controller.base_frame += 1
        self.controller.saved = False
        for vn, cell in self.cells.items():
            if not cell.synced or not self.controller.is_view_enabled(vn):
                continue
            target = self.controller.base_frame + self.controller.offsets.get(vn, 0)
            if cell.decoder:
                qimg = cell.decoder.get_frame(target)
                if qimg:
                    cell.display_image(qimg, target, fast=True)

    def _on_ui_refresh(self):
        if not self.controller.is_playing:
            return
        base = self.controller.base_frame
        for vn, cell in self.cells.items():
            if not cell.synced or not self.controller.is_view_enabled(vn):
                continue
            target = base + self.controller.offsets.get(vn, 0)
            cell.overlay.current_frame = target
            cell.overlay.update()
            cell.slider.blockSignals(True)
            cell.slider.setValue(target)
            cell.slider.blockSignals(False)
            cell._update_time_label(target)
            cell.waveform.set_base_frame(base)
        self._update_status()
        self._update_title()

    def _set_speed(self, idx):
        self.controller.speed_index = idx
        self.toolbar.highlight_speed(idx)
        speed = SPEED_STEPS[idx]
        if self.controller.is_playing:
            self.play_timer.setInterval(
                max(16, int(1000 / (DEFAULT_FPS * speed))))
            for cell in self.cells.values():
                if cell.synced:
                    cell.set_speed(speed)

    def _step_frames(self, delta):
        was_playing = self.controller.is_playing
        if was_playing:
            self.controller.pause()
        self.controller.step_frames(delta)

    def _sync_correction(self):
        if BACKEND != "mpv":
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
        for vn, cell in self.cells.items():
            if cell.synced and self.controller.is_view_enabled(vn):
                target = frame + self.controller.offsets.get(vn, 0)
                cell.seek_to_frame(target)
                cell.update_overlay_for_base(frame)
            elif cell.synced:
                cell.waveform.set_base_frame(frame)
        self._update_status()
        self._update_title()

    def _on_offset_changed(self, view, offset):
        if view in self.cells:
            self.cells[view].set_offset(offset)
        self._on_base_frame_changed(self.controller.base_frame)

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
        cell.solo_stepping.connect(
            lambda vn, d: self.controller.adjust_offset(vn, d))
        cell.enable_toggled.connect(self.controller.set_view_enabled)
        cell.sync_toggled.connect(self._on_sync_toggled)
        cell.solo_position_jump.connect(self._on_solo_position_jump)
        cell.video_file_selected.connect(self._on_manual_video_selected)
        cell.waveform.position_clicked.connect(self.controller.seek_to)
        cell.grid_pos = (row, col)
        linear_idx = row * self.layout_config.cols + col
        cell.set_view_color(VIEW_COLORS[linear_idx % len(VIEW_COLORS)])
        self.cells[view_name] = cell
        self.grid_layout.addWidget(cell, row, col)
        self._slot_widgets[(row, col)] = cell

    # ---- Cell swap (drag & drop) ----

    def _swap_cells(self, src_pos, dst_pos):
        if src_pos == dst_pos:
            return
        src_widget = self._slot_widgets.get(src_pos)
        dst_widget = self._slot_widgets.get(dst_pos)
        if not src_widget or not dst_widget:
            return

        # Swap widget positions in grid layout
        self.grid_layout.removeWidget(src_widget)
        self.grid_layout.removeWidget(dst_widget)
        self.grid_layout.addWidget(src_widget, dst_pos[0], dst_pos[1])
        self.grid_layout.addWidget(dst_widget, src_pos[0], src_pos[1])

        # Swap grid_pos attributes
        src_widget.grid_pos = dst_pos
        dst_widget.grid_pos = src_pos

        # Swap view_colors
        src_color = src_widget.view_color
        dst_color = dst_widget.view_color
        src_widget.set_view_color(dst_color)
        dst_widget.set_view_color(src_color)

        # Update _slot_widgets mapping
        self._slot_widgets[src_pos] = dst_widget
        self._slot_widgets[dst_pos] = src_widget

    # ---- 后端初始化 ----

    def _init_single_cell(self, view_name):
        cell = self.cells.get(view_name)
        info = self.controller.video_info.get(view_name, {})
        if cell and info:
            cell.init_backend(info["path"], info["total_frames"], info["fps"])
            cell.set_offset(self.controller.offsets.get(view_name, 0))
            cell.waveform.set_video_meta(info["fps"], info["total_frames"])
            cell.waveform.set_offset(self.controller.offsets.get(view_name, 0))

    def _init_next_backend(self):
        if not self._backend_queue:
            self.controller.base_frame = 0
            self._on_base_frame_changed(0)
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
        self._audio_timer = QTimer(self)
        self._audio_timer.timeout.connect(self._load_next_audio)
        self._audio_timer.start(50)

    def _load_next_audio(self):
        if not hasattr(self, '_audio_queue') or not self._audio_queue:
            if hasattr(self, '_audio_timer'):
                self._audio_timer.stop()
            return
        vn = self._audio_queue.pop(0)
        info = self.controller.video_info.get(vn, {})
        if vn in self.cells and info.get("path"):
            self.cells[vn].load_audio(info["path"])
        if not self._audio_queue:
            self._audio_timer.stop()

    # ---- 同步锁回调 ----

    def _on_sync_toggled(self, view_name, synced):
        if synced:
            frame = self.controller.base_frame
            target = frame + self.controller.offsets.get(view_name, 0)
            self.cells[view_name].seek_to_frame(target)
            self.cells[view_name].update_overlay_for_base(frame)

    def _on_solo_position_jump(self, view_name, frame):
        cell = self.cells.get(view_name)
        if cell:
            cell.seek_to_frame(frame)

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
        if not self.controller.save():
            self._save_as()
        else:
            self._write_extras_to_session()

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存会话", "",
            "会话文件 (*.mvsp.json);;JSON 文件 (*.json);;所有文件 (*)")
        if path:
            if not path.endswith(".json"):
                path += ".mvsp.json"
            self.controller.save(path)
            self._write_extras_to_session()

    def _write_extras_to_session(self):
        sp = self.controller.session_path
        if not sp or not Path(sp).exists():
            return
        try:
            with open(sp, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["metadata"] = self.metadata.to_dict()
            data["layout"] = self.layout_config.to_dict()
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

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
        self.status_bar.showMessage(
            f"帧率: {DEFAULT_FPS:.0f} | 基准帧: {c.base_frame} | "
            f"速度: {speed:.2f}x | 布局: {layout_str} | "
            f"选中: {sel} | 同步: {synced_n}/{total_n} | "
            f"标记: {nm} | 已保存: {mark}")

    def _update_title(self):
        c = self.controller
        total = 0
        for info in c.video_info.values():
            total = max(total, info.get("total_frames", 0))
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
            "会话文件 (*.mvsp.json);;JSON 文件 (*.json);;所有文件 (*)")
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
