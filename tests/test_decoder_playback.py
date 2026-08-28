from multiview_sync_player.video_decoder import PrefetchDecoder


def test_adjacent_step_uses_sequential_decode_and_recent_cache(
        qtbot, synthetic_videos):
    decoder = PrefetchDecoder(
        synthetic_videos["camA"], target_width=320,
        buffer_size=24, cache_size=64)
    results = []
    decoder.frame_ready.connect(
        lambda request, frame, image: results.append((request, frame, image)))
    decoder.start()
    try:
        decoder.request_frame(100, 1)
        qtbot.waitUntil(lambda: any(r[:2] == (1, 100) for r in results),
                        timeout=3000)
        initial_random_seeks = decoder.metrics()["random_seeks"]

        decoder.request_frame(101, 2)
        qtbot.waitUntil(lambda: any(r[:2] == (2, 101) for r in results),
                        timeout=1000)
        assert decoder.metrics()["random_seeks"] == initial_random_seeks

        decoder.request_frame(100, 3)
        qtbot.waitUntil(lambda: any(r[:2] == (3, 100) for r in results),
                        timeout=300)
        metrics = decoder.metrics()
        assert metrics["cache_hits"] >= 1
        assert metrics["random_seeks"] == initial_random_seeks
    finally:
        decoder.stop()
