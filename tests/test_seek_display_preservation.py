"""Regression tests: seek must never clear or gray the video display.

The decoder/UI contract: while a seek is pending the cell keeps showing the
last good frame; a committed frame replaces it atomically; stale generations
never touch the display.
"""
import numpy as np
from PySide6.QtGui import QImage, QPixmap

from multiview_sync_player.video_cell import VideoCell


def _make_qimage(value):
    img = QImage(32, 18, QImage.Format_RGB888)
    img.fill(value)
    return img


def _make_cell(qtbot, tmp_path):
    cell = VideoCell("camA", str(tmp_path))
    qtbot.addWidget(cell)
    return cell


def test_seek_keeps_last_good_frame(qtbot, tmp_path):
    cell = _make_cell(qtbot, tmp_path)
    good = _make_qimage(120)
    cell.display_image(good, 47)
    key = cell._pixmap.cacheKey()
    assert cell._last_good_pixmap is not None
    assert cell.video_frame._pixmap.cacheKey() == key

    # Seek pending: null/placeholder frames must not clear the display
    cell.video_frame.set_pixmap(None)
    assert cell.video_frame._pixmap.cacheKey() == key
    null_img = QImage()
    assert null_img.isNull()
    cell.display_image(null_img, 48)
    cell.display_image(None, 48)
    assert cell.video_frame._pixmap.cacheKey() == key
    assert cell._pixmap.cacheKey() == key
    assert cell._last_good_pixmap.cacheKey() == key
    assert cell.current_frame == 47


def test_stale_generation_never_replaces_frame(qtbot, tmp_path):
    cell = _make_cell(qtbot, tmp_path)
    good = _make_qimage(80)
    cell.display_image(good, 10)
    key = cell._pixmap.cacheKey()

    # Generation 99 is authoritative; a stale generation-1 reply must be
    # dropped before it can touch the display.
    cell._latest_seek_request_id = 99
    cell._on_seek_frame_ready(1, 99, _make_qimage(200))
    assert cell._pixmap.cacheKey() == key
    assert cell._last_good_pixmap.cacheKey() == key
    assert cell.current_frame == 10


def test_seek_commit_replaces_last_good_atomically(qtbot, tmp_path):
    cell = _make_cell(qtbot, tmp_path)
    cell.display_image(_make_qimage(80), 10)

    new_img = _make_qimage(200)
    new_pixel = new_img.pixelColor(0, 0).value()
    cell.seek_to_frame(11, request_id=5)
    assert cell.video_frame._pixmap is not None  # pending: old frame kept
    # Barrier complete: MainWindow receives the ready callback and commits
    cell._on_seek_frame_ready(5, 11, new_img)
    cell.display_image(new_img, 11)
    displayed = cell.video_frame._pixmap.toImage().pixelColor(0, 0).value()
    assert displayed == new_pixel
    assert cell.current_frame == 11
    # Commit is atomic: display and last-good move to the same pixmap
    last_pixel = cell._last_good_pixmap.toImage().pixelColor(0, 0).value()
    assert last_pixel == new_pixel
    assert cell.video_frame._pixmap.cacheKey() == cell._pixmap.cacheKey()


def test_offset_adjustment_does_not_clear_display(
        qtbot, synthetic_videos, monkeypatch, tmp_path):
    """Emulate the per-view +/- offset flow: full barrier seek, display
    continuity maintained through pending -> commit."""
    monkeypatch.setattr(
        "multiview_sync_player.video_cell.VideoCell.load_audio",
        lambda self, path: None)
    from multiview_sync_player.layout_manager import LayoutConfig
    from multiview_sync_player.main_window import MainWindow
    from multiview_sync_player.session_io import SessionData

    session = SessionData(
        cells=[{
            "view_name": "camA",
            "video_path": str(synthetic_videos["camA"]),
            "total_frames": 180,
            "fps": 25.0,
            "has_audio": False,
            "offset": 0,
        }],
        layout={"rows": 1, "cols": 1,
                "view_names": ["camA"], "view_colors": ["#ff0000"]},
        global_state={"offsets": {"camA": 0}, "markers": [],
                      "metadata": {}},
    )
    window = MainWindow(layout_config=LayoutConfig(
        rows=1, cols=1, view_names=["camA"], view_colors=["#ff0000"]))
    qtbot.addWidget(window)
    window._apply_session_data(session)
    qtbot.waitUntil(
        lambda: window.cells
        and window.cells["camA"]._pixmap is not None
        and window._seek_barrier.active is None,
        timeout=4000)

    cell = window.cells["camA"]
    window.controller.seek_to(50)
    qtbot.waitUntil(
        lambda: cell.current_frame == 50
        and window._seek_barrier.active is None,
        timeout=4000)
    assert cell._pixmap is not None
    keys = [cell._pixmap.cacheKey()]

    # Offset +1 x5 — during each pending window the old frame stays visible
    for expected_offset in (1, 2, 3, 4, 5):
        window.cells["camA"].offset_changed.emit("camA", 1)
        # pending: display must still show a valid pixmap (old frame)
        assert cell.video_frame._pixmap is not None
        qtbot.waitUntil(
            lambda: window._seek_barrier.active is None
            and cell.current_frame == 50 + expected_offset
            and cell.offset == expected_offset,
            timeout=4000)
        assert cell._pixmap is not None
        assert cell._last_good_pixmap is not None
        keys.append(cell._pixmap.cacheKey())

    assert cell.current_frame == 55
    # Every commit actually replaced the frame (no stuck gray frame)
    assert len(set(keys)) == 6

    # Backward offsets too
    window.cells["camA"].offset_changed.emit("camA", -25)
    qtbot.waitUntil(
        lambda: window._seek_barrier.active is None
        and cell.offset == -20
        and cell.current_frame == 30,
        timeout=4000)
    assert cell.video_frame._pixmap is not None
    assert cell._last_good_pixmap is not None
