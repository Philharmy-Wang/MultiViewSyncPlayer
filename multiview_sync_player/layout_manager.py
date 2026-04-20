"""
multiview_sync_player.layout_manager — Layout configuration

Defines layout presets and LayoutConfig for configurable grid dimensions.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

from .config import get_view_color


# (display_name, rows, cols) — rows=0, cols=0 means custom
LAYOUT_PRESETS: List[Tuple[str, int, int]] = [
    ("1x1 Single", 1, 1),
    ("1x2 Side-by-side", 1, 2),
    ("2x1 Stacked", 2, 1),
    ("2x2 Quad", 2, 2),
    ("2x3 Six-view", 2, 3),
    ("3x3 Nine-view", 3, 3),
    ("Custom...", 0, 0),
]


def _default_view_names(count: int) -> List[str]:
    """Generate default view names: View 1, View 2, ..."""
    return [f"View {i}" for i in range(1, count + 1)]


@dataclass
class LayoutConfig:
    """Grid layout configuration."""
    rows: int = 2
    cols: int = 3
    view_names: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.view_names:
            self.view_names = _default_view_names(self.slots_count())
        # Ensure view_names length matches grid size
        count = self.slots_count()
        while len(self.view_names) < count:
            idx = len(self.view_names) + 1
            self.view_names.append(f"View {idx}")
        self.view_names = self.view_names[:count]

    def slots_count(self) -> int:
        return self.rows * self.cols

    def positions(self) -> List[Tuple[int, int]]:
        """Return (row, col) for each slot in left-to-right, top-to-bottom order."""
        return [(r, c) for r in range(self.rows) for c in range(self.cols)]

    def view_positions(self) -> dict:
        """Return {view_name: (row, col)} mapping."""
        return {vn: pos for vn, pos in zip(self.view_names, self.positions())}

    def to_dict(self) -> dict:
        return {
            "rows": self.rows,
            "cols": self.cols,
            "view_names": list(self.view_names),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutConfig":
        return cls(
            rows=data.get("rows", 2),
            cols=data.get("cols", 3),
            view_names=data.get("view_names", []),
        )
