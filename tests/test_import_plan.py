import datetime
from pathlib import Path

import pytest

from multiview_sync_player.library.import_plan import (
    ImportPlan,
    ViewMapping,
    autodetect_view_mappings,
    render_plan_preview,
)


def test_autodetect_chinese_names(tmp_path):
    sources = [
        tmp_path / "前-1.mp4",
        tmp_path / "前-2.mp4",
        tmp_path / "top.mp4",
        tmp_path / "cam03.mp4",
        tmp_path / "随便.mov",
    ]
    ms = autodetect_view_mappings(sources)
    assert len(ms) == 5
    assert ms[0].direction == "front" and ms[0].index == 1
    assert ms[1].direction == "front" and ms[1].index == 2
    assert ms[2].direction == "top" and ms[2].index is None
    assert ms[3].direction is None and ms[3].index == 3
    assert ms[4].direction is None and ms[4].index is None
    # 颜色不重复
    colors = [m.color for m in ms]
    assert len(set(colors)) == 5


def test_target_mapping(tmp_path):
    srcs = []
    for name in ["前-1.mp4", "前-2.mp4", "top.mp4"]:
        p = tmp_path / name
        p.write_bytes(b"x")
        srcs.append(p)
    ms = autodetect_view_mappings(srcs)
    plan = ImportPlan(
        library_root=tmp_path / "lib",
        experiment="ThreeChamber",
        date=datetime.date(2026, 1, 26),
        subject_id="24332",
        view_mappings=ms,
    )
    assert plan.validate() == []
    tm = plan.target_mapping()
    assert len(tm) == 3
    src, tgt = tm[0]
    assert src == srcs[0]
    assert tgt.parent.name == "24332"
    assert tgt.parent.parent.name == "2026-01-26"
    assert tgt.parent.parent.parent.name == "ThreeChamber"
    assert tgt.name == "前-1.mp4"


def test_validate_errors(tmp_path):
    plan = ImportPlan(
        library_root=Path("relative/path"),  # 非绝对
        experiment="",  # 空
        date=datetime.date(2026, 1, 26),
        subject_id="24332",
        view_mappings=[],  # 空
    )
    errs = plan.validate()
    assert any("library_root" in e for e in errs)
    assert any("experiment" in e for e in errs)
    assert any("view_mappings" in e or "include" in e for e in errs)


def test_duplicate_filenames(tmp_path):
    s1 = tmp_path / "a.mp4"
    s1.write_bytes(b"x")
    s2 = tmp_path / "b.mp4"
    s2.write_bytes(b"x")
    ms = [
        ViewMapping(source=s1, view_name="前/1"),  # sanitize -> '前_1'
        ViewMapping(source=s2, view_name="前_1"),  # 同名
    ]
    plan = ImportPlan(
        library_root=tmp_path / "lib",
        experiment="Exp",
        date=datetime.date(2026, 1, 26),
        subject_id="s",
        view_mappings=ms,
    )
    errs = plan.validate()
    assert any("duplicate" in e.lower() or "重复" in e for e in errs)


def test_render_preview(tmp_path):
    srcs = [tmp_path / "前-1.mp4", tmp_path / "top.mp4"]
    for s in srcs:
        s.write_bytes(b"x")
    ms = autodetect_view_mappings(srcs)
    plan = ImportPlan(
        library_root=Path("K:/library"),
        experiment="ThreeChamber",
        date=datetime.date(2026, 1, 26),
        subject_id="24332",
        view_mappings=ms,
    )
    text = render_plan_preview(plan)
    assert "ThreeChamber" in text
    assert "2026-01-26" in text
    assert "24332" in text
    assert "前-1.mp4" in text
    assert "top.mp4" in text
