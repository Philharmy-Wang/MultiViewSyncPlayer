import datetime
import json
import os
from pathlib import Path

import pytest

from multiview_sync_player.library.executor import ImportExecutor, ImportResult
from multiview_sync_player.library.import_plan import (
    ImportPlan,
    autodetect_view_mappings,
)


def _make_plan(tmp_path, names, copy_mode="copy", conflict_policy="skip"):
    srcs = []
    for n in names:
        p = tmp_path / "raw" / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"hello " + n.encode("utf-8"))
        srcs.append(p)
    ms = autodetect_view_mappings(srcs)
    return ImportPlan(
        library_root=tmp_path / "lib",
        experiment="ThreeChamber",
        date=datetime.date(2026, 1, 26),
        subject_id="24332",
        notes="unit test",
        view_mappings=ms,
        copy_mode=copy_mode,
        conflict_policy=conflict_policy,
    )


def test_copy_mode_basic(tmp_path):
    plan = _make_plan(tmp_path, ["前-1.mp4", "top.mp4"])
    res = ImportExecutor(plan).run()
    assert len(res.successes) == 2
    assert not res.failed and not res.skipped
    for _, tgt in res.successes:
        assert tgt.exists() and tgt.stat().st_size > 0
    assert res.meta_path and res.meta_path.exists()
    meta = json.loads(res.meta_path.read_text(encoding="utf-8"))
    assert meta["experiment"] == "ThreeChamber"
    assert meta["subject_id"] == "24332"
    assert len(meta["views"]) == 2
    assert meta["views"][0]["name"] == "前-1"
    assert meta["views"][0]["direction"] == "front"


def test_dry_run_no_write(tmp_path):
    plan = _make_plan(tmp_path, ["a.mp4", "b.mp4"])
    res = ImportExecutor(plan).run(dry_run=True)
    assert res.dry_run is True
    assert len(res.successes) == 2
    for _, tgt in res.successes:
        assert not tgt.exists()
    assert res.meta_path is None
    assert not (plan.library_root).exists()


def test_conflict_skip(tmp_path):
    plan = _make_plan(tmp_path, ["前-1.mp4"], conflict_policy="skip")
    r1 = ImportExecutor(plan).run()
    assert len(r1.successes) == 1
    r2 = ImportExecutor(plan).run()
    assert len(r2.successes) == 0
    assert len(r2.skipped) == 1
    assert r2.skipped[0][2].startswith("conflict")


def test_conflict_rename(tmp_path):
    plan = _make_plan(tmp_path, ["前-1.mp4"], conflict_policy="rename")
    r1 = ImportExecutor(plan).run()
    r2 = ImportExecutor(plan).run()
    assert len(r2.successes) == 1
    _, tgt2 = r2.successes[0]
    assert tgt2.name != "前-1.mp4"
    assert "_1" in tgt2.stem or tgt2.stem.endswith("_1")
    assert tgt2.exists()


def test_conflict_overwrite(tmp_path):
    plan = _make_plan(tmp_path, ["前-1.mp4"], conflict_policy="overwrite")
    r1 = ImportExecutor(plan).run()
    src = plan.view_mappings[0].source
    src.write_bytes(b"NEW CONTENT")
    r2 = ImportExecutor(plan).run()
    assert len(r2.successes) == 1
    _, tgt = r2.successes[0]
    assert tgt.read_bytes() == b"NEW CONTENT"


def test_hardlink_mode(tmp_path):
    plan = _make_plan(tmp_path, ["a.mp4"], copy_mode="hardlink")
    res = ImportExecutor(plan).run()
    assert len(res.successes) == 1
    src, tgt = res.successes[0]
    assert tgt.exists()
    if os.name != "nt":
        assert src.stat().st_ino == tgt.stat().st_ino


def test_excluded_mapping(tmp_path):
    plan = _make_plan(tmp_path, ["a.mp4", "b.mp4"])
    plan.view_mappings[1].include = False
    res = ImportExecutor(plan).run()
    assert len(res.successes) == 1
    assert len(res.skipped) == 1
    assert res.skipped[0][2] == "excluded"
    meta = json.loads(res.meta_path.read_text(encoding="utf-8"))
    assert len(meta["views"]) == 1


def test_progress_callback(tmp_path):
    plan = _make_plan(tmp_path, ["a.mp4", "b.mp4", "c.mp4"])
    calls = []

    def cb(i, total, src):
        calls.append((i, total, src))

    ImportExecutor(plan, on_progress=cb).run()
    assert len(calls) == 3
    assert calls[0][1] == 3 and calls[-1][0] == 3


def test_validate_errors_fail_fast(tmp_path):
    plan = _make_plan(tmp_path, ["a.mp4"])
    plan.subject_id = ""
    res = ImportExecutor(plan).run()
    assert res.failed, "expected validation failure"
    lib = plan.library_root
    assert not lib.exists() or not any(lib.rglob("*.mp4"))
