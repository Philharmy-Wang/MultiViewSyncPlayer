import os
import shutil
from types import SimpleNamespace

from multiview_sync_player import media_cache, video_decoder


def _isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("MVSP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(media_cache, "tool_version", lambda executable: "test-version")
    media_cache.reset_cache_metrics()
    video_decoder._KEYFRAME_INDEX_CACHE.clear()


def test_metadata_cache_hit_miss_and_invalidation(
        synthetic_videos, monkeypatch, tmp_path):
    _isolated_cache(monkeypatch, tmp_path)
    source = tmp_path / "camA.avi"
    shutil.copy2(synthetic_videos["camA"], source)

    first = video_decoder.probe_video_metadata(source)
    second = video_decoder.probe_video_metadata(source)
    assert first == second
    metrics = media_cache.cache_metrics()
    assert metrics["metadata_misses"] == 1
    assert metrics["metadata_hits"] == 1

    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    video_decoder.probe_video_metadata(source)
    assert media_cache.cache_metrics()["metadata_misses"] == 2


def test_keyframe_cache_hit_miss_and_persistence(
        synthetic_videos, monkeypatch, tmp_path):
    _isolated_cache(monkeypatch, tmp_path)
    source = synthetic_videos["camB"]
    monkeypatch.setattr(video_decoder, "FFPROBE_PATH", "test-ffprobe")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=b"0.000000,K_\n1.000000,K_\n", returncode=0)

    monkeypatch.setattr(video_decoder, "run_hidden", fake_run)
    first = video_decoder.probe_keyframe_index(source, 25.0)
    video_decoder._KEYFRAME_INDEX_CACHE.clear()
    second = video_decoder.probe_keyframe_index(source, 25.0)

    assert first == [0, 25]
    assert second == first
    assert len(calls) == 1
    assert media_cache.get_packet_count(source) == 2
    metrics = media_cache.cache_metrics()
    assert metrics["keyframe_scans"] == 1
    assert metrics["keyframe_hits"] == 1
