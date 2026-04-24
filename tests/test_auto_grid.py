"""tests/test_auto_grid.py — auto_grid + fit_layout_to_views 单元测试。"""

import pytest

from multiview_sync_player.layout_manager import (
    LayoutConfig,
    auto_grid,
    fit_layout_to_views,
)


# ---------------------------------------------------------------------------
# auto_grid
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n,expected", [
    (1, (1, 1)), (2, (1, 2)), (3, (1, 3)), (4, (2, 2)),
    (5, (2, 3)), (6, (2, 3)), (7, (2, 4)), (8, (2, 4)), (9, (3, 3)),
    (10, (3, 4)), (12, (3, 4)),
    (13, (4, 4)), (16, (4, 4)),
    (17, (4, 5)), (20, (4, 5)),
    (21, (5, 5)), (25, (5, 5)),
    (26, (5, 6)), (30, (5, 6)),
])
def test_auto_grid_presets(n, expected):
    assert auto_grid(n) == expected


@pytest.mark.parametrize("n", [31, 36, 49, 64, 100])
def test_auto_grid_overflow(n):
    rows, cols = auto_grid(n)
    assert rows * cols >= n
    assert cols >= rows


def test_auto_grid_invalid():
    with pytest.raises(ValueError):
        auto_grid(0)
    with pytest.raises(ValueError):
        auto_grid(-1)


# ---------------------------------------------------------------------------
# fit_layout_to_views
# ---------------------------------------------------------------------------

def test_fit_layout_no_change_when_enough():
    cfg = LayoutConfig(rows=3, cols=3,
                       view_names=[f"V{i}" for i in range(9)],
                       view_colors=["#000000"] * 9)
    assert fit_layout_to_views(cfg, 5) is cfg


def test_fit_layout_expands_when_insufficient():
    cfg = LayoutConfig(rows=2, cols=2,
                       view_names=["V1", "V2", "V3", "V4"],
                       view_colors=["#000000"] * 4)
    new_cfg = fit_layout_to_views(cfg, 9)
    assert new_cfg.rows * new_cfg.cols >= 9
    assert len(new_cfg.view_names) == new_cfg.rows * new_cfg.cols
