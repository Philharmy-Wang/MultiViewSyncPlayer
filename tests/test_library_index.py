import datetime
import json
from pathlib import Path

import pytest

from multiview_sync_player.library.executor import ImportExecutor
from multiview_sync_player.library.import_plan import (
    ImportPlan,
    autodetect_view_mappings,
)
from multiview_sync_player.library.index import (
    INDEX_FILENAME,
    LibraryIndex,
    load_index,
    rebuild_index,
    save_index,
    scan_library,
)


def _import(tmp_path, experiment, date, subject_id, filenames):
    srcs = []
    for n in filenames:
        p = tmp_path / "raw" / experiment / date.isoformat() / subject_id / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        srcs.append(p)
    plan = ImportPlan(
        library_root=tmp_path / "lib",
        experiment=experiment,
        date=date,
        subject_id=subject_id,
        view_mappings=autodetect_view_mappings(srcs),
    )
    ImportExecutor(plan).run()


def test_scan_empty_library(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    idx = scan_library(lib)
    assert idx.experiments == []
    assert idx.warnings == []
    assert idx.library_root == lib


def test_scan_single_subject(tmp_path):
    _import(
        tmp_path, "ThreeChamber", datetime.date(2026, 1, 26), "24332",
        ["前-1.mp4", "top.mp4"],
    )
    idx = scan_library(tmp_path / "lib")
    assert len(idx.experiments) == 1
    exp = idx.experiments[0]
    assert exp.name == "ThreeChamber"
    assert len(exp.dates) == 1
    d = exp.dates[0]
    assert d.date == datetime.date(2026, 1, 26)
    assert len(d.subjects) == 1
    sub = d.subjects[0]
    assert sub.subject_id == "24332"
    assert len(sub.views) == 2
    assert sub.views[0].name == "前-1"
    assert sub.views[0].direction == "front"


def test_scan_multi_experiments(tmp_path):
    _import(tmp_path, "ExpA", datetime.date(2026, 1, 26), "s1", ["a.mp4"])
    _import(tmp_path, "ExpA", datetime.date(2026, 1, 27), "s2", ["b.mp4"])
    _import(tmp_path, "ExpB", datetime.date(2026, 2, 1), "s3", ["c.mp4"])
    idx = scan_library(tmp_path / "lib")
    names = sorted(idx.experiment_names())
    assert names == ["ExpA", "ExpB"]
    expa = [e for e in idx.experiments if e.name == "ExpA"][0]
    assert len(expa.dates) == 2
    assert [d.date.isoformat() for d in expa.dates] == [
        "2026-01-26",
        "2026-01-27",
    ]


def test_scan_with_warnings(tmp_path):
    _import(tmp_path, "Exp", datetime.date(2026, 1, 26), "s1", ["a.mp4"])
    lib = tmp_path / "lib"
    # Non-date second-level directory
    (lib / "Exp" / "not-a-date" / "s2").mkdir(parents=True)
    (lib / "Exp" / "not-a-date" / "s2" / "x.mp4").write_bytes(b"x")
    # Subject dir without _meta.json but with video files
    (lib / "Exp" / "2026-02-01" / "orphan").mkdir(parents=True)
    (lib / "Exp" / "2026-02-01" / "orphan" / "y.mp4").write_bytes(b"x")
    idx = scan_library(lib)
    assert len(idx.warnings) >= 2
    reasons = {w.reason for w in idx.warnings}
    assert "missing_meta" in reasons


def test_save_load_roundtrip(tmp_path):
    _import(tmp_path, "Exp", datetime.date(2026, 1, 26), "s1", ["前-1.mp4"])
    lib = tmp_path / "lib"
    idx = scan_library(lib)
    path = save_index(idx)
    assert path == lib / INDEX_FILENAME
    assert path.exists()

    loaded = load_index(lib)
    assert loaded is not None
    assert loaded.experiment_names() == idx.experiment_names()
    assert loaded.experiments[0].dates[0].subjects[0].views[0].name == "前-1"


def test_load_missing_returns_none(tmp_path):
    (tmp_path / "lib").mkdir()
    assert load_index(tmp_path / "lib") is None


def test_load_schema_mismatch(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / INDEX_FILENAME).write_text(
        json.dumps({"schema_version": 999, "experiments": []}),
        encoding="utf-8",
    )
    assert load_index(lib) is None


def test_find_subject(tmp_path):
    _import(tmp_path, "Exp", datetime.date(2026, 1, 26), "s1", ["a.mp4"])
    _import(tmp_path, "Exp", datetime.date(2026, 1, 26), "s2", ["b.mp4"])
    idx = scan_library(tmp_path / "lib")
    s = idx.find_subject("Exp", datetime.date(2026, 1, 26), "s2")
    assert s is not None and s.subject_id == "s2"
    assert idx.find_subject("Exp", datetime.date(2026, 1, 26), "nope") is None


def test_rebuild_writes_file(tmp_path):
    _import(tmp_path, "Exp", datetime.date(2026, 1, 26), "s1", ["a.mp4"])
    idx = rebuild_index(tmp_path / "lib")
    assert (tmp_path / "lib" / INDEX_FILENAME).exists()
    assert len(idx.experiments) == 1
