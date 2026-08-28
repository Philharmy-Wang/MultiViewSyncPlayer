from multiview_sync_player.layout_manager import LayoutConfig
from multiview_sync_player.main_window import MainWindow
from multiview_sync_player.session_io import SessionData


def _session(paths):
    offsets = {"camA": 0, "camB": 5, "camC": -3}
    cells = [
        {
            "view_name": camera,
            "video_path": str(paths[camera]),
            "total_frames": 180,
            "fps": 25.0,
            "has_audio": False,
            "offset": offsets[camera],
        }
        for camera in ("camA", "camB", "camC")
    ]
    return SessionData(
        cells=cells,
        layout={
            "rows": 1, "cols": 3,
            "view_names": ["camA", "camB", "camC"],
            "view_colors": ["#ff0000", "#00ff00", "#0000ff"],
        },
        global_state={"offsets": offsets, "markers": [], "metadata": {}},
    )


def _make_window(qtbot, paths, monkeypatch):
    monkeypatch.setattr(
        "multiview_sync_player.video_cell.VideoCell.load_audio",
        lambda self, path: None)
    layout = LayoutConfig(
        rows=1, cols=3,
        view_names=["camA", "camB", "camC"],
        view_colors=["#ff0000", "#00ff00", "#0000ff"])
    window = MainWindow(layout_config=layout)
    qtbot.addWidget(window)
    window._apply_session_data(_session(paths))
    qtbot.waitUntil(
        lambda: len(window.cells) == 3
        and all(cell.decoder is not None for cell in window.cells.values()),
        timeout=3000)
    qtbot.waitUntil(
        lambda: window._backend_init_complete
        and window._seek_barrier.active is None
        and all(cell._pixmap is not None for cell in window.cells.values()),
        timeout=4000)
    return window


def _assert_targets(window, base):
    expected = {"camA": base, "camB": base + 5, "camC": base - 3}
    for view, target in expected.items():
        cell = window.cells[view]
        assert cell.current_frame == target
        assert cell.overlay.current_frame == target
        assert cell.slider.value() == target


def test_paused_step_refreshes_pixels_overlay_and_slider_together(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        window.controller.seek_to(100)
        qtbot.waitUntil(
            lambda: all(window.cells[v].current_frame == target for v, target in
                        {"camA": 100, "camB": 105, "camC": 97}.items()),
            timeout=3000)
        old_pixmaps = {
            view: cell._pixmap.cacheKey() for view, cell in window.cells.items()
        }

        window._step_frames(1)
        qtbot.waitUntil(
            lambda: all(window.cells[v].current_frame == target for v, target in
                        {"camA": 101, "camB": 106, "camC": 98}.items()),
            timeout=1500)
        _assert_targets(window, 101)
        assert all(window.cells[view]._pixmap.cacheKey() != old_pixmaps[view]
                   for view in old_pixmaps)
        assert not window.controller.is_playing
    finally:
        window._clear_all()


def test_rapid_step_latest_generation_wins(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        window.controller.seek_to(100)
        for _ in range(20):
            window._step_frames(1)
        qtbot.waitUntil(
            lambda: window.controller.base_frame == 120
            and all(window.cells[v].current_frame == target for v, target in
                    {"camA": 120, "camB": 125, "camC": 117}.items()),
            timeout=3000)
        _assert_targets(window, 120)
        assert window._seek_barrier.active is None
    finally:
        window._clear_all()


def test_disabled_and_unsynced_views_do_not_join_global_barrier(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        window.controller.seek_to(100)
        qtbot.waitUntil(lambda: window._seek_barrier.active is None,
                        timeout=3000)
        window.cells["camB"]._toggle_sync()
        qtbot.waitUntil(lambda: window._seek_barrier.active is None,
                        timeout=3000)
        window.cells["camC"]._toggle_enable()
        qtbot.waitUntil(lambda: window._seek_barrier.active is None,
                        timeout=3000)
        untouched = {
            view: window.cells[view]._pixmap.cacheKey()
            for view in ("camB", "camC")
        }

        window._step_frames(1)
        qtbot.waitUntil(
            lambda: window._seek_barrier.active is None
            and window.cells["camA"].current_frame == 101,
            timeout=1500)
        assert all(window.cells[view]._pixmap.cacheKey() == key
                   for view, key in untouched.items())
    finally:
        window._clear_all()


def test_strict_playback_has_zero_inter_view_drift_and_clamps_end(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    samples = []
    window.play_timer.timeout.connect(lambda: samples.append([
        window.cells["camA"].current_frame,
        window.cells["camB"].current_frame - 5,
        window.cells["camC"].current_frame + 3,
    ]))
    try:
        window.controller.seek_to(20)
        qtbot.waitUntil(
            lambda: window._seek_barrier.active is None
            and window.cells["camA"].current_frame == 20,
            timeout=3000)
        window.controller.toggle_play()
        qtbot.waitUntil(lambda: window.controller.base_frame >= 45,
                        timeout=4000)
        window.controller.pause()
        assert samples
        assert max(max(sample) - min(sample) for sample in samples) == 0

        window.controller.seek_to(window.controller._max_base_frame() - 2)
        qtbot.waitUntil(lambda: window._seek_barrier.active is None,
                        timeout=3000)
        window.controller.toggle_play()
        qtbot.waitUntil(lambda: not window.controller.is_playing,
                        timeout=3000)
        assert window.controller.base_frame == window.controller._max_base_frame()
    finally:
        window._clear_all()
