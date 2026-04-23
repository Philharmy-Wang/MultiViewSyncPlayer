import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_wizard_has_four_pages(qapp):
    from multiview_sync_player.library.import_wizard import ImportWizard

    wiz = ImportWizard()
    assert len(wiz.pageIds()) == 4


def test_meta_page_incomplete_when_empty(qapp):
    from multiview_sync_player.library.import_wizard import ImportWizard

    wiz = ImportWizard()
    meta = wiz.page(0)
    assert meta.isComplete() is False


def test_meta_page_complete_when_filled(qapp, tmp_path):
    from multiview_sync_player.library.import_wizard import ImportWizard

    wiz = ImportWizard(default_library_root=tmp_path)
    meta = wiz.page(0)
    wiz.setField("library_root", str(tmp_path))
    wiz.setField("experiment", "ThreeChamber")
    wiz.setField("subject_id", "24332")
    assert meta.isComplete() is True


def test_sources_page_incomplete_empty(qapp):
    from multiview_sync_player.library.import_wizard import ImportWizard

    wiz = ImportWizard()
    src = wiz.page(1)
    assert src.isComplete() is False


def test_sources_page_add_file(qapp, tmp_path):
    from multiview_sync_player.library.import_wizard import ImportWizard

    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    wiz = ImportWizard()
    src = wiz.page(1)
    src._add_paths([f])
    assert src.isComplete() is True
    assert f in src.sources()


def test_get_plan_autodetect(qapp, tmp_path):
    from multiview_sync_player.library.import_wizard import ImportWizard

    (tmp_path / "前-1.mp4").write_bytes(b"x")
    (tmp_path / "top.mp4").write_bytes(b"x")
    wiz = ImportWizard(default_library_root=tmp_path / "lib")
    wiz.setField("library_root", str(tmp_path / "lib"))
    wiz.setField("experiment", "Exp")
    wiz.setField("subject_id", "s1")
    src = wiz.page(1)
    src._add_paths([tmp_path / "前-1.mp4", tmp_path / "top.mp4"])
    plan = wiz.get_plan()
    assert plan.experiment == "Exp"
    assert len(plan.view_mappings) == 2
    assert plan.view_mappings[0].direction == "front"
    assert plan.view_mappings[1].direction == "top"
