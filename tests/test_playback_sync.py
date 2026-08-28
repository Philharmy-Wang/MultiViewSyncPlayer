from multiview_sync_player.playback_sync import SeekBarrier


def test_seek_barrier_commits_only_when_every_view_is_exact():
    barrier = SeekBarrier()
    request = barrier.begin(101, {"A": 101, "B": 106, "C": 98})

    assert not barrier.accept(request.generation, "A", 101, "A101")
    assert not barrier.accept(request.generation, "B", 105, "wrong")
    assert not barrier.accept(request.generation, "B", 106, "B106")
    assert barrier.accept(request.generation, "C", 98, "C98")

    finished = barrier.finish(request.generation)
    assert finished.frames == {"A": "A101", "B": "B106", "C": "C98"}


def test_rapid_seek_rejects_every_stale_generation():
    barrier = SeekBarrier()
    requests = [
        barrier.begin(frame, {"A": frame, "B": frame + 5, "C": frame - 3})
        for frame in range(100, 121)
    ]
    latest = requests[-1]

    for old in reversed(requests[:-1]):
        assert not barrier.accept(old.generation, "A", old.base_frame, object())

    assert not barrier.accept(latest.generation, "A", 119, object())
    assert not barrier.accept(latest.generation, "A", 120, object())
    assert not barrier.accept(latest.generation, "B", 125, object())
    assert barrier.accept(latest.generation, "C", 117, object())
    assert barrier.finish(latest.generation).base_frame == 120

