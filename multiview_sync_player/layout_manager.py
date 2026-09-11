"""
multiview_sync_player.layout_manager — Layout configuration

Defines layout presets and LayoutConfig for configurable grid dimensions.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
    view_colors: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.view_names:
            self.view_names = _default_view_names(self.slots_count())
        # Ensure view_names length matches grid size
        count = self.slots_count()
        while len(self.view_names) < count:
            idx = len(self.view_names) + 1
            self.view_names.append(f"View {idx}")
        self.view_names = self.view_names[:count]
        # Ensure view_colors length matches
        while len(self.view_colors) < count:
            self.view_colors.append(get_view_color(len(self.view_colors)))
        self.view_colors = self.view_colors[:count]

    def slots_count(self) -> int:
        return self.rows * self.cols

    def positions(self) -> List[Tuple[int, int]]:
        """Return (row, col) for each slot in left-to-right, top-to-bottom order."""
        return [(r, c) for r in range(self.rows) for c in range(self.cols)]

    def view_positions(self) -> dict:
        """Return {view_name: (row, col)} mapping."""
        return {vn: pos for vn, pos in zip(self.view_names, self.positions())}

    def to_dict(self) -> dict:
        colors = [color if isinstance(color, str) else color.name()
                  for color in self.view_colors]
        return {
            "rows": self.rows,
            "cols": self.cols,
            "view_names": list(self.view_names),
            "view_colors": colors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutConfig":
        return cls(
            rows=data.get("rows", 2),
            cols=data.get("cols", 3),
            view_names=data.get("view_names", []),
            view_colors=data.get("view_colors", []),
        )


# ---------------------------------------------------------------------------
# auto_grid / fit_layout_to_views
# ---------------------------------------------------------------------------

_AUTO_GRID_PRESETS = {
    1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 2),
    5: (2, 3), 6: (2, 3), 7: (2, 4), 8: (2, 4), 9: (3, 3),
    10: (3, 4), 11: (3, 4), 12: (3, 4),
    13: (4, 4), 14: (4, 4), 15: (4, 4), 16: (4, 4),
    17: (4, 5), 18: (4, 5), 19: (4, 5), 20: (4, 5),
    21: (5, 5), 22: (5, 5), 23: (5, 5), 24: (5, 5), 25: (5, 5),
    26: (5, 6), 27: (5, 6), 28: (5, 6), 29: (5, 6), 30: (5, 6),
}


def auto_grid(n: int) -> Tuple[int, int]:
    """给定视频数 n，返回 (rows, cols)，优先更宽 (cols >= rows)。

    映射规则:
      n ∈ {1..30}    走预设表
      n > 30         rows = ceil(sqrt(n)), cols = ceil(n / rows)
      n <= 0         raise ValueError
    """
    if n <= 0:
        raise ValueError("auto_grid: n must be >= 1")
    if n in _AUTO_GRID_PRESETS:
        return _AUTO_GRID_PRESETS[n]
    rows = math.ceil(math.sqrt(n))
    cols = math.ceil(n / rows)
    return (rows, cols)


def fit_layout_to_views(current: LayoutConfig, required: int) -> LayoutConfig:
    """若 current.slots_count() < required，返回扩展后的新 LayoutConfig；否则原样返回。

    扩展时新增 cell 的 view_name 走占位 'View {i+1}'，
    view_color 走 vocabulary.assign_color(None, i) 兜底。
    """
    if current.slots_count() >= required:
        return current
    rows, cols = auto_grid(required)
    new_slots = rows * cols
    extra_names = [f"View {i + 1}" for i in range(current.slots_count(), new_slots)]
    extra_colors = [get_view_color(i) for i in range(current.slots_count(), new_slots)]
    return LayoutConfig(
        rows=rows,
        cols=cols,
        view_names=list(current.view_names) + extra_names,
        view_colors=list(current.view_colors) + extra_colors,
    )
