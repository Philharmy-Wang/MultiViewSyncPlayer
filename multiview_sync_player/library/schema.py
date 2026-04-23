"""multiview_sync_player.library.schema — Four-level media library data model.

Defines Experiment → DateEntry → SubjectEntry → ViewEntry with full
serialization support (to_dict / from_dict).  Paths are stored as POSIX
strings in JSON; dates as ISO format.

Generated: 2026-04-23 20:00:00
"""

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ViewEntry:
    """A single camera view / video file."""

    name: str  # display name, e.g. "前-1" / "top" / "cam03"
    direction: Optional[str]  # 'front'/'back'/'left'/'right'/'top'/'bottom'/None
    index: Optional[int]  # camera number within direction; None = sole camera
    color: Optional[str]  # hex colour, e.g. '#42a5f5'
    video_path: Path  # relative to library root
    duration_sec: Optional[float] = None
    fps: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "direction": self.direction,
            "index": self.index,
            "color": self.color,
            "video_path": self.video_path.as_posix(),
            "duration_sec": self.duration_sec,
            "fps": self.fps,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ViewEntry":
        d = dict(d)  # shallow copy
        d["video_path"] = Path(d["video_path"])
        return cls(**d)


@dataclass
class SubjectEntry:
    """An individual subject observed on a given date."""

    subject_id: str
    views: List[ViewEntry] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "subject_id": self.subject_id,
            "views": [v.to_dict() for v in self.views],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SubjectEntry":
        return cls(
            subject_id=d["subject_id"],
            views=[ViewEntry.from_dict(v) for v in d.get("views", [])],
            notes=d.get("notes", ""),
        )


@dataclass
class DateEntry:
    """All subjects recorded on a specific date."""

    date: datetime.date
    subjects: List[SubjectEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "subjects": [s.to_dict() for s in self.subjects],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DateEntry":
        return cls(
            date=datetime.date.fromisoformat(d["date"]),
            subjects=[SubjectEntry.from_dict(s) for s in d.get("subjects", [])],
        )


@dataclass
class ExperimentEntry:
    """Top-level experiment grouping."""

    name: str
    dates: List[DateEntry] = field(default_factory=list)
    extra: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "dates": [d.to_dict() for d in self.dates],
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentEntry":
        return cls(
            name=d["name"],
            dates=[DateEntry.from_dict(dd) for dd in d.get("dates", [])],
            extra=d.get("extra", {}),
        )
