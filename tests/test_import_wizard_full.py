import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _setup_wizard(qapp, tmp_path, names):
    from multiview_sync_player.library.import_wizard import ImportWizard

    srcs = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"x" * 1024)
        srcs.append(p)
    lib = tmp_path / "lib"
    wiz = ImportWizard(default_library_root=lib)
    wiz.setField("library_root", str(lib))
    wiz.setField("experiment", "ThreeChamber")
    wiz.setField("subject_id", "24332")
    src_page = wiz.page(1)
    src_page._add_paths(srcs)
    views_page = wiz.page(2)
    views_page.initializePage()
    return wiz, views_page


def test_views_page_autodetect_fills_rows(qapp, tmp_path):
    wiz, views = _setup_wizard(qapp, tmp_path, ["前-1.mp4", "前-2.mp4", "top.mp4"])
    ms = views.view_mappings()
    assert len(ms) == 3
    assert ms[0].direction == "front" and ms[0].index == 1
    assert ms[2].direction == "top"


def test_views_page_incomplete_when_no_include(qapp, tmp_path):
    wiz, views = _setup_wizard(qapp, tmp_path, ["前-1.mp4"])
    from PySide6.QtCore import Qt

    from PySide6.QtWidgets import QCheckBox

    for row in range(views._table.rowCount()):
        wrapper = views._table.cellWidget(row, 5)
        chk = wrapper.findChild(QCheckBox) if wrapper else None
        if chk:
            chk.setChecked(False)
    assert views.isComplete() is False


def test_review_page_preview_contains_paths(qapp, tmp_path):
    wiz, views = _setup_wizard(qapp, tmp_path, ["前-1.mp4", "top.mp4"])
    review = wiz.page(3)
    review.initializePage()
    text = review._text.toPlainText()
    assert "ThreeChamber" in text
    assert "24332" in text
    assert "前-1.mp4" in text
    assert "top.mp4" in text


def test_full_wizard_get_plan(qapp, tmp_path):
    wiz, views = _setup_wizard(qapp, tmp_path, ["前-1.mp4", "前-2.mp4", "top.mp4"])
    review = wiz.page(3)
    review.initializePage()
    plan = wiz.get_plan()
    assert plan.experiment == "ThreeChamber"
    assert plan.subject_id == "24332"
    assert len(plan.view_mappings) == 3
    assert plan.conflict_policy in ("skip", "rename", "overwrite")
    assert plan.copy_mode in ("copy", "hardlink", "move")
    errs = plan.validate()
    assert errs == [], f"expected no errors, got {errs}"


def test_review_page_shows_errors_when_duplicate(qapp, tmp_path):
    wiz, views = _setup_wizard(qapp, tmp_path, ["a.mp4", "b.mp4"])
    # Set both view names to the same value → duplicate after sanitize
    views._table.item(0, 1).setText("dup")
    views._table.item(1, 1).setText("dup")
    review = wiz.page(3)
    review.initializePage()
    plan = wiz.get_plan()
    errs = plan.validate()
    assert any("重复" in e or "duplicate" in e.lower() for e in errs)
