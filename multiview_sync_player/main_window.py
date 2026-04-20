"""
multiview_sync_player.main_window — Main window

Configurable grid + global toolbar + status bar.
Manages VideoCell lifecycle, connects signals.
Supports sync lock control, manual video selection, session management.
Playback uses consumer-pull model: timer tick pulls frames from decoder buffers.
"""

import json
import shutil
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QGridLayout, QMessageBox, QStatusBar,
    QFileDialog,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QShortcut, QKeySequence

from .config import (
    DEFAULT_GRID_ROWS, DEFAULT_GRID_COLS, SPEED_STEPS,
    PLAYER_CONFIG_PATH, DEFAULT_FPS, BACKEND,
)
from .styles import DARK_THEME_QSS
from .video_decoder import probe_video_metadata
from .sync_controller import SyncController
from .global_toolbar import GlobalToolbar
from .video_cell import VideoCell


class _EmptySlot(QWidget):
    """Empty grid slot placeholder. Double-click to select video."""

    double_clicked = Signal(str)

    def __init__(self, view_name: str, label="No video\nDouble-click to select",
                 parent=None):
        super().__init__(parent)
        self._view_name = view_name
        self._label = label
        self.setMouseTracking(True)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen, QFont
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#222222"))
        p.setPen(QPen(QColor("#3c3c3c"), 1))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        p.setPen(QColor("#888888"))
        p.setFont(QFont("Microsoft YaHei", 11))
        p.drawText(self.rect(), Qt.AlignCenter, self._label)
        p.end()

    def mouseDoubleClickEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select video — {self._view_name}", "",
            "Video files (*.mp4 *.avi *.mkv *.mov);;All files (*)")
        if path:
            self.double_clicked.emit(path)


