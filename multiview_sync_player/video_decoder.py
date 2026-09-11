"""
multiview_sync_player.video_decoder — Ring-buffer prefetch video decoder

Producer-consumer model: background thread decodes frames via cap.read(),
main thread pulls frames non-blocking via get_frame().

Also contains video metadata probing utility.
"""

import bisect
import collections
import ctypes
import sys
import threading
from time import perf_counter

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .config import (
    DECODE_TARGET_WIDTH,
    DECODE_THREADS_PER_VIEW,
    OPENCV_INTERNAL_THREADS,
    DECODE_BUFFER_SIZE,
    RECENT_FRAME_CACHE_SIZE,
    SEQUENTIAL_STEP_WINDOW,
    FFPROBE_PATH,
    SEEK_KEYFRAME_DECODE_MARGIN,
)
from .media_cache import (
    get_keyframes, get_metadata, get_packet_count, put_keyframes, put_metadata,
    record_keyframe_scan,
)
from .process_utils import run_hidden


# Resize/colour operations are already distributed across per-view decoder
# threads.  A large global OpenCV pool inside each operation causes nested
# oversubscription without changing decoded pixels.
cv2.setNumThreads(OPENCV_INTERNAL_THREADS)


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


def _safe_video_capture(path, decoder_threads=None):
    """Open video with OpenCV, falling back to short path on Windows."""
    def open_path(candidate):
        if decoder_threads and hasattr(cv2, "CAP_PROP_N_THREADS"):
            cap = cv2.VideoCapture(
                str(candidate), cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_N_THREADS, int(decoder_threads)])
            if cap.isOpened():
                return cap
            cap.release()
        return cv2.VideoCapture(str(candidate))

    cap = open_path(path)
    if cap.isOpened():
        return cap
    short = _get_short_path(str(path))
    if short != str(path):
        cap = open_path(short)
        if cap.isOpened():
            return cap
    return None


# ==================== Video metadata probe ====================

def probe_video_metadata(video_path: str, use_cache: bool = True) -> dict:
    """Probe video metadata used by playback and session identity checks."""
    from pathlib import Path
    if use_cache:
        try:
            cached = get_metadata(video_path)
        except OSError:
            cached = None
        if cached is not None:
            return _apply_cached_packet_count(video_path, cached)
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

    result = {
        "path": str(video_path),
        "fps": fps,
        "total_frames": total,
        "has_audio": has_audio,
        "width": width,
        "height": height,
        "duration_sec": duration,
        "codec": codec,
    }
    if use_cache:
        try:
            put_metadata(video_path, result)
        except OSError:
            pass
    return result


# ==================== Ring-buffer prefetch decoder ====================

# path -> sorted keyframe frame-number list (shared across decoder threads)
_KEYFRAME_INDEX_CACHE = {}
_KEYFRAME_SCAN_LOCKS = {}
_KEYFRAME_SCAN_LOCKS_GUARD = threading.Lock()


def _apply_cached_packet_count(video_path, metadata):
    """Correct container frame-count estimates after a full packet scan."""
    try:
        packet_count = get_packet_count(video_path)
    except OSError:
        packet_count = None
    if packet_count and metadata.get("total_frames") != packet_count:
        metadata = dict(metadata)
        metadata["total_frames"] = packet_count
        fps = float(metadata.get("fps") or 0)
        if fps > 0:
            metadata["duration_sec"] = packet_count / fps
    return metadata


