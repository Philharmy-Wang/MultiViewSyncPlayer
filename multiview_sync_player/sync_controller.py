"""
multiview_sync_player.sync_controller — Sync control logic

Manages base_frame, per-view offsets, playback state, markers.
Save/load uses a generic session file path (no business-specific fields).
"""

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .config import SPEED_STEPS, DEFAULT_FPS


class SyncController(QObject):
    """Central state manager for synchronization and playback."""

    base_frame_changed = Signal(int)            # base_frame updated
    offset_changed = Signal(str, int)           # (view_name, new_offset)
    playback_toggled = Signal(bool)             # is_playing
    speed_changed = Signal(int)                 # speed_index
    markers_changed = Signal(list)              # marker list updated

    def __init__(self):
        super().__init__()
        self.base_frame = 0
        self.offsets = {}          # {view_name: int}
        self.is_playing = False
        self.speed_index = 2       # 1.0x
        self.selected_view = None
        self.markers = []          # [{frame, time_str, note, view_frames}]
        self.video_info = {}       # {view_name: {path, total_frames, fps, ...}}
        self.enabled_views = set() # enabled view set
        self.session_path = None   # path to .mvsp.json session file
        self.saved = True

    # ---- Frame operations ----

    def step_frames(self, delta: int):
        if not self.video_info:
            return
        mx = self._max_base_frame()
        self.base_frame = max(0, min(self.base_frame + delta, mx))
        self.saved = False
        self.base_frame_changed.emit(self.base_frame)

    def seek_to(self, frame: int):
        mx = self._max_base_frame()
        self.base_frame = max(0, min(frame, mx))
        self.saved = False
        self.base_frame_changed.emit(self.base_frame)

    def seek_to_start(self):
        """Return to start (preserving offsets)."""
        self.seek_to(0)

    def _max_base_frame(self) -> int:
        mx = 0
        for vn, info in self.video_info.items():
            if vn not in self.enabled_views:
                continue
            eff = info["total_frames"] - self.offsets.get(vn, 0)
            if eff > mx:
                mx = eff
        return max(0, mx - 1)

    # ---- Offsets ----

    def adjust_offset(self, view: str, delta: int):
        self.offsets[view] = self.offsets.get(view, 0) + delta
        self.saved = False
        self.offset_changed.emit(view, self.offsets[view])

    def reset_offsets(self):
        for vn in list(self.offsets.keys()):
            self.offsets[vn] = 0
            self.offset_changed.emit(vn, 0)
        self.saved = False

    # ---- Playback ----

    def toggle_play(self):
        self.is_playing = not self.is_playing
        self.playback_toggled.emit(self.is_playing)

    def pause(self):
        if self.is_playing:
            self.is_playing = False
            self.playback_toggled.emit(False)

    def set_speed(self, idx: int):
        if 0 <= idx < len(SPEED_STEPS):
            self.speed_index = idx
            self.speed_changed.emit(idx)

    def speed_up(self):
        if self.speed_index < len(SPEED_STEPS) - 1:
            self.set_speed(self.speed_index + 1)

    def speed_down(self):
        if self.speed_index > 0:
            self.set_speed(self.speed_index - 1)

    @property
    def speed(self) -> float:
        return SPEED_STEPS[self.speed_index]

    # ---- View enable/disable ----

    def set_view_enabled(self, view: str, enabled: bool):
        if enabled:
            self.enabled_views.add(view)
        else:
            self.enabled_views.discard(view)

    def is_view_enabled(self, view: str) -> bool:
        return view in self.enabled_views

    # ---- Markers ----

    def add_marker(self, note: str = ""):
        fps = DEFAULT_FPS
        for vn, info in self.video_info.items():
            fps = info.get("fps", DEFAULT_FPS)
            break
        sec = self.base_frame / fps if fps > 0 else 0
        mm, ss = divmod(int(sec), 60)
        ms = int((sec - int(sec)) * 100)
        marker = {
            "frame": self.base_frame,
            "time_str": f"{mm:02d}:{ss:02d}.{ms:02d}",
            "note": note or f"Marker {len(self.markers) + 1}",
            "view_frames": {
                vn: self.base_frame + self.offsets.get(vn, 0)
                for vn in self.video_info
            },
        }
        self.markers.append(marker)
        self.saved = False
        self.markers_changed.emit(self.markers)

    def remove_marker(self, idx: int):
        if 0 <= idx < len(self.markers):
            self.markers.pop(idx)
            self.saved = False
            self.markers_changed.emit(self.markers)

    def jump_to_marker(self, idx: int):
        if 0 <= idx < len(self.markers):
            self.seek_to(self.markers[idx]["frame"])

    # ---- Save / Load ----

    def save(self, path: str = None) -> bool:
        """Save session to JSON file.

        Args:
            path: File path to save to. If None, uses self.session_path.
                  Must have a valid path to save.
        """
        out_path = Path(path) if path else (
            Path(self.session_path) if self.session_path else None)
        if not out_path:
            return False

        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "0.1.0",
            "created": datetime.now().isoformat(timespec="seconds"),
            "offsets": dict(self.offsets),
            "markers": self.markers,
            "videos": {
                vn: {
                    "path": info["path"],
                    "total_frames": info["total_frames"],
                    "fps": info["fps"],
                    "has_audio": info.get("has_audio", False),
                }
                for vn, info in self.video_info.items()
            },
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.saved = True
        self.session_path = str(out_path)
        print(f"Session saved: {out_path}")
        return True

    def load(self, path: str) -> bool:
        """Load session from JSON file.

        Args:
            path: File path to load from.
        """
        f = Path(path)
        if not f.exists():
            return False
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if "offsets" in data:
                self.offsets = data["offsets"]
            if "markers" in data:
                self.markers = data["markers"]
            self.session_path = str(f)
            self.saved = True
            print(f"Session loaded: {f}")
            return True
        except Exception as e:
            print(f"Session load failed: {e}")
            return False

    def get_target_frame(self, view: str) -> int:
        """Get the absolute frame number for a given view."""
        return self.get_target_frame_at(view, self.base_frame)

    def get_target_frame_at(self, view: str, base_frame: int) -> int:
        """Map any master frame to a clamped per-view frame."""
        offset = self.offsets.get(view, 0)
        total = self.video_info.get(view, {}).get("total_frames", 0)
        target = base_frame + offset
        return max(0, min(target, total - 1)) if total > 0 else 0

    def master_view(self, eligible_views=None):
        """Return the explicit reference view used for the master clock."""
        eligible = set(eligible_views) if eligible_views is not None else None
        for view in self.video_info:
            if view not in self.enabled_views:
                continue
            if eligible is None or view in eligible:
                return view
        return None

    def master_fps(self, eligible_views=None) -> float:
        view = self.master_view(eligible_views)
        if view is None:
            return DEFAULT_FPS
        fps = float(self.video_info.get(view, {}).get("fps", DEFAULT_FPS))
        return fps if fps > 0 else DEFAULT_FPS

    def fps_mismatches(self, eligible_views=None, tolerance=0.01):
        """Return enabled views whose FPS differs from the reference view."""
        eligible = set(eligible_views) if eligible_views is not None else None
        master = self.master_view(eligible)
        if master is None:
            return {}
        reference = self.master_fps(eligible)
        mismatches = {}
        for view, info in self.video_info.items():
            if view not in self.enabled_views:
                continue
            if eligible is not None and view not in eligible:
                continue
            fps = float(info.get("fps", DEFAULT_FPS))
            if abs(fps - reference) > tolerance:
                mismatches[view] = fps
        return mismatches

    def frame_to_time_str(self, frame: int, fps: float = None) -> str:
        if fps is None:
            fps = DEFAULT_FPS
        if fps <= 0:
            return "--:--.--"
        sec = frame / fps
        mm, ss = divmod(int(sec), 60)
        ff = int((sec - int(sec)) * 100)
        return f"{mm:02d}:{ss:02d}.{ff:02d}"
