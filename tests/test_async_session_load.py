import time

from multiview_sync_player.layout_manager import LayoutConfig
from multiview_sync_player.main_window import MainWindow
from multiview_sync_player.session_io import SessionData, save_session


def test_session_probe_does_not_block_gui(
        qtbot, synthetic_videos, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "multiview_sync_player.video_cell.VideoCell.load_audio",
        lambda self, path: None)
    from multiview_sync_player import main_window
    real_probe = main_window.probe_video_metadata

    def slow_probe(path):
        time.sleep(0.2)
        return real_probe(path)

    monkeypatch.setattr(main_window, "probe_video_metadata", slow_probe)
    session_path = tmp_path / "async.mvsp.json"
    data = SessionData(
        cells=[{
            "view_name": "camA", "video_path": str(synthetic_videos["camA"]),
            "total_frames": 180, "fps": 25.0, "has_audio": False,
        }],
        layout={"rows": 1, "cols": 1, "view_names": ["camA"],
                "view_colors": ["#ff0000"]},
        global_state={"offsets": {"camA": 0}, "markers": []},
    )
    save_session(session_path, data)
    window = MainWindow(layout_config=LayoutConfig(rows=1, cols=1))
    qtbot.addWidget(window)

    started = time.perf_counter()
    window._load_session(str(session_path))
    elapsed = time.perf_counter() - started
    assert elapsed < 0.15
    assert window.layout_config.view_names == ["camA"]
    qtbot.waitUntil(lambda: window._backend_init_complete and bool(window.cells),
                    timeout=6000)
