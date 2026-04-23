"""multiview_sync_player.library.index — Library scanner and persistent index.

Scans a media library root for ``_meta.json`` files, aggregates them into
an Experiment → Date → Subject → View tree, and persists the result as
``library.mvsp-lib.json``.

Input:  library_root path (containing experiments/dates/subjects).
Output: LibraryIndex object + library.mvsp-lib.json on disk.

Generated: 2026-04-23 23:30:00
"""

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .schema import DateEntry, ExperimentEntry, SubjectEntry, ViewEntry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_FILENAME = "library.mvsp-lib.json"
INDEX_SCHEMA_VERSION = 1

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------------------
# ScanWarning
# ---------------------------------------------------------------------------


@dataclass
class ScanWarning:
    path: Path
    reason: str  # 'missing_meta' / 'invalid_json' / 'schema_mismatch' / 'io_error' / 'not_a_date'
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "reason": self.reason,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScanWarning":
        return cls(path=Path(d["path"]), reason=d["reason"], detail=d.get("detail", ""))


# ---------------------------------------------------------------------------
# LibraryIndex
# ---------------------------------------------------------------------------


@dataclass
class LibraryIndex:
    """全库索引：实验 → 日期 → 个体 → 视角。"""

    library_root: Path
    experiments: List[ExperimentEntry] = field(default_factory=list)
    generated_at: str = ""
    schema_version: int = INDEX_SCHEMA_VERSION
    warnings: List[ScanWarning] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "library_root": str(self.library_root),
            "experiments": [e.to_dict() for e in self.experiments],
            "warnings": [w.to_dict() for w in self.warnings],
        }

    @classmethod
    def from_dict(cls, d: dict, library_root: Path) -> "LibraryIndex":
        return cls(
            library_root=library_root,
            experiments=[ExperimentEntry.from_dict(e) for e in d.get("experiments", [])],
            generated_at=d.get("generated_at", ""),
            schema_version=d.get("schema_version", INDEX_SCHEMA_VERSION),
            warnings=[ScanWarning.from_dict(w) for w in d.get("warnings", [])],
        )

    def experiment_names(self) -> List[str]:
        return [e.name for e in self.experiments]

    def find_subject(
        self, experiment: str, date: datetime.date, subject_id: str
    ) -> Optional[SubjectEntry]:
        """按 (experiment, date, subject_id) 查找 subject。"""
        for exp in self.experiments:
            if exp.name != experiment:
                continue
            for d in exp.dates:
                if d.date != date:
                    continue
                for s in d.subjects:
                    if s.subject_id == subject_id:
                        return s
        return None

    def all_subjects(self) -> List[SubjectEntry]:
        """扁平化所有 subject，按 (experiment, date, subject_id) 排序。"""
        result: List[SubjectEntry] = []
        for exp in self.experiments:
            for d in exp.dates:
                result.extend(d.subjects)
        return result


# ---------------------------------------------------------------------------
# scan_library
# ---------------------------------------------------------------------------

_VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm", ".flv", ".wmv"}


def scan_library(library_root: Path) -> LibraryIndex:
    """遍历 library_root/*/(YYYY-MM-DD)/*/_meta.json，构造 LibraryIndex。"""
    library_root = Path(library_root)
    warnings: List[ScanWarning] = []
    # experiment_name -> { date_str -> { subject_id -> SubjectEntry } }
    tree: Dict[str, Dict[str, Dict[str, SubjectEntry]]] = {}

    if not library_root.is_dir():
        return LibraryIndex(library_root=library_root, warnings=warnings)

    for exp_dir in sorted(library_root.iterdir()):
        # Skip hidden / special files and the index itself
        if exp_dir.name.startswith(".") or exp_dir.name.startswith("_"):
            continue
        if exp_dir.name == INDEX_FILENAME:
            continue
        if not exp_dir.is_dir():
            continue

        exp_name = exp_dir.name
        if exp_name not in tree:
            tree[exp_name] = {}

        for date_dir in sorted(exp_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            if not _DATE_RE.match(date_dir.name):
                warnings.append(
                    ScanWarning(date_dir, "not_a_date", f"directory '{date_dir.name}' does not match YYYY-MM-DD")
                )
                continue

            date_str = date_dir.name
            if date_str not in tree[exp_name]:
                tree[exp_name][date_str] = {}

            for subj_dir in sorted(date_dir.iterdir()):
                if not subj_dir.is_dir():
                    continue
                meta_path = subj_dir / "_meta.json"

                if not meta_path.exists():
                    # Check if there are video files
                    has_videos = any(
                        p.suffix.lower() in _VIDEO_EXTS for p in subj_dir.iterdir() if p.is_file()
                    )
                    if has_videos:
                        warnings.append(
                            ScanWarning(subj_dir, "missing_meta", "")
                        )
                    continue

                # Read _meta.json
                try:
                    raw = meta_path.read_text(encoding="utf-8")
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    warnings.append(
                        ScanWarning(meta_path, "invalid_json", str(exc))
                    )
                    continue
                except OSError as exc:
                    warnings.append(
                        ScanWarning(meta_path, "io_error", str(exc))
                    )
                    continue

                if data.get("schema_version") != 1:
                    warnings.append(
                        ScanWarning(meta_path, "schema_mismatch", f"got {data.get('schema_version')}")
                    )
                    continue

                # Build SubjectEntry from _meta.json
                views: List[ViewEntry] = []
                for vd in data.get("views", []):
                    views.append(
                        ViewEntry(
                            name=vd.get("name", ""),
                            direction=vd.get("direction"),
                            index=vd.get("index"),
                            color=vd.get("color"),
                            video_path=Path(vd.get("video", "")),
                            notes=vd.get("notes", ""),
                        )
                    )

                subject = SubjectEntry(
                    subject_id=data.get("subject_id", subj_dir.name),
                    views=views,
                    notes=data.get("notes", ""),
                )
                tree[exp_name][date_str][subj_dir.name] = subject

    # Aggregate into ExperimentEntry list
    experiments: List[ExperimentEntry] = []
    for exp_name in sorted(tree):
        dates: List[DateEntry] = []
        for date_str in sorted(tree[exp_name]):
            subjects = [
                tree[exp_name][date_str][sid]
                for sid in sorted(tree[exp_name][date_str])
            ]
            dates.append(
                DateEntry(
                    date=datetime.date.fromisoformat(date_str),
                    subjects=subjects,
                )
            )
        experiments.append(ExperimentEntry(name=exp_name, dates=dates))

    generated_at = datetime.datetime.now(
        datetime.timezone.utc
    ).astimezone().isoformat()

    return LibraryIndex(
        library_root=library_root,
        experiments=experiments,
        generated_at=generated_at,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# save_index / load_index / rebuild_index
# ---------------------------------------------------------------------------


def save_index(index: LibraryIndex, path: Optional[Path] = None) -> Path:
    """将 index 写入 JSON。默认 path = library_root / INDEX_FILENAME。"""
    if path is None:
        path = index.library_root / INDEX_FILENAME
    path.write_text(
        json.dumps(index.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_index(library_root: Path) -> Optional[LibraryIndex]:
    """读取 library_root / INDEX_FILENAME。失败返回 None。"""
    path = library_root / INDEX_FILENAME
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None

    if data.get("schema_version") != INDEX_SCHEMA_VERSION:
        return None

    return LibraryIndex.from_dict(data, library_root=library_root)


def rebuild_index(library_root: Path) -> LibraryIndex:
    """scan_library + save_index 的组合。"""
    idx = scan_library(library_root)
    save_index(idx)
    return idx
