"""Regression coverage for independent stepping of unlinked views."""

from multiview_sync_player.layout_manager import LayoutConfig
from multiview_sync_player.main_window import MainWindow
from multiview_sync_player.session_io import SessionData


def _session(paths, names=("camA", "camB", "camC")):
    source_names = ("camA", "camB", "camC")
    offsets = {name: index - 1 for index, name in enumerate(names)}
    cells = []
    for index, name in enumerate(names):
        cells.append({
            "view_name": name,
            "video_path": str(paths[source_names[index % 3]]),
            "total_frames": 180,
            "fps": 25.0,
            "has_audio": False,
            "offset": offsets[name],
        })
    return SessionData(
        cells=cells,
        layout={
            "rows": 1 if len(names) <= 3 else 2,
            "cols": 3,
            "view_names": list(names),
            "view_colors": ["#ff0000"] * len(names),
        },
        global_state={"offsets": offsets, "markers": [], "metadata": {}},
    )


def _make_window(qtbot, paths, monkeypatch, names=("camA", "camB", "camC")):
    monkeypatch.setattr(
        "multiview_sync_player.video_cell.VideoCell.load_audio",
        lambda self, path: None)
    rows = 1 if len(names) <= 3 else 2
    layout = LayoutConfig(
        rows=rows, cols=3, view_names=list(names),
        view_colors=["#ff0000"] * len(names))
    window = MainWindow(layout_config=layout)
    qtbot.addWidget(window)
    window._apply_session_data(_session(paths, names))
    qtbot.waitUntil(
        lambda: len(window.cells) == len(names)
        and window._backend_init_complete
        and window._seek_barrier.active is None
        and all(cell._pixmap is not None for cell in window.cells.values()),
        timeout=6000)
    return window


def _seek(window, qtbot, frame):
    window.controller.seek_to(frame)
    qtbot.waitUntil(
        lambda: window._seek_barrier.active is None
        and all(cell.current_frame == window.controller.get_target_frame(name)
                for name, cell in window.cells.items() if cell.synced),
        timeout=4000)


