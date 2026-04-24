"""multiview_sync_player.session_io — Session file I/O (pure functions, no Qt).

Handles serialization / deserialization of .mvsp.json session files.
All field names are kept backward-compatible with the existing format.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants — must match the values already used in .mvsp.json files
# ---------------------------------------------------------------------------

SESSION_FORMAT = "mvsp.session"
SESSION_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SessionFormatError(ValueError):
    """Raised when a session file has an unexpected format or version."""


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class SessionData:
    """In-memory representation of a session file.

    Field naming follows the existing .mvsp.json structure exactly.
    """

    cells: list[dict] = field(default_factory=list)
    # Each cell dict: {view_name, video_path, offset, total_frames, fps,
    #                   has_audio}

    layout: dict = field(default_factory=dict)
    # {rows, cols, view_names, view_colors}

    global_state: dict = field(default_factory=dict)
    # {version, created, offsets, markers, metadata}

    library_ref: Optional[dict] = None
    # {'root': abs_path, 'experiment': '...', 'date': 'YYYY-MM-DD',
    #  'subject': '...'}  — None when absent (backward-compatible).

    extra: dict = field(default_factory=dict)
    # Any additional top-level keys not covered above.


# ---------------------------------------------------------------------------
# Save / Load
# ---------------------------------------------------------------------------

def save_session(path: Path, data: SessionData) -> None:
    """Write *data* to *path* as a .mvsp.json file.

    The JSON structure is backward-compatible with files written by
    ``SyncController.save()`` + ``_write_extras_to_session()``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Reconstruct the flat JSON dict from SessionData
    obj: dict = {}

    # global_state fields → top level
    obj["version"] = data.global_state.get("version", SESSION_VERSION)
    if "created" in data.global_state:
        obj["created"] = data.global_state["created"]

    # offsets: {view_name: int}
    obj["offsets"] = data.global_state.get("offsets", {})

    # markers
    obj["markers"] = data.global_state.get("markers", [])

    # videos: {view_name: {path, total_frames, fps, has_audio}}
    videos: dict = {}
    for cell in data.cells:
        vn = cell["view_name"]
        videos[vn] = {
            "path": cell["video_path"],
            "total_frames": cell.get("total_frames", 0),
            "fps": cell.get("fps", 0.0),
            "has_audio": cell.get("has_audio", False),
        }
    obj["videos"] = videos

    # metadata
    if "metadata" in data.global_state:
        obj["metadata"] = data.global_state["metadata"]

    # layout
    if data.layout:
        obj["layout"] = data.layout

    # extra keys
    obj.update(data.extra)

    # library_ref (omit when None for backward compatibility)
    if data.library_ref is not None:
        obj["library_ref"] = data.library_ref

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_session(path: Path) -> SessionData:
    """Read a .mvsp.json file and return a :class:`SessionData`.

    Raises:
        SessionFormatError: if the file has no ``version`` key or the
            ``format`` key (if present) does not match :data:`SESSION_FORMAT`.
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)

    # ---- Schema validation ----
    if "version" not in obj:
        raise SessionFormatError("Missing required field 'version'")
    fmt = obj.get("format")
    if fmt is not None and fmt != SESSION_FORMAT:
        raise SessionFormatError(
            f"Format mismatch: expected {SESSION_FORMAT!r}, got {fmt!r}")

    # ---- Extract known keys ----
    videos = obj.get("videos", {})
    offsets = obj.get("offsets", {})
    markers = obj.get("markers", [])

    cells = []
    for vn, vinfo in videos.items():
        cells.append({
            "view_name": vn,
            "video_path": vinfo.get("path", ""),
            "total_frames": vinfo.get("total_frames", 0),
            "fps": vinfo.get("fps", 0.0),
            "has_audio": vinfo.get("has_audio", False),
            "offset": offsets.get(vn, 0),
        })

    layout = obj.get("layout", {})

    global_state = {
        "version": obj["version"],
    }
    if "created" in obj:
        global_state["created"] = obj["created"]
    global_state["offsets"] = offsets
    global_state["markers"] = markers
    if "metadata" in obj:
        global_state["metadata"] = obj["metadata"]

    # Collect any unknown top-level keys as extra
    known = {"version", "created", "offsets", "markers",
             "videos", "metadata", "layout", "library_ref"}
    extra = {k: v for k, v in obj.items() if k not in known}

    # library_ref (backward-compatible: None if absent)
    library_ref = obj.get("library_ref")

    return SessionData(
        cells=cells,
        layout=layout,
        global_state=global_state,
        library_ref=library_ref,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Library-ref detection
# ---------------------------------------------------------------------------

def detect_library_ref(
    video_paths: list[str],
    known_libraries: list[Path],
) -> Optional[dict]:
    """Check whether all *video_paths* share the same library root and the
    same experiment/date/subject triple under that root.

    Returns a dict ``{root, experiment, date, subject}`` on match, or
    ``None`` if the paths are scattered across libraries / subjects or do
    not fall under any known library.
    """
    if not video_paths or not known_libraries:
        return None

    # Normalise library roots to absolute resolved paths
    lib_roots = [Path(p).resolve() for p in known_libraries]

    matched_root: Optional[Path] = None
    matched_parts: Optional[tuple] = None  # (experiment, date, subject)

    for vp in video_paths:
        p = Path(vp).resolve()
        found = False
        for root in lib_roots:
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            parts = rel.parts
            # Expect at least experiment/date/subject/file
            if len(parts) < 4:
                continue
            exp, date, subj = parts[0], parts[1], parts[2]
            if matched_root is None:
                matched_root = root
                matched_parts = (exp, date, subj)
            elif matched_root != root or matched_parts != (exp, date, subj):
                return None  # cross-library or cross-subject
            found = True
            break
        if not found:
            return None  # outside any known library

    if matched_root is None or matched_parts is None:
        return None

    return {
        "root": str(matched_root),
        "experiment": matched_parts[0],
        "date": matched_parts[1],
        "subject": matched_parts[2],
    }
