"""
multiview_sync_player.video_decoder — Ring-buffer prefetch video decoder

Producer-consumer model: background thread decodes frames via cap.read(),
main thread pulls frames non-blocking via get_frame().

Also contains video metadata probing utility.
"""

import collections
import ctypes
import sys
import threading

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .config import DECODE_TARGET_WIDTH, DECODE_BUFFER_SIZE


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
    """Probe video file for fps, total_frames, has_audio.

    Returns dict with keys: path, fps, total_frames, has_audio.
    """
    from pathlib import Path
    cap = _safe_video_capture(video_path)
    if cap is None or not cap.isOpened():
        return {"path": str(video_path), "fps": 25.0, "total_frames": 0,
                "has_audio": False}

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.release()

    # Audio detection: check file extension and try ffprobe-like approach
    has_audio = Path(video_path).suffix.lower() in (
        ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv")

    return {
        "path": str(video_path),
        "fps": fps,
        "total_frames": total,
        "has_audio": has_audio,
    }


# ==================== Ring-buffer prefetch decoder ====================

class PrefetchDecoder(QThread):
    """
    Ring-buffer prefetch decoder (producer-consumer model).

    - Sequential playback: continuous cap.read(), no cap.set() random seek
    - Decode + resize + BGR->RGB all in worker thread
    - Main thread consumes via get_frame() (non-blocking)
    - First frame after seek is pushed via signal (only allowed push scenario)
    """

    frame_ready = Signal(int, object)  # frame_number, QImage (fast display after seek)

    def __init__(self, video_path, target_width=DECODE_TARGET_WIDTH,
                 buffer_size=DECODE_BUFFER_SIZE):
        super().__init__()
        from pathlib import Path
        self._video_path = Path(video_path)
        self._target_width = target_width
        self._buffer_size = buffer_size
        self.total_frames = 0
        self.fps = 25.0

        self._buffer = collections.deque(maxlen=buffer_size)
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

        # Thread control (all read/written under lock)
        self._running = True
        self._state = "paused"       # paused / playing
        self._seek_target = -1       # >= 0 means seek needed
        self._current_pos = 0        # cap's current frame position

    # ---- Producer thread ----

    def run(self):
        cap = _safe_video_capture(self._video_path)
        if cap is None:
            print(f"[Decoder] Cannot open: {self._video_path.name}")
            return

        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self._current_pos = 0

        while self._running:
            # ---- Check state under lock ----
            with self._condition:
                # PAUSED with no seek: wait for wake
                while (self._state == "paused"
                       and self._seek_target < 0
                       and self._running):
                    self._condition.wait(timeout=0.1)

                if not self._running:
                    break

                # Take seek request
                seek_req = self._seek_target
                self._seek_target = -1

                # Buffer full: wait briefly for consumer
                if seek_req < 0 and len(self._buffer) >= self._buffer_size:
                    self._condition.wait(timeout=0.005)
                    continue

            # ---- I/O and CPU work outside lock ----
            if seek_req >= 0:
                seek_req = max(0, min(seek_req, self.total_frames - 1))
                cap.set(cv2.CAP_PROP_POS_FRAMES, seek_req)
                self._current_pos = seek_req

            ret, frame = cap.read()
            if not ret:
                with self._condition:
                    self._state = "paused"
                continue

            # BGR->RGB + resize in worker thread
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame.shape[:2]
            if w > self._target_width:
                nw = self._target_width
                nh = int(h * nw / w)
                frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
            h, w, ch = frame.shape
            qimg = QImage(frame.data, w, h, ch * w,
                          QImage.Format_RGB888).copy()

            # ---- Put into buffer under lock ----
            with self._condition:
                # If seek was overridden, discard this frame
                if self._seek_target >= 0:
                    continue

                self._buffer.append((self._current_pos, qimg))
                self._current_pos += 1

                # First frame after seek: signal push to main thread
                if seek_req >= 0:
                    self.frame_ready.emit(seek_req, qimg)

        cap.release()

    # ---- Consumer interface (main thread) ----

    def get_frame(self, frame_number):
        """
        Main thread: pull frame from buffer.
        Returns QImage or None (frame not ready, caller should skip).
        """
        with self._condition:
            # Discard stale frames (number < frame_number)
            while self._buffer and self._buffer[0][0] < frame_number:
                self._buffer.popleft()

            # Check if first frame matches
            if self._buffer and self._buffer[0][0] == frame_number:
                _, qimg = self._buffer.popleft()
                self._condition.notify()
                return qimg

            return None

    # ---- Control interface (main thread) ----

    def seek(self, frame_number):
        """Request seek to frame. Clears buffer."""
        with self._condition:
            self._buffer.clear()
            self._seek_target = frame_number
            self._condition.notify()

    def set_playing(self, playing):
        """Toggle play/pause state."""
        with self._condition:
            self._state = "playing" if playing else "paused"
            self._condition.notify()

    def stop(self):
        """Stop the decoder thread."""
        with self._condition:
            self._running = False
            self._condition.notify()
        self.wait(3000)