def probe_keyframe_index(video_path, fps: float) -> list:
    """Return sorted keyframe frame numbers via ffprobe packet scan.

    Frame numbers are derived from packet PTS: floor((pts - start_pts) * fps),
    deliberately floored (never rounded up) so an anchor seek never starts
    *after* the real keyframe. Returns [] when ffprobe is unavailable or the
    stream cannot be indexed. Results are cached per video path.
    """
    from pathlib import Path
    path = Path(video_path)
    cache_key = str(path.resolve())
    cached = _KEYFRAME_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        cached = get_keyframes(path)
    except OSError:
        cached = None
    if cached is not None:
        _KEYFRAME_INDEX_CACHE[cache_key] = cached
        return cached
    index = []
    packet_count = 0
    if FFPROBE_PATH and fps > 0:
        try:
            record_keyframe_scan()
            proc = run_hidden(
                [FFPROBE_PATH, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "packet=flags,pts_time",
                 "-of", "csv=p=0", str(path)],
                stdout=-1, stderr=-1, timeout=120)
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
                packet_count += 1
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
    _KEYFRAME_INDEX_CACHE[cache_key] = index
    try:
        put_keyframes(path, index, packet_count=packet_count or None)
        if packet_count:
            metadata = get_metadata(path)
            if metadata is not None:
                corrected = _apply_cached_packet_count(path, metadata)
                if corrected != metadata:
                    put_metadata(path, corrected)
    except OSError:
        pass
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
        self._keyframes = []
        self._all_frames_keyframes = False
        self._index_thread = None
        self._conversion_samples_ms = collections.deque(maxlen=2048)
        self._decode_read_samples_ms = collections.deque(maxlen=2048)
        self._resize_samples_ms = collections.deque(maxlen=2048)
        self._color_samples_ms = collections.deque(maxlen=2048)
        self._qimage_samples_ms = collections.deque(maxlen=2048)
        self._seek_samples_ms = collections.deque(maxlen=256)
        self._grab_samples_ms = collections.deque(maxlen=256)

    def _to_qimage(self, frame, target_width):
        conversion_started = perf_counter()
        h, w = frame.shape[:2]
        resize_started = perf_counter()
        if w > target_width:
            nw = target_width
            nh = int(h * nw / w)
            frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        self._resize_samples_ms.append((perf_counter() - resize_started) * 1000.0)
        # Downscale before colour conversion: the output is identical at the
        # target resolution while substantially reducing converted pixels.
        color_started = perf_counter()
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._color_samples_ms.append((perf_counter() - color_started) * 1000.0)
        h, w, ch = frame.shape
        image_started = perf_counter()
        image = QImage(frame.data, w, h, ch * w, QImage.Format_RGB888).copy()
        self._qimage_samples_ms.append((perf_counter() - image_started) * 1000.0)
        self._conversion_samples_ms.append(
            (perf_counter() - conversion_started) * 1000.0)
        return image

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
        cap = _safe_video_capture(
            self._video_path, decoder_threads=DECODE_THREADS_PER_VIEW)
        if cap is None:
            print(f"[Decoder] Cannot open: {self._video_path.name}")
            return

        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        fourcc_value = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
        fourcc = "".join(chr((fourcc_value >> (8 * idx)) & 0xFF)
                         for idx in range(4)).strip("\x00 ").lower()
        self._all_frames_keyframes = fourcc in {"mjpg", "jpeg", "mjpa", "mjpb"}
        self._current_pos = 0
        # A persistent index is cheap to load.  A cold full packet scan is
        # deliberately deferred until after the first frame is delivered.
        # Before it is ready, random seeks decode safely from frame zero.
        try:
            self._keyframes = get_keyframes(self._video_path) or []
        except OSError:
            self._keyframes = []

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
        if self._all_frames_keyframes:
            return target
        if not self._keyframes:
            return None
        idx = bisect.bisect_right(self._keyframes, target) - 1
        if idx < 0:
            return None
        return self._keyframes[idx]

    def _ensure_keyframe_index_started(self):
        if self._all_frames_keyframes or self._keyframes or self._index_thread is not None:
            return
        cache_key = str(self._video_path.resolve())
        with _KEYFRAME_SCAN_LOCKS_GUARD:
            scan_lock = _KEYFRAME_SCAN_LOCKS.setdefault(cache_key, threading.Lock())

        def build():
            with scan_lock:
                index = probe_keyframe_index(self._video_path, self.fps)
            with self._condition:
                self._keyframes = index
                try:
                    packet_count = get_packet_count(self._video_path)
                except OSError:
                    packet_count = None
                if packet_count:
                    self.total_frames = min(self.total_frames, packet_count)

        self._index_thread = threading.Thread(
            target=build, name=f"mvsp-index-{self._video_path.name}", daemon=True)
        self._index_thread.start()

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
                # Never seek into a possibly inter-coded GOP before the index
                # is ready.  Decoding from zero is slower but reference-safe.
                anchor = 0
            seek_started = perf_counter()
            cap.set(cv2.CAP_PROP_POS_FRAMES, anchor)
            self._seek_samples_ms.append((perf_counter() - seek_started) * 1000.0)
            current_pos = anchor
            with self._condition:
                self._current_pos = anchor
                self._random_seeks += 1
            grab_stop = max(anchor, target - SEEK_KEYFRAME_DECODE_MARGIN)
            grab_started = perf_counter()
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
            self._grab_samples_ms.append((perf_counter() - grab_started) * 1000.0)

        while current_pos <= target:
            read_started = perf_counter()
            ret, frame = cap.read()
            self._decode_read_samples_ms.append(
                (perf_counter() - read_started) * 1000.0)
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
                self._ensure_keyframe_index_started()
                return

    def _decode_playback_frame(self, cap):
        with self._condition:
            frame_number = self._current_pos
        read_started = perf_counter()
        ret, frame = cap.read()
        self._decode_read_samples_ms.append(
            (perf_counter() - read_started) * 1000.0)
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
        self._ensure_keyframe_index_started()

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
            def distribution(values):
                samples = sorted(values)
                if not samples:
                    return {"median": 0.0, "p95": 0.0, "max": 0.0, "samples": 0}
                at = lambda fraction: samples[min(
                    len(samples) - 1, int((len(samples) - 1) * fraction))]
                return {
                    "median": round(at(0.5), 3),
                    "p95": round(at(0.95), 3),
                    "max": round(samples[-1], 3),
                    "samples": len(samples),
                }
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
                "keyframe_index_ready": bool(self._keyframes),
                "decode_read_ms": distribution(self._decode_read_samples_ms),
                "resize_ms": distribution(self._resize_samples_ms),
                "bgr_to_rgb_ms": distribution(self._color_samples_ms),
                "numpy_to_qimage_copy_ms": distribution(self._qimage_samples_ms),
                "convert_qimage_total_ms": distribution(self._conversion_samples_ms),
                "random_cap_seek_ms": distribution(self._seek_samples_ms),
                "keyframe_fast_forward_grab_ms": distribution(self._grab_samples_ms),
            }

    def stop(self):
        with self._condition:
            self._running = False
            self._condition.notify()
        if not self.wait(3000):
            print(f"[Decoder] Timed out stopping: {self._video_path.name}")
