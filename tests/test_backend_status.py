from multiview_sync_player.video_cell import VideoCell


def test_precision_backend_status(qtbot, tmp_path):
    cell = VideoCell("cam", str(tmp_path))
    qtbot.addWidget(cell)
    status = cell.backend_status("hevc")
    assert status == {
        "backend": "opencv", "codec": "hevc", "hwdec_current": "none",
        "gpu_decode_active": False, "dropped_frames": 0,
    }
