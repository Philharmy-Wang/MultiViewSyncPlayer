"""Persistent metadata and keyframe-index cache.

Cache files live in the application cache directory, never beside source
videos.  Entries are invalidated by file identity, tool versions, and schema.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QStandardPaths

from .config import FFMPEG_PATH, FFPROBE_PATH
from .process_utils import run_hidden
from .session_io import quick_fingerprint


CACHE_SCHEMA_VERSION = 2
_LOCK = threading.RLock()
_METRICS = {
    "metadata_hits": 0,
    "metadata_misses": 0,
    "keyframe_hits": 0,
    "keyframe_misses": 0,
    "keyframe_scans": 0,
}


def cache_root() -> Path:
    override = os.environ.get("MVSP_CACHE_DIR")
    if override:
        root = Path(override)
    else:
        location = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
        root = Path(location) if location else Path.home() / ".cache" / "MultiViewSyncPlayer"
    root = root / "media-v1"
    root.mkdir(parents=True, exist_ok=True)
    return root


@lru_cache(maxsize=4)
def tool_version(executable: str) -> str:
    if not executable:
        return "unavailable"
    try:
        proc = run_hidden(
            [executable, "-version"], stdout=-1, stderr=-1, timeout=10,
            text=True, encoding="utf-8", errors="replace")
        first = (proc.stdout or proc.stderr or "").splitlines()
        return first[0].strip() if first else f"exit-{proc.returncode}"
    except Exception as exc:
        return f"unavailable:{type(exc).__name__}"


def file_identity(video_path: str | Path) -> dict[str, Any]:
    path = Path(video_path).resolve()
    stat = path.stat()
    return {
        "path": str(path),
        "file_size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "quick_fingerprint": quick_fingerprint(path),
        "ffprobe_version": tool_version(FFPROBE_PATH),
        "ffmpeg_version": tool_version(FFMPEG_PATH),
        "schema_version": CACHE_SCHEMA_VERSION,
    }


def _entry_path(video_path: str | Path) -> Path:
    resolved = os.path.normcase(str(Path(video_path).resolve())).encode("utf-8")
    return cache_root() / f"{hashlib.sha256(resolved).hexdigest()}.json"


def _read(video_path: str | Path) -> tuple[Optional[dict], dict]:
    identity = file_identity(video_path)
    path = _entry_path(video_path)
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None, identity
    if entry.get("identity") != identity:
        return None, identity
    return entry, identity


def _write(video_path: str | Path, identity: dict, **sections: Any) -> None:
    path = _entry_path(video_path)
    with _LOCK:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            existing = {}
        if existing.get("identity") != identity:
            existing = {"identity": identity}
        existing.update(sections)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)


def get_metadata(video_path: str | Path) -> Optional[dict]:
    with _LOCK:
        entry, _ = _read(video_path)
        value = entry.get("metadata") if entry else None
        _METRICS["metadata_hits" if value is not None else "metadata_misses"] += 1
        return dict(value) if value is not None else None


def put_metadata(video_path: str | Path, metadata: dict) -> None:
    identity = file_identity(video_path)
    _write(video_path, identity, metadata=dict(metadata))


def get_keyframes(video_path: str | Path) -> Optional[list[int]]:
    with _LOCK:
        entry, _ = _read(video_path)
        value = entry.get("keyframes") if entry else None
        _METRICS["keyframe_hits" if value is not None else "keyframe_misses"] += 1
        return list(value) if value is not None else None


def get_packet_count(video_path: str | Path) -> Optional[int]:
    with _LOCK:
        entry, _ = _read(video_path)
        value = entry.get("video_packet_count") if entry else None
        return int(value) if value is not None else None


def put_keyframes(video_path: str | Path, keyframes: list[int],
                  packet_count: Optional[int] = None) -> None:
    identity = file_identity(video_path)
    sections = {"keyframes": [int(value) for value in keyframes]}
    if packet_count is not None:
        sections["video_packet_count"] = int(packet_count)
    _write(video_path, identity, **sections)


def record_keyframe_scan() -> None:
    with _LOCK:
        _METRICS["keyframe_scans"] += 1


def cache_metrics() -> dict[str, int]:
    with _LOCK:
        return dict(_METRICS)


def reset_cache_metrics() -> None:
    with _LOCK:
        for key in _METRICS:
            _METRICS[key] = 0