def test_unsynced_local_forward_and_backward_refresh_without_moving_master(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        _seek(window, qtbot, 100)
        cell = window.cells["camB"]
        cell._toggle_sync()
        assert cell.local_frame == 100
        assert cell.lbl_offset.text() == "LOCAL"

        before = cell._pixmap.cacheKey()
        cell._request_local_step(1)
        qtbot.waitUntil(
            lambda: cell.current_frame == 101
            and cell.overlay.current_frame == 101
            and cell.slider.value() == 101,
            timeout=2000)
        assert cell.local_frame == 101
        assert window.controller.base_frame == 100
        assert cell._pixmap.cacheKey() != before

        cell._request_local_step(-1)
        qtbot.waitUntil(lambda: cell.current_frame == 100, timeout=2000)
        assert cell.local_frame == 100
        assert window.controller.base_frame == 100
    finally:
        window._clear_all()


def test_synced_local_step_adjusts_offset_and_only_refreshes_that_view(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        _seek(window, qtbot, 100)
        cell = window.cells["camB"]
        untouched = {
            name: other.current_frame
            for name, other in window.cells.items() if name != "camB"
        }

        cell._request_local_step(1)
        qtbot.waitUntil(
            lambda: window._seek_barrier.active is None
            and cell.current_frame == 101,
            timeout=3000)
        assert window.controller.base_frame == 100
        assert window.controller.offsets["camB"] == 1
        assert all(window.cells[name].current_frame == frame
                   for name, frame in untouched.items())
    finally:
        window._clear_all()


def test_unsynced_global_step_is_ignored(qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        _seek(window, qtbot, 100)
        cell = window.cells["camB"]
        cell._toggle_sync()
        fixed_frame = cell.current_frame
        fixed_key = cell._pixmap.cacheKey()

        window._step_frames(25)
        qtbot.waitUntil(
            lambda: window.controller.base_frame == 125
            and window._seek_barrier.active is None,
            timeout=3000)
        assert cell.local_frame == fixed_frame
        assert cell.current_frame == fixed_frame
        assert cell._pixmap.cacheKey() == fixed_key
    finally:
        window._clear_all()


def test_unlink_and_relink_preserve_visual_frame_after_master_moves(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        window.controller.offsets["camB"] = 43
        window.cells["camB"].set_offset(43)
        _seek(window, qtbot, 100)
        cell = window.cells["camB"]
        assert cell.current_frame == 143

        cell._toggle_sync()
        qtbot.waitUntil(lambda: window._seek_barrier.active is None,
                        timeout=3000)
        assert cell.current_frame == cell.local_frame == 143

        window._step_frames(25)
        qtbot.waitUntil(
            lambda: window.controller.base_frame == 125
            and window._seek_barrier.active is None,
            timeout=3000)
        assert cell.current_frame == cell.local_frame == 143

        cell._toggle_sync()
        qtbot.waitUntil(lambda: window._seek_barrier.active is None,
                        timeout=3000)
        assert window.controller.offsets["camB"] == 18
        assert cell.offset == 18
        assert cell.current_frame == cell.local_frame == 143
    finally:
        window._clear_all()


def test_unsynced_rapid_steps_latest_generation_wins(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        _seek(window, qtbot, 100)
        cell = window.cells["camA"]
        cell._toggle_sync()
        initial = cell.current_frame
        for _ in range(20):
            cell._request_local_step(1)
        qtbot.waitUntil(
            lambda: cell.current_frame == initial + 20
            and cell.overlay.current_frame == initial + 20,
            timeout=3000)
        assert cell.local_frame == initial + 20
        assert window.controller.base_frame == 100
        assert cell._latest_seek_request_id == -20
    finally:
        window._clear_all()


def test_unsynced_local_seek_clamps_per_view_and_slider_updates_local_state(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        _seek(window, qtbot, 0)
        cell = window.cells["camA"]
        cell._toggle_sync()
        cell._request_local_step(-1)
        qtbot.waitUntil(lambda: cell.current_frame == 0, timeout=1000)
        assert cell.local_frame == 0

        cell._request_local_step(1000)
        qtbot.waitUntil(lambda: cell.current_frame == 179, timeout=3000)
        assert cell.local_frame == 179
        cell._request_local_step(1)
        qtbot.waitUntil(lambda: cell.current_frame == 179, timeout=1000)
        assert cell.local_frame == 179

        cell._on_slider_moved(77)
        qtbot.waitUntil(lambda: cell.current_frame == 77, timeout=3000)
        assert cell.local_frame == 77
        assert window.controller.base_frame == 0
    finally:
        window._clear_all()


def test_unlinked_plus_minus_25_use_generation_safe_prefetch_decoder_path(
        qtbot, synthetic_videos, monkeypatch):
    window = _make_window(qtbot, synthetic_videos, monkeypatch)
    try:
        _seek(window, qtbot, 75)
        cell = window.cells["camA"]
        cell._toggle_sync()
        initial = cell.current_frame
        calls = []
        real_request = cell.decoder.request_frame

        def record_request(frame, request_id):
            calls.append((frame, request_id))
            return real_request(frame, request_id)

        monkeypatch.setattr(cell.decoder, "request_frame", record_request)
        cell._request_local_step(25)
        qtbot.waitUntil(lambda: cell.current_frame == initial + 25,
                        timeout=3000)
        cell._request_local_step(-25)
        qtbot.waitUntil(lambda: cell.current_frame == initial, timeout=3000)

        assert calls == [(initial + 25, -1), (initial, -2)]
        assert all(request_id < 0 for _, request_id in calls)
    finally:
        window._clear_all()


def test_mixed_six_view_barrier_and_relink_semantics(
        qtbot, synthetic_videos, monkeypatch):
    names = tuple(f"View{i}" for i in range(1, 7))
    window = _make_window(qtbot, synthetic_videos, monkeypatch, names)
    barrier_targets = []
    real_begin = window._seek_barrier.begin

    def record_begin(base_frame, targets, retry_count=0):
        barrier_targets.append((base_frame, dict(targets)))
        return real_begin(base_frame, targets, retry_count)

    monkeypatch.setattr(window._seek_barrier, "begin", record_begin)
    try:
        _seek(window, qtbot, 100)
        for name in ("View3", "View5"):
            window.cells[name]._toggle_sync()
            qtbot.waitUntil(lambda: window._seek_barrier.active is None,
                            timeout=4000)
        window.cells["View3"]._request_local_step(7)
        window.cells["View5"]._request_local_step(-5)
        qtbot.waitUntil(
            lambda: window.cells["View3"].current_frame == 108
            and window.cells["View5"].current_frame == 98,
            timeout=3000)
        local_frames = {
            name: window.cells[name].current_frame
            for name in ("View3", "View5")
        }

        window._step_frames(25)
        qtbot.waitUntil(
            lambda: window.controller.base_frame == 125
            and window._seek_barrier.active is None,
            timeout=4000)
        assert set(barrier_targets[-1][1]) == {
            "View1", "View2", "View4", "View6"}
        assert all(window.cells[name].current_frame == frame
                   for name, frame in local_frames.items())
        normalized = [
            window.cells[name].current_frame
            - window.controller.offsets[name]
            for name in ("View1", "View2", "View4", "View6")
        ]
        assert max(normalized) - min(normalized) == 0

        for name in ("View3", "View5"):
            before = window.cells[name].current_frame
            window.cells[name]._toggle_sync()
            qtbot.waitUntil(lambda: window._seek_barrier.active is None,
                            timeout=4000)
            assert window.cells[name].current_frame == before
            assert window.controller.offsets[name] == before - 125
    finally:
        window._clear_all()
