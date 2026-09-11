from multiview_sync_player.layout_manager import LayoutConfig
from multiview_sync_player.main_window import MainWindow
from multiview_sync_player.session_io import SessionData, save_session, load_session


def _session(paths):
    names = ["camA", "camB", "camC"]
    offsets = {"camA": 0, "camB": 5, "camC": -3}
    cells = [
        {
            "view_name": name,
            "video_path": str(paths[name]),
            "total_frames": 180,
            "fps": 25.0,
            "has_audio": False,
            "offset": offsets[name],
        }
        for name in names
    ]
    return SessionData(
        cells=cells,
        layout=LayoutConfig(
            rows=1, cols=3, view_names=names,
            view_colors=["#ff0000", "#00ff00", "#0000ff"]).to_dict(),
        global_state={
            "version": "0.2.0",
            "offsets": offsets,
            "synced": {"camA": True, "camB": False, "camC": True},
            "base_frame": 20,
            "review_state": {"base_frame": 20,
                              "per_view": {"camB": {"local_frame": 37}}},
            "markers": [],
        },
    )


def test_open_session_auto_loads_and_restores_review_state(
        qtbot, synthetic_videos, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "multiview_sync_player.video_cell.VideoCell.load_audio",
        lambda self, path: None)
    source = tmp_path / "portable.mvsp.json"
    save_session(source, _session(synthetic_videos))

    window = MainWindow()
    qtbot.addWidget(window)
    window._load_session(str(source))
    qtbot.waitUntil(
        lambda: len(window.cells) == 3
        and all(cell.decoder is not None for cell in window.cells.values()),
        timeout=4000)
    qtbot.waitUntil(
        lambda: window._backend_init_complete
        and window._seek_barrier.active is None
        and all(cell._pixmap is not None for cell in window.cells.values()),
        timeout=6000)

    assert window.controller.base_frame == 20
    assert window.cells["camA"].synced is True
    assert window.cells["camB"].synced is False
    assert window.cells["camB"].local_frame == 37

    saved_again = tmp_path / "saved_again.mvsp.json"
    save_session(saved_again, window._collect_session_data())
    reopened = load_session(saved_again)
    assert reopened.global_state["synced"]["camB"] is False
    assert reopened.global_state["review_state"]["per_view"]["camB"]["local_frame"] == 37
