"""Session manifests and portable path resolution.

The on-disk shape remains compatible with the original MVSP sessions. New
sessions additionally carry enough information to reopen themselves after a
workspace move: relative paths, an absolute fallback, lightweight video
identity metadata, and review state.

This module deliberately has no Qt dependency so it can be tested independently
from the player UI.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


SESSION_FORMAT = "mvsp.session"
SESSION_VERSION = "0.2.0"
LEGACY_SESSION_VERSION = "0.1.0"
QUICK_FINGERPRINT_CHUNK = 1024 * 1024


class SessionFormatError(ValueError):
    """Raised when a JSON file is not a supported session manifest."""


class SessionResolutionError(ValueError):
    """Raised when a legacy session cannot be mapped unambiguously."""


@dataclass
class SessionData:
    """In-memory representation of a session file.

    ``cells`` intentionally retains the old compact shape. Rich per-video
    fields are kept separately in ``video_manifests`` so callers written for
    the v0.1 API continue to compare/consume cells unchanged.
    """

    cells: list[dict] = field(default_factory=list)
    layout: dict = field(default_factory=dict)
    global_state: dict = field(default_factory=dict)
    library_ref: Optional[dict] = None
    extra: dict = field(default_factory=dict)
    video_manifests: dict = field(default_factory=dict)


@dataclass
class VideoResolution:
    """Result of resolving one manifest entry."""

    view_name: str
    path: Optional[Path]
    method: str
    relative_path: str = ""
    absolute_path: str = ""
    file_name: str = ""
    identity_ok: Optional[bool] = None
    identity_message: str = ""

    @property
    def ok(self) -> bool:
        return self.path is not None and self.identity_ok is not False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def quick_fingerprint(path: Path) -> str:
    """Hash size + first/last 1 MiB without reading the whole video."""

    path = Path(path)
    size = path.stat().st_size
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(QUICK_FINGERPRINT_CHUNK))
        if size > QUICK_FINGERPRINT_CHUNK:
            handle.seek(max(0, size - QUICK_FINGERPRINT_CHUNK))
            digest.update(handle.read(QUICK_FINGERPRINT_CHUNK))
    return digest.hexdigest()


def _normalise_relative_path(value: str) -> str:
    """Store paths in portable JSON form while accepting Windows separators."""

    return str(value or "").replace("\\", "/")


def _relative_path(video_path: Path, session_path: Path) -> str:
    try:
        return _normalise_relative_path(
            video_path.resolve().relative_to(session_path.resolve().parent))
    except ValueError:
        try:
            return _normalise_relative_path(
                os.path.relpath(str(video_path), str(session_path.parent)))
        except ValueError:
            return ""


def build_video_manifest(
    video_path: str | Path,
    session_path: str | Path,
    info: Optional[dict] = None,
) -> dict:
    """Build the canonical manifest entry for one currently loaded video."""

    raw_video_path = str(video_path)
    video = Path(video_path)
    session = Path(session_path)
    info = dict(info or {})
    manifest = {
        "path": raw_video_path,
        "relative_path": _relative_path(video, session),
        "file_name": video.name,
        "total_frames": int(info.get("total_frames", 0) or 0),
        "fps": float(info.get("fps", 0.0) or 0.0),
        "has_audio": bool(info.get("has_audio", False)),
    }
    for key in ("width", "height", "duration_sec", "codec"):
        if key in info and info[key] not in (None, ""):
            manifest[key] = info[key]

    if video.exists() and video.is_file():
        stat = video.stat()
        manifest["file_size"] = stat.st_size
        try:
            manifest["quick_fingerprint"] = {
                "method": "sha256_first_last_1MiB_plus_size",
                "value": quick_fingerprint(video),
            }
        except OSError:
            # A transient read failure must not make a session unsaveable.
            pass
    return manifest


def _atomic_write_json(path: Path, obj: dict) -> None:
    """Write beside the destination and replace it atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(obj, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            backup = Path(str(path) + ".bak")
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def save_session(path: Path, data: SessionData) -> None:
    """Write a portable, backward-compatible session atomically."""

    path = Path(path)
    obj: dict = {
        "format": SESSION_FORMAT,
        "version": data.global_state.get("version", SESSION_VERSION),
        "created": data.global_state.get("created", _now()),
        "offsets": data.global_state.get("offsets", {}),
        "markers": data.global_state.get("markers", []),
        "videos": {},
    }
    if "updated" in data.global_state:
        obj["updated"] = data.global_state["updated"]
    if "synced" in data.global_state:
        obj["synced"] = data.global_state["synced"]

    base_frame = data.global_state.get("base_frame")
    if base_frame is not None:
        obj["base_frame"] = int(base_frame)
    review_state = data.global_state.get("review_state")
    if review_state:
        obj["review_state"] = review_state

    for cell in data.cells:
        vn = cell["view_name"]
        video_path = cell.get("video_path", "")
        manifest = dict(data.video_manifests.get(vn, {}))
        if video_path:
            manifest.update(build_video_manifest(video_path, path, cell))
        elif manifest.get("path"):
            manifest["relative_path"] = _relative_path(
                Path(manifest["path"]), path)
        manifest["path"] = str(manifest.get("path", video_path))
        manifest.setdefault("file_name", Path(manifest["path"]).name)
        manifest.setdefault("total_frames", int(cell.get("total_frames", 0) or 0))
        manifest.setdefault("fps", float(cell.get("fps", 0.0) or 0.0))
        manifest.setdefault("has_audio", bool(cell.get("has_audio", False)))
        obj["videos"][vn] = manifest

    if "metadata" in data.global_state:
        obj["metadata"] = data.global_state["metadata"]
    if data.layout:
        obj["layout"] = data.layout
    obj.update(data.extra)
    if data.library_ref is not None:
        obj["library_ref"] = data.library_ref

    _atomic_write_json(path, obj)


def _is_session_object(obj: dict) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("format") == SESSION_FORMAT:
        return True
    session_keys = {
        "version", "offsets", "videos", "layout", "markers",
        "review_state", "base_frame", "synced", "library_ref",
    }
    if not session_keys.intersection(obj):
        return False
    # A layout-only JSON is commonly a project/template or arbitrary UI
    # metadata. The one supported exception is the legacy v0.1 alignment
    # shape, which may contain an empty offsets object but has view slots.
    layout = obj.get("layout") or {}
    legacy_layout = (
        str(obj.get("version", "")) == LEGACY_SESSION_VERSION
        and isinstance(layout, dict)
        and bool(layout.get("view_names") or
                 (layout.get("rows") and layout.get("cols"))))
    return bool(obj.get("videos") or obj.get("offsets") or legacy_layout)


def load_session(path: Path) -> SessionData:
    """Load current MVSP, legacy v0.1, or a recognized plain JSON session."""

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            # Two real v0.1 TestA files end exactly after the opening
            # ``view_colors`` array. They are recoverable in memory because
            # LayoutConfig supplies the palette defaults. Never write this
            # repair back to the source file automatically.
            if text.rstrip().endswith('"view_colors": ['):
                obj = json.loads(text.rstrip() + "]}\n}")
            else:
                raise exc
    except json.JSONDecodeError as exc:
        raise SessionFormatError(f"Invalid JSON: {exc}") from exc
    fmt = obj.get("format")
    if fmt is not None and fmt != SESSION_FORMAT:
        raise SessionFormatError(
            f"Format mismatch: expected {SESSION_FORMAT!r}, got {fmt!r}")
    if "version" not in obj and {"videos", "offsets"}.issubset(obj):
        raise SessionFormatError("Missing required field 'version'")
    if not _is_session_object(obj):
        raise SessionFormatError("JSON does not contain a recognized MVSP session")

    version = obj.get("version", LEGACY_SESSION_VERSION)
    videos = obj.get("videos", {})
    offsets = obj.get("offsets", {})
    markers = obj.get("markers", [])
    if not isinstance(videos, dict) or not isinstance(offsets, dict):
        raise SessionFormatError("Session fields 'videos' and 'offsets' must be objects")

    cells = []
    manifests = {}
    for vn, raw_info in videos.items():
        if not isinstance(raw_info, dict):
            raise SessionFormatError(f"Video entry for {vn!r} must be an object")
        info = dict(raw_info)
        manifests[vn] = info
        cells.append({
            "view_name": vn,
            "video_path": info.get("path", ""),
            "total_frames": info.get("total_frames", 0),
            "fps": info.get("fps", 0.0),
            "has_audio": info.get("has_audio", False),
            "offset": offsets.get(vn, 0),
        })

    global_state = {
        "version": version,
        "offsets": offsets,
        "markers": markers,
    }
    for key in ("created", "updated", "metadata", "base_frame", "synced",
                "review_state"):
        if key in obj:
            global_state[key] = obj[key]

    known = {
        "format", "version", "created", "updated", "offsets", "synced",
        "markers", "videos", "metadata", "layout", "library_ref",
        "base_frame", "review_state",
    }
    extra = {key: value for key, value in obj.items() if key not in known}
    return SessionData(
        cells=cells,
        layout=obj.get("layout", {}),
        global_state=global_state,
        library_ref=obj.get("library_ref"),
        extra=extra,
        video_manifests=manifests,
    )


def discover_legacy_video_manifests(path: Path, data: SessionData) -> dict:
    """Discover strict cage2/3/4 top/front files for legacy sessions.

    Old Windows sessions may contain six ``videos`` entries whose ``path``
    values are drive-letter paths but no ``relative_path``.  When those paths
    are unavailable on Linux, the same subject directory can still be mapped
    safely by the established cage/direction layout.  This function returns
    that derived mapping in memory only; it never writes back to the source
    session automatically.
    """

    existing = dict(data.video_manifests)
    legacy_windows_paths = bool(existing) and all(
        not item.get("relative_path")
        and len(str(item.get("path", ""))) >= 3
        and str(item.get("path", ""))[1] == ":"
        and str(item.get("path", ""))[2:3] in {"/", "\\"}
        for item in existing.values())
    if existing and not legacy_windows_paths:
        return existing
    path = Path(path)
    stem = path.name
    for suffix in (".mvsp.json", ".json", ".mvsp"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    subject_id = stem.rsplit("_", 1)[-1]
    if path.parent.name != subject_id:
        raise SessionResolutionError(
            f"Legacy session subject mismatch: {path.parent.name!r} vs {subject_id!r}")

    names = list(data.layout.get("view_names", []))
    if len(names) < 6:
        names = [f"View {idx}" for idx in range(1, 7)]
    expected = []
    for cage in (2, 3, 4):
        for direction in ("top", "front"):
            filename = f"{stem}_{direction}_{cage}"
            candidates = [
                item for item in (path.parent / f"cage{cage}" / direction).glob("*")
                if item.is_file()
                and item.stem.lower() == filename.lower()
                and item.suffix.lower() in {".mp4", ".avi", ".mkv", ".mov"}
            ]
            if len(candidates) != 1:
                expected.append((direction, cage, candidates))
    failures = [
        f"{direction}_{cage}: {len(candidates)} matches"
        for direction, cage, candidates in expected
    ]
    if failures:
        raise SessionResolutionError(
            "Legacy session video discovery is not unambiguous: "
            + ", ".join(failures))

    order = [(2, "top"), (3, "top"), (4, "top"),
             (2, "front"), (3, "front"), (4, "front")]
    manifests = {}
    for view, (cage, direction) in zip(names[:6], order):
        filename = f"{stem}_{direction}_{cage}"
        directory = path.parent / f"cage{cage}" / direction
        candidate = next(item for item in directory.glob("*")
                         if item.is_file()
                         and item.stem.lower() == filename.lower()
                         and item.suffix.lower() in {".mp4", ".avi", ".mkv", ".mov"})
        manifest = dict(existing.get(view, {}))
        manifest.update({
            "path": str(candidate),
            "relative_path": _relative_path(candidate, path),
            "file_name": candidate.name,
        })
        manifests[view] = manifest
    return manifests


def _identity_mismatch(manifest: dict, path: Path, actual: Optional[dict]) -> str:
    expected_size = manifest.get("file_size")
    if expected_size is not None and path.stat().st_size != int(expected_size):
        return f"file_size expected {expected_size}, got {path.stat().st_size}"
    expected_fp = manifest.get("quick_fingerprint") or {}
    if expected_fp.get("value"):
        try:
            actual_fp = quick_fingerprint(path)
        except OSError as exc:
            return f"fingerprint unavailable: {exc}"
        if actual_fp != expected_fp["value"]:
            return "quick_fingerprint mismatch"
    if actual:
        for key in ("total_frames", "width", "height"):
            expected = manifest.get(key)
            observed = actual.get(key)
            if expected not in (None, 0, "") and observed not in (None, 0, ""):
                if int(expected) != int(observed):
                    return f"{key} expected {expected}, got {observed}"
        expected_fps = manifest.get("fps")
        observed_fps = actual.get("fps")
        if expected_fps and observed_fps and abs(float(expected_fps) - float(observed_fps)) > 0.05:
            return f"fps expected {expected_fps}, got {observed_fps}"
    return ""


def resolve_video_manifest(
    view_name: str,
    manifest: dict,
    session_path: Path,
    search_root: Optional[Path] = None,
    actual_metadata: Optional[dict] = None,
) -> VideoResolution:
    """Resolve relative path first, absolute fallback second, then root search."""

    manifest = dict(manifest or {})
    session_path = Path(session_path)
    rel = _normalise_relative_path(manifest.get("relative_path", ""))
    absolute = str(manifest.get("path", ""))
    filename = manifest.get("file_name") or Path(absolute).name
    candidates = []
    if rel:
        candidates.append((session_path.parent / Path(rel), "relative"))
    if absolute:
        candidates.append((Path(absolute), "absolute"))
    if search_root and rel:
        candidates.append((Path(search_root) / Path(rel), "selected-root-relative"))

    seen = set()
    for candidate, method in candidates:
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            mismatch = _identity_mismatch(manifest, candidate, actual_metadata)
            return VideoResolution(
                view_name, candidate, method, rel, absolute, filename,
                identity_ok=not bool(mismatch), identity_message=mismatch)

    if search_root and filename:
        matches = [item for item in Path(search_root).rglob("*")
                   if item.is_file() and item.name.lower() == str(filename).lower()]
        if len(matches) == 1:
            mismatch = _identity_mismatch(manifest, matches[0], actual_metadata)
            return VideoResolution(
                view_name, matches[0], "selected-root-filename", rel, absolute,
                filename, identity_ok=not bool(mismatch), identity_message=mismatch)
        if len(matches) > 1:
            return VideoResolution(
                view_name, None, "ambiguous", rel, absolute, filename,
                identity_ok=False,
                identity_message=f"{len(matches)} filename matches under selected root")

    return VideoResolution(
        view_name, None, "missing", rel, absolute, filename,
        identity_ok=False, identity_message="file not found")


def resolve_session_videos(
    data: SessionData,
    session_path: Path,
    search_root: Optional[Path] = None,
    actual_metadata: Optional[dict] = None,
) -> dict[str, VideoResolution]:
    """Resolve every manifest entry without prompting or filesystem-wide search."""

    manifests = data.video_manifests
    if not manifests:
        manifests = {cell["view_name"]: {"path": cell.get("video_path", "")}
                     for cell in data.cells}
    return {
        vn: resolve_video_manifest(vn, manifest, Path(session_path), search_root,
                                   (actual_metadata or {}).get(vn))
        for vn, manifest in manifests.items()
    }


def detect_library_ref(
    video_paths: list[str],
    known_libraries: list[Path],
) -> Optional[dict]:
    """Return a library reference when all videos share one subject tree."""

    if not video_paths or not known_libraries:
        return None
    lib_roots = [Path(p).resolve() for p in known_libraries]
    matched_root: Optional[Path] = None
    matched_parts: Optional[tuple] = None
    for video_path in video_paths:
        p = Path(video_path).resolve()
        found = False
        for root in lib_roots:
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) < 4:
                continue
            parts = rel.parts
            current = (parts[0], parts[1], parts[2])
            if matched_root is None:
                matched_root, matched_parts = root, current
            elif matched_root != root or matched_parts != current:
                return None
            found = True
            break
        if not found:
            return None
    if matched_root is None or matched_parts is None:
        return None
    return {
        "root": str(matched_root),
        "experiment": matched_parts[0],
        "date": matched_parts[1],
        "subject": matched_parts[2],
    }