class MainWindow(QMainWindow):
    """Multi-view video synchronized playback main window."""

    def __init__(self, session_path=None, backend='opencv'):
        super().__init__()
        self.setWindowTitle("MultiViewSyncPlayer")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 900)

        # Inject backend config
        from . import config as cfg
        cfg.BACKEND = backend

        self.controller = SyncController()
        self.cells = {}           # {view_name: VideoCell}
        self._slot_widgets = {}   # {(row, col): widget}
        self.temp_dir = tempfile.mkdtemp(prefix="mvsp_")

        # Grid dimensions (can be changed by session / layout manager later)
        self._grid_rows = DEFAULT_GRID_ROWS
        self._grid_cols = DEFAULT_GRID_COLS

        # Build view name list from grid dimensions
        self._view_names = []
        self._view_positions = {}  # {view_name: (row, col)}
        idx = 1
        for r in range(self._grid_rows):
            for c in range(self._grid_cols):
                vn = f"View {idx}"
                self._view_names.append(vn)
                self._view_positions[vn] = (r, c)
                idx += 1

        self._build_ui()
        self._connect_signals()
        self._setup_shortcuts()

        # Playback timer — precise timing + consumer-pull model
        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.PreciseTimer)
        self.play_timer.timeout.connect(self._on_play_tick)

        # UI refresh timer — 5Hz throttle for status bar / title / slider
        self._ui_timer = QTimer(self)
        self._ui_timer.setTimerType(Qt.CoarseTimer)
        self._ui_timer.timeout.connect(self._on_ui_refresh)

        # Sync correction timer (mpv backend)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self._sync_correction)

        self._restore_geometry()

        # Load session if provided
        if session_path:
            QTimer.singleShot(100, lambda: self._load_session(session_path))

        self.setStyleSheet(DARK_THEME_QSS)

    # ---- UI construction ----

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(4, 4, 4, 4)
        ml.setSpacing(4)

        self.toolbar = GlobalToolbar()
        ml.addWidget(self.toolbar)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(2)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        for c in range(self._grid_cols):
            self.grid_layout.setColumnStretch(c, 1)
        for r in range(self._grid_rows):
            self.grid_layout.setRowStretch(r, 1)

        for vn in self._view_names:
            r, c = self._view_positions[vn]
            e = _EmptySlot(vn, f"{vn}\nDouble-click to select video")
            e.double_clicked.connect(
                lambda path, v=vn: self._on_manual_video_selected(v, path))
            self.grid_layout.addWidget(e, r, c)
            self._slot_widgets[(r, c)] = e

        ml.addWidget(self.grid_widget, 1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status()

    # ---- Signal connections ----

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
        t.help_requested.connect(self._show_help)

        ctrl.base_frame_changed.connect(self._on_base_frame_changed)
        ctrl.offset_changed.connect(self._on_offset_changed)
        ctrl.playback_toggled.connect(self._on_playback_toggled)
        ctrl.markers_changed.connect(self._update_status)

    # ---- Keyboard shortcuts ----

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
        sc("Ctrl+S", self._save)
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

    # ---- Session callbacks ----

    def _on_session_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Session", "",
            "Session files (*.mvsp.json);;JSON files (*.json);;All files (*)")
        if path:
            self._load_session(path)

    def _on_session_new(self):
        if not self.controller.saved and self.cells:
            ret = QMessageBox.question(
                self, "Unsaved Changes",
                "Current session has unsaved changes. Discard?",
                QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        self._clear_all()

    def _load_session(self, path: str):
        """Load a session file: restore videos, offsets, markers."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load session:\n{e}")
            return

        self._clear_all()
        self.controller.session_path = path

        videos = data.get("videos", {})
        offsets = data.get("offsets", {})
        markers = data.get("markers", [])

        # Load each video into its slot
        for vn, vinfo in videos.items():
            video_path = vinfo.get("path", "")
            if not video_path or not Path(video_path).exists():
                print(f"[Session] Video not found, skipping: {video_path}")
                continue

            # Map view name to grid position
            pos = self._view_positions.get(vn)
            if pos is None:
                # Try to find an empty slot
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

        # Restore markers
        self.controller.markers = markers

        # Initialize backends sequentially
        self._backend_queue = list(self.cells.keys())
        QTimer.singleShot(200, self._init_next_backend)

    # ---- Playback control (consumer-pull model) ----

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
        """Display timer tick: pull frames from decoder buffers (consumer mode)."""
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
        """Low-frequency UI refresh: status bar / title / overlay / slider / waveform."""
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
        """Global step: pause first, then seek to target frame."""
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

    # ---- base_frame / offset update (pause/seek) ----

    def _on_base_frame_changed(self, frame):
        """Pause/step/drag slider: seek to target frame."""
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

    # ---- Manual video selection ----

    def _on_manual_video_selected(self, view_name: str, file_path: str):
        pos = self._view_positions.get(view_name)
        if pos is None:
            return

        meta = probe_video_metadata(file_path)
        if meta["total_frames"] <= 0:
            QMessageBox.warning(self, "Cannot Open",
                                f"Cannot read video: {file_path}")
            return

        self.controller.video_info[view_name] = {
            "path": file_path,
            "total_frames": meta["total_frames"],
            "fps": meta["fps"],
            "has_audio": meta["has_audio"],
        }
        self.controller.offsets.setdefault(view_name, 0)
        self.controller.enabled_views.add(view_name)

        # Remove existing cell/slot at this position
        if view_name in self.cells:
            old = self.cells.pop(view_name)
            old.cleanup()
            self.grid_layout.removeWidget(old)
            old.deleteLater()

        self._create_cell(view_name, pos[0], pos[1])
        QTimer.singleShot(100, lambda: self._init_single_cell(view_name))

    def _create_cell(self, view_name: str, row: int, col: int):
        """Create a VideoCell and add it to the grid."""
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

        self.cells[view_name] = cell
        self.grid_layout.addWidget(cell, row, col)
        self._slot_widgets[(row, col)] = cell

    # ---- Backend initialization ----

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

    # ---- Sync lock callback ----

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

    # ---- View selection ----

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

    # ---- Markers ----

    def _mark_frame(self):
        self.controller.add_marker()
        self._update_status()

    # ---- Save ----

    def _save(self):
        if not self.controller.save():
            # No session path yet, do Save As
            self._save_as()

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session", "",
            "Session files (*.mvsp.json);;JSON files (*.json);;All files (*)")
        if path:
            if not path.endswith(".json"):
                path += ".mvsp.json"
            self.controller.save(path)

    # ---- Status bar / title ----

    def _update_status(self):
        c = self.controller
        speed = SPEED_STEPS[c.speed_index]
        sel = c.selected_view or "None"
        mark = "Y" if c.saved else "X"
        nm = len(c.markers)
        synced_n = sum(1 for cell in self.cells.values() if cell.synced)
        total_n = len(self.cells)
        self.status_bar.showMessage(
            f"FPS: {DEFAULT_FPS:.0f} | Base frame: {c.base_frame} | "
            f"Speed: {speed:.2f}x | Selected: {sel} | "
            f"Synced: {synced_n}/{total_n} | "
            f"Markers: {nm} | Saved: {mark}")

    def _update_title(self):
        c = self.controller
        total = 0
        for info in c.video_info.values():
            total = max(total, info.get("total_frames", 0))
        speed = SPEED_STEPS[c.speed_index]
        session = Path(c.session_path).name if c.session_path else "Untitled"
        self.setWindowTitle(
            f"MultiViewSyncPlayer — {session} — "
            f"Frame {c.base_frame}/{total} — {speed}x")

    # ---- Grid clear ----

    def _clear_all(self):
        """Stop playback and clear all cells, reset controller."""
        self.controller.pause()
        self.play_timer.stop()
        self._ui_timer.stop()
        self.sync_timer.stop()

        for vn, cell in self.cells.items():
            cell.cleanup()
            self.grid_layout.removeWidget(cell)
            cell.deleteLater()
        self.cells.clear()

        for vn in self._view_names:
            r, c = self._view_positions[vn]
            w = self._slot_widgets.get((r, c))
            if w:
                self.grid_layout.removeWidget(w)
                w.deleteLater()
            e = _EmptySlot(vn, f"{vn}\nDouble-click to select video")
            e.double_clicked.connect(
                lambda path, v=vn: self._on_manual_video_selected(v, path))
            self.grid_layout.addWidget(e, r, c)
            self._slot_widgets[(r, c)] = e

        self.controller.video_info.clear()
        self.controller.offsets.clear()
        self.controller.enabled_views.clear()
        self.controller.markers.clear()
        self.controller.base_frame = 0
        self.controller.session_path = None
        self.controller.saved = True
        self._update_status()
        self._update_title()

    # ---- Help ----

    def _show_help(self):
        view_list = "  ".join(
            f"{i+1}={vn}" for i, vn in enumerate(self._view_names))
        QMessageBox.information(self, "Keyboard Shortcuts", f"""
        <h3>Keyboard Shortcuts</h3>
        <table cellpadding='3' style='font-size:10pt'>
        <tr><td><b>Space</b></td><td>Play/Pause</td></tr>
        <tr><td><b>D/A/W/S/Q/E</b></td><td>Global frame step</td></tr>
        <tr><td><b>Home/End</b></td><td>Jump to start/end</td></tr>
        <tr><td><b>1~9</b></td><td>Select view slot</td></tr>
        <tr><td><b>0/Esc</b></td><td>Deselect</td></tr>
        <tr><td><b>Left/Right (selected)</b></td><td>Offset +-1/+-25/+-250</td></tr>
        <tr><td><b>M</b></td><td>Mark current frame</td></tr>
        <tr><td><b>R</b></td><td>Reset all offsets</td></tr>
        <tr><td><b>Ctrl+S</b></td><td>Save session</td></tr>
        <tr><td><b>+/-</b></td><td>Playback speed</td></tr>
        <tr><td><b>F</b></td><td>Fullscreen</td></tr>
        </table>
        <h3>Sync Lock</h3>
        <table cellpadding='3' style='font-size:10pt'>
        <tr><td><b>🔗 Locked</b></td><td>Follow global play/pause/step</td></tr>
        <tr><td><b>🔓 Unlocked</b></td><td>Independent play/drag slider</td></tr>
        </table>
        <p style='color:#888'>View slots: {view_list}<br>
        Double-click a slot to select a video file.</p>""")

    # ---- Window geometry persistence ----

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

    # ---- Cleanup ----

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
