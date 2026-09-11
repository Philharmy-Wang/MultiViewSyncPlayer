"""
multiview_sync_player.video_decoder — Ring-buffer prefetch video decoder

Producer-consumer model: background thread decodes frames via cap.read(),
main thread pulls frames non-blocking via get_frame().

Also contains video metadata probing utility.
"""

import bisect
import collections
import ctypes
import subprocess
import sys
import threading
from time import perf_counter

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .config import (
    DECODE_TARGET_WIDTH,
    DECODE_BUFFER_SIZE,
    RECENT_FRAME_CACHE_SIZE,
    SEQUENTIAL_STEP_WINDOW,
    FFPROBE_PATH,
    SEEK_KEYFRAME_DECODE_MARGIN,
)


# ==================== Windows CJK path helpers ====================

def _get_short_path(long_path: str) -> str:
    """Get Windows 8.3 short path name for CJK path compatibility."""
    if sys.platform != "win32":
        return long_path
    try:
        buf_size = ctypes.windll.kernel32.GetShortPathNameW(long_path, None, 0)
        if buf_size == 0:
            return long_path
        buf = ctypes.create_unicode_buffer(buf_size)
        ctypes.windll.kernel32.GetShortPathNameW(long_path, buf, buf_size)
        return buf.value if buf.value else long_path
    except Exception:
        return long_path


def _safe_video_capture(path):
    """Open video with OpenCV, falling back to short path on Windows."""
    cap = cv2.VideoCapture(str(path))
    if cap.isOpened():
        return cap
    short = _get_short_path(str(path))
    if short != str(path):
        cap = cv2.VideoCapture(short)
        if cap.isOpened():
            return cap
    return None


# ==================== Video metadata probe ====================

