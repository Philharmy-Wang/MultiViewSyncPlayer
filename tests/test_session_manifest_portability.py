import json
from pathlib import Path

import pytest

from multiview_sync_player.session_io import (
    SessionData,
    SessionFormatError,
    discover_legacy_video_manifests,
    load_session,
    resolve_session_videos,
    save_session,
)


def _data(video_path: Path, *, view="View 1", extra=None):
    return SessionData(
        cells=[{
            "view_name": view,
            "video_path": str(video_path),
            "total_frames": 12,
            "fps": 25.0,
            "has_audio": True,
            "width": 320,
            "height": 180,
            "codec": "mp4v",
        }],
        layout={"rows": 1, "cols": 1, "view_names": [view]},
        global_state={
            "version": "0.2.0",
            "offsets": {view: 3},
            "synced": {view: False},
            "base_frame": 7,
            "review_state": {"base_frame": 7,
                              "per_view": {view: {"local_frame": 9}}},
            "markers": [],
        },
        extra=extra or {},
    )


def test_save_writes_complete_manifest_and_atomic_roundtrip(tmp_path):
    video = tmp_path / "cage2" / "top" / "clip.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"header" + bytes(range(32)) + b"tail")
    session = tmp_path / "clip.mvsp.json"

    save_session(session, _data(video))
    raw = json.loads(session.read_text(encoding="utf-8"))
    manifest = raw["videos"]["View 1"]

    assert raw["format"] == "mvsp.session"
    assert manifest["relative_path"] == "cage2/top/clip.mp4"
    assert manifest["file_name"] == "clip.mp4"
    assert manifest["file_size"] == video.stat().st_size
    assert manifest["quick_fingerprint"]["method"] == (
        "sha256_first_last_1MiB_plus_size")
    assert raw["synced"] == {"View 1": False}
    assert raw["review_state"]["per_view"]["View 1"]["local_frame"] == 9


def test_relative_path_is_preferred_over_absolute_fallback(tmp_path):
    session = tmp_path / "subject" / "s.mvsp.json"
    relative = session.parent / "cage2" / "clip.mp4"
    absolute = tmp_path / "old" / "clip.mp4"
    relative.parent.mkdir(parents=True)
    absolute.parent.mkdir(parents=True)
    relative.write_bytes(b"relative")
    absolute.write_bytes(b"absolute")
    data = _data(absolute)
    data.video_manifests = {"View 1": {
        "path": str(absolute), "relative_path": "cage2/clip.mp4",
        "file_name": "clip.mp4",
    }}

    result = resolve_session_videos(data, session)
    assert result["View 1"].method == "relative"
    assert result["View 1"].path == relative


def test_absolute_fallback_and_moved_tree(tmp_path):
    old_root = tmp_path / "old"
    new_root = tmp_path / "moved"
    old_video = old_root / "cage2" / "clip.mp4"
    moved_video = new_root / "cage2" / "clip.mp4"
    old_video.parent.mkdir(parents=True)
    moved_video.parent.mkdir(parents=True)
    old_video.write_bytes(b"old")
    moved_video.write_bytes(b"moved")
    session = new_root / "s.mvsp.json"
    data = _data(old_video)
    data.video_manifests = {"View 1": {
        "path": str(old_video), "relative_path": "cage2/clip.mp4",
        "file_name": "clip.mp4",
    }}

    result = resolve_session_videos(data, session)
    assert result["View 1"].path == moved_video
    assert result["View 1"].method == "relative"

    moved_video.unlink()
    result = resolve_session_videos(data, session)
    assert result["View 1"].path == old_video
    assert result["View 1"].method == "absolute"


def test_metadata_mismatch_is_not_accepted_silently(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"actual")
    session = tmp_path / "s.mvsp.json"
    data = _data(video)
    data.video_manifests = {"View 1": {
        "path": str(video), "relative_path": "clip.mp4", "file_name": "clip.mp4",
        "file_size": 999,
    }}

    result = resolve_session_videos(data, session)
    assert result["View 1"].path == video
    assert not result["View 1"].ok
    assert "file_size" in result["View 1"].identity_message


def test_missing_view_is_explicit_and_unrelated_json_rejected(tmp_path):
    session = tmp_path / "s.mvsp.json"
    data = SessionData(
        cells=[{"view_name": f"View {idx}", "video_path": str(tmp_path / f"{idx}.mp4")}
               for idx in range(1, 7)],
        global_state={"offsets": {}},
    )
    result = resolve_session_videos(data, session)
    assert sum(item.ok for item in result.values()) == 0
    assert len(result) == 6

    unrelated = tmp_path / "metadata.json"
    unrelated.write_text(json.dumps({"name": "not a session"}), encoding="utf-8")
    with pytest.raises(SessionFormatError):
        load_session(unrelated)


def test_plain_json_and_old_review_defaults_are_supported(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps({
        "version": "0.1.0",
        "videos": {"View 1": {"path": str(video)}},
        "offsets": {"View 1": 4},
        "layout": {"rows": 1, "cols": 1, "view_names": ["View 1"]},
    }), encoding="utf-8")
    data = load_session(plain)
    assert data.cells[0]["video_path"] == str(video)
    assert "review_state" not in data.global_state


def test_legacy_no_video_discovery_uses_strict_subject_layout(tmp_path):
    subject = tmp_path / "24332"
    subject.mkdir()
    session = subject / "TestA_1_24332.json"
    session.write_text(json.dumps({
        "version": "0.1.0", "offsets": {},
        "layout": {"view_names": [f"View {idx}" for idx in range(1, 7)]},
    }), encoding="utf-8")
    for cage in (2, 3, 4):
        for direction in ("top", "front"):
            folder = subject / f"cage{cage}" / direction
            folder.mkdir(parents=True)
            (folder / f"TestA_1_24332_{direction}_{cage}.MP4").write_bytes(b"x")

    data = load_session(session)
    manifests = discover_legacy_video_manifests(session, data)
    assert manifests["View 1"]["path"].endswith("cage2\\top\\TestA_1_24332_top_2.MP4")
    assert manifests["View 6"]["path"].endswith("cage4\\front\\TestA_1_24332_front_4.MP4")
