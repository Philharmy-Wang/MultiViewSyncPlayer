import pytest

from multiview_sync_player.sync_controller import SyncController


@pytest.fixture
def controller():
    ctrl = SyncController()
    ctrl.video_info = {
        "A": {"total_frames": 200, "fps": 25.0},
        "B": {"total_frames": 200, "fps": 25.0},
        "C": {"total_frames": 200, "fps": 25.0},
    }
    ctrl.offsets = {"A": 0, "B": 5, "C": -3}
    ctrl.enabled_views = {"A", "B", "C"}
    return ctrl


@pytest.mark.parametrize("start,delta,expected", [
    (100, 1, 101),
    (100, -1, 99),
    (100, 25, 125),
    (100, -25, 75),
    (100, 100, 200),
    (100, -100, 0),
    (0, -1, 0),
    (500, 1, 202),
])
def test_step_frames_and_clamping(controller, start, delta, expected):
    controller.base_frame = start
    controller.step_frames(delta)
    assert controller.base_frame == expected


def test_offset_mapping(controller):
    controller.base_frame = 101
    assert controller.get_target_frame("A") == 101
    assert controller.get_target_frame("B") == 106
    assert controller.get_target_frame("C") == 98


def test_disabled_view_does_not_define_end(controller):
    controller.video_info["C"]["total_frames"] = 1000
    controller.set_view_enabled("C", False)
    assert controller._max_base_frame() == 199


def test_unsynced_view_can_be_excluded_from_master_clock(controller):
    controller.video_info["B"]["fps"] = 30.0
    assert controller.master_view(["A", "C"]) == "A"
    assert controller.master_fps(["A", "C"]) == 25.0
    assert controller.fps_mismatches(["A", "C"]) == {}


def test_fps_mismatch_is_explicit(controller):
    controller.video_info["B"]["fps"] = 29.97
    assert controller.master_view() == "A"
    assert controller.fps_mismatches() == {"B": 29.97}