def probe_video_metadata(video_path: str) -> dict:
    """Probe video metadata used by playback and session identity checks."""
    from pathlib import Path
    cap = _safe_video_capture(video_path)
    if cap is None or not cap.isOpened():
        return {"path": str(video_path), "fps": 25.0, "total_frames": 0,
                "has_audio": False, "width": 0, "height": 0,
                "duration_sec": 0.0, "codec": ""}

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = total / fps if fps > 0 and total > 0 else 0.0
    fourcc_value = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
    codec = ""
    if fourcc_value:
        codec = "".join(chr((fourcc_value >> (8 * idx)) & 0xFF)
                        for idx in range(4)).strip("\x00 ")
    cap.release()

    # Audio detection: check file extension and try ffprobe-like approach
    has_audio = Path(video_path).suffix.lower() in (
        ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv")

    return {
        "path": str(video_path),
        "fps": fps,
        "total_frames": total,
        "has_audio": has_audio,
        "width": width,
        "height": height,
        "duration_sec": duration,
        "codec": codec,
    }


# ==================== Ring-buffer prefetch decoder ====================

# path -> sorted keyframe frame-number list (shared across decoder threads)
_KEYFRAME_INDEX_CACHE = {}


def probe_keyframe_index(video_path, fps: float) -> list:
    """Return sorted keyframe frame numbers via ffprobe packet scan.

    Frame numbers are derived from packet PTS: floor((pts - start_pts) * fps),
    deliberately floored (never rounded up) so an anchor seek never starts
    *after* the real keyframe. Returns [] when ffprobe is unavailable or the
    stream cannot be indexed. Results are cached per video path.
    """
    from pathlib import Path
    path = Path(video_path)
    cached = _KEYFRAME_INDEX_CACHE.get(str(path))
    if cached is not None:
        return cached
    index = []
    if FFPROBE_PATH and fps > 0:
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run(
                [FFPROBE_PATH, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "packet=flags,pts_time",
                 "-of", "csv=p=0", str(path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=120, creationflags=creationflags)
            lines = proc.stdout.decode("ascii", errors="ignore").splitlines()
            start_pts = None
            for line in lines:
                parts = line.split(",")
                pts = None
                flags = ""
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        value = float(part)
                    except ValueError:
                        flags = part
                    else:
                        if pts is None:
                            pts = value
                if pts is None:
                    continue
                if start_pts is None:
                    start_pts = pts
                if flags.startswith("K"):
                    frame_number = int((pts - start_pts) * fps)
                    if frame_number < 0:
                        frame_number = 0
                    if not index or frame_number > index[-1]:
                        index.append(frame_number)
        except Exception:
            index = []
    _KEYFRAME_INDEX_CACHE[str(path)] = index
    return index


class PrefetchDecoder(QThread):
    """Generation-aware ring-buffer decoder with a recent-frame cache."""

    # request_id, exact frame number, QImage
    frame_ready = Signal(int, int, object)
    # request_id, requested frame number, human-readable error
    frame_failed = Signal(int, int, str)

    def __init__(self, video_path, target_width=DECODE_TARGET_WIDTH,
                 buffer_size=DECODE_BUFFER_SIZE,
                 cache_size=RECENT_FRAME_CACHE_SIZE):
        super().__init__()
        from pathlib import Path
        self._video_path = Path(video_path)
        self._target_width = target_width
        self._buffer_size = buffer_size
        self._cache_size = cache_size
        self.total_frames = 0
        self.fps = 25.0

        self._buffer = collections.deque(maxlen=buffer_size)
        self._cache = collections.OrderedDict()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

        self._running = True
        self._state = "paused"
        self._seek_request = None  # (request_id, target, requested_at)
        self._latest_request_id = 0
        self._current_pos = 0      # next frame returned by cap.read()

        self._last_seek_latency_ms = 0.0
        self._cache_hits = 0
        self._cache_misses = 0
        self._random_seeks = 0
        self._decoded_frames = 0

    @staticmethod
    def _to_qimage(frame, target_width):
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = frame.shape[:2]
        if w > target_width:
            nw = target_width
            nh = int(h * nw / w)
            frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        h, w, ch = frame.shape
        return QImage(frame.data, w, h, ch * w,
                      QImage.Format_RGB888).copy()

    def _cache_put_unlocked(self, frame_number, image):
        self._cache[frame_number] = image
        self._cache.move_to_end(frame_number)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _cache_get_unlocked(self, frame_number):
        image = self._cache.get(frame_number)
        if image is not None:
            self._cache.move_to_end(frame_number)
        return image

    def run(self):
        cap = _safe_video_capture(self._video_path)
        if cap is None:
            print(f"[Decoder] Cannot open: {self._video_path.name}")
            return

        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self._current_pos = 0
        # Keyframe index for reference-safe random seeks (HEVC/H.264):
        # a raw cap.set() into mid-GOP decodes P/B frames without their
        # references and yields gray/corrupt frames until the next keyframe.
        self._keyframes = probe_keyframe_index(self._video_path, self.fps)

        try:
            while True:
                with self._condition:
                    while (self._running and self._state == "paused"
                           and self._seek_request is None):
                        self._condition.wait(timeout=0.1)
                    if not self._running:
                        break

                    request = self._seek_request
                    self._seek_request = None
                    if request is None and len(self._buffer) >= self._buffer_size:
                        self._condition.wait(timeout=0.005)
                        continue

                if request is not None:
                    self._decode_request(cap, request)
                else:
                    self._decode_playback_frame(cap)
        finally:
            cap.release()

    def _keyframe_anchor(self, target: int):
        """Largest keyframe frame number <= target, or None without index."""
        if not self._keyframes:
            return None
        idx = bisect.bisect_right(self._keyframes, target) - 1
        if idx < 0:
            return None
        return self._keyframes[idx]

    def _decode_request(self, cap, request):
        request_id, target, requested_at = request
        if self.total_frames <= 0:
            self.frame_failed.emit(request_id, target, "video has no frames")
            return
        target = max(0, min(target, self.total_frames - 1))

        with self._condition:
            current_pos = self._current_pos
        sequential = (current_pos <= target
                      and target - current_pos <= SEQUENTIAL_STEP_WINDOW)
        if not sequential:
            # Anchor random seeks at a keyframe so decoding always starts
            # with a complete reference chain, then fast-forward to the
            # target with grab() (no convert/cache cost), keeping the last
            # SEEK_KEYFRAME_DECODE_MARGIN frames as cached reads.
            anchor = self._keyframe_anchor(target)
            if anchor is None:
                anchor = target
            cap.set(cv2.CAP_PROP_POS_FRAMES, anchor)
            current_pos = anchor
            with self._condition:
                self._current_pos = anchor
                self._random_seeks += 1
            grab_stop = max(anchor, target - SEEK_KEYFRAME_DECODE_MARGIN)
            while current_pos < grab_stop:
                if not cap.grab():
                    with self._condition:
                        is_latest = request_id == self._latest_request_id
                    if is_latest:
                        self.frame_failed.emit(
                            request_id, target,
                            f"decode failed at frame {current_pos}")
                    return
                current_pos += 1
                with self._condition:
                    self._current_pos = current_pos
                    self._decoded_frames += 1
                    if request_id != self._latest_request_id:
                        return

        while current_pos <= target:
            ret, frame = cap.read()
            if not ret:
                with self._condition:
                    is_latest = request_id == self._latest_request_id
                if is_latest:
                    self.frame_failed.emit(
                        request_id, target, f"decode failed at frame {current_pos}")
                return

            frame_number = current_pos
            current_pos += 1
            qimg = self._to_qimage(frame, self._target_width)

            with self._condition:
                self._current_pos = current_pos
                self._decoded_frames += 1
                self._cache_put_unlocked(frame_number, qimg)
                if request_id != self._latest_request_id:
                    return
                if frame_number == target:
                    self._buffer.append((frame_number, qimg))
                    self._last_seek_latency_ms = (
                        perf_counter() - requested_at) * 1000.0

            if frame_number == target:
                self.frame_ready.emit(request_id, frame_number, qimg)
                return

    def _decode_playback_frame(self, cap):
        with self._condition:
            frame_number = self._current_pos
        ret, frame = cap.read()
        if not ret:
            with self._condition:
                self._state = "paused"
            return
        qimg = self._to_qimage(frame, self._target_width)
        with self._condition:
            self._current_pos = frame_number + 1
            self._decoded_frames += 1
            self._cache_put_unlocked(frame_number, qimg)
            # A newly queued seek supersedes playback work already in flight.
            if self._seek_request is None:
                self._buffer.append((frame_number, qimg))

    # ---- Consumer interface (main thread) ----

    def has_frame(self, frame_number):
        with self._condition:
            return (frame_number in self._cache
                    or any(number == frame_number
                           for number, _ in self._buffer))

    def get_frame(self, frame_number):
        """Return one exact frame and release consumed prefetch capacity."""
        with self._condition:
            image = self._cache_get_unlocked(frame_number)
            if image is None:
                image = next(
                    (candidate for number, candidate in self._buffer
                     if number == frame_number), None)
            if image is None:
                return None
            while self._buffer and self._buffer[0][0] <= frame_number:
                self._buffer.popleft()
            self._condition.notify()
            return image

    def request_frame(self, frame_number, request_id):
        """Request an exact paused frame, serving cache hits immediately."""
        requested_at = perf_counter()
        with self._condition:
            self._latest_request_id = request_id
            image = self._cache_get_unlocked(frame_number)
            if image is not None:
                self._cache_hits += 1
                self._last_seek_latency_ms = 0.0
                next_ready = (
                    frame_number + 1 in self._cache
                    or any(number == frame_number + 1
                           for number, _ in self._buffer)
                )
                if not next_ready and self._current_pos != frame_number + 1:
                    # Commit the cached paused image immediately, but prime the
                    # sequential decoder in the background so Play can resume.
                    self._buffer.clear()
                    self._seek_request = (
                        request_id, frame_number, requested_at)
                    self._condition.notify()
            else:
                self._cache_misses += 1
                # A seek changes the producer timeline.  Keeping old prefetch
                # entries would make the deque non-monotonic and can leave a
                # stale high frame at the head, permanently blocking capacity.
                self._buffer.clear()
                self._seek_request = (request_id, frame_number, requested_at)
                self._condition.notify()
        if image is not None:
            self.frame_ready.emit(request_id, frame_number, image)

    def seek(self, frame_number, request_id=0):
        """Backward-compatible exact-frame request."""
        self.request_frame(frame_number, request_id)

    def set_playing(self, playing):
        with self._condition:
            self._state = "playing" if playing else "paused"
            self._condition.notify()

    def metrics(self):
        with self._condition:
            return {
                "buffer_occupancy": len(self._buffer),
                "buffer_capacity": self._buffer_size,
                "buffer_head": self._buffer[0][0] if self._buffer else None,
                "buffer_tail": self._buffer[-1][0] if self._buffer else None,
                "cache_occupancy": len(self._cache),
                "cache_capacity": self._cache_size,
                "cache_min": min(self._cache) if self._cache else None,
                "cache_max": max(self._cache) if self._cache else None,
                "seek_latency_ms": self._last_seek_latency_ms,
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "random_seeks": self._random_seeks,
                "decoded_frames": self._decoded_frames,
                "decoder_position": self._current_pos,
            }

    def stop(self):
        with self._condition:
            self._running = False
            self._condition.notify()
        if not self.wait(3000):
            print(f"[Decoder] Timed out stopping: {self._video_path.name}")
