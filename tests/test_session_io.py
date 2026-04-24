"""tests/test_session_io — Pure-function tests for session_io module."""

import json
from pathlib import Path

import pytest

from multiview_sync_player.session_io import (
    SESSION_FORMAT,
    SESSION_VERSION,
    SessionData,
    SessionFormatError,
    detect_library_ref,
    load_session,
    save_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_data() -> SessionData:
    return SessionData(
        cells=[
            {
                "view_name": "View 1",
                "video_path": "/data/front.mp4",
                "total_frames": 9000,
                "fps": 30.0,
                "has_audio": False,
                "offset": 0,
            },
            {
                "view_name": "View 2",
                "video_path": "/data/top.mp4",
                "total_frames": 9000,
                "fps": 30.0,
                "has_audio": True,
                "offset": 5,
            },
        ],
        layout={
            "rows": 1,
            "cols": 2,
            "view_names": ["View 1", "View 2"],
            "view_colors": ["#42a5f5", "#ef5350"],
        },
        global_state={
            "version": SESSION_VERSION,
            "created": "2026-04-24T12:00:00",
            "offsets": {"View 1": 0, "View 2": 5},
            "markers": [
                {"frame": 100, "time_str": "00:03.33", "note": "Marker 1",
                 "view_frames": {"View 1": 100, "View 2": 105}},
            ],
            "metadata": {"experiment": "ThreeChamber", "subject": "24332"},
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRoundtrip:
    def test_save_load_roundtrip(self, tmp_path):
        """SessionData → save → load → 字段全等。"""
        path = tmp_path / "test.mvsp.json"
        original = _sample_data()
        save_session(path, original)

        loaded = load_session(path)

        assert loaded.cells == original.cells
        assert loaded.layout == original.layout
        assert loaded.global_state == original.global_state
        assert loaded.extra == original.extra


class TestValidation:
    def test_load_invalid_format(self, tmp_path):
        """format 字段值不匹配 → SessionFormatError。"""
        path = tmp_path / "bad.mvsp.json"
        path.write_text(json.dumps({
            "version": SESSION_VERSION,
            "format": "wrong.format",
            "videos": {},
            "offsets": {},
            "markers": [],
        }), encoding="utf-8")

        with pytest.raises(SessionFormatError, match="Format mismatch"):
            load_session(path)

    def test_load_missing_version(self, tmp_path):
        """缺 version 字段 → SessionFormatError。"""
        path = tmp_path / "noversion.mvsp.json"
        path.write_text(json.dumps({
            "videos": {},
            "offsets": {},
            "markers": [],
        }), encoding="utf-8")

        with pytest.raises(SessionFormatError, match="Missing required"):
            load_session(path)


class TestUnicode:
    def test_save_unicode(self, tmp_path):
        """中文路径/标注 → roundtrip 不损坏。"""
        path = tmp_path / "unicode.mvsp.json"
        original = SessionData(
            cells=[
                {
                    "view_name": "前-1",
                    "video_path": "D:/视频/实验/前侧.mp4",
                    "total_frames": 5000,
                    "fps": 25.0,
                    "has_audio": False,
                    "offset": 10,
                },
            ],
            layout={"rows": 1, "cols": 1,
                    "view_names": ["前-1"], "view_colors": ["#42a5f5"]},
            global_state={
                "version": SESSION_VERSION,
                "offsets": {"前-1": 10},
                "markers": [],
                "metadata": {"备注": "测试中文"},
            },
        )
        save_session(path, original)
        loaded = load_session(path)

        assert loaded.cells[0]["video_path"] == "D:/视频/实验/前侧.mp4"
        assert loaded.cells[0]["view_name"] == "前-1"
        assert loaded.global_state["metadata"]["备注"] == "测试中文"

        # Also verify the raw JSON contains actual Unicode (not escaped)
        raw = path.read_text(encoding="utf-8")
        assert "前侧" in raw
        assert "备注" in raw


# ---------------------------------------------------------------------------
# library_ref tests (Step 8b)
# ---------------------------------------------------------------------------

class TestLibraryRef:
    def test_save_with_library_ref(self, tmp_path):
        """SessionData.library_ref 非空 → save → load → 字段全等。"""
        path = tmp_path / "with_lib.mvsp.json"
        lib_ref = {
            "root": "/data/library",
            "experiment": "ThreeChamber",
            "date": "2026-01-26",
            "subject": "24332",
        }
        original = _sample_data()
        original.library_ref = lib_ref
        save_session(path, original)

        loaded = load_session(path)
        assert loaded.library_ref == lib_ref

    def test_load_legacy_no_library_ref(self, tmp_path):
        """旧格式 JSON（无 library_ref 键）→ load 成功 + library_ref is None。"""
        path = tmp_path / "legacy.mvsp.json"
        path.write_text(json.dumps({
            "version": SESSION_VERSION,
            "videos": {"View 1": {"path": "/a.mp4", "total_frames": 100,
                                  "fps": 30.0, "has_audio": False}},
            "offsets": {"View 1": 0},
            "markers": [],
        }), encoding="utf-8")

        loaded = load_session(path)
        assert loaded.library_ref is None


class TestDetectLibraryRef:
    def test_detect_library_ref_hit(self, tmp_path):
        """所有 video_paths 位于同一 subject 目录 → detect 命中。"""
        lib_root = tmp_path / "lib"
        exp_dir = lib_root / "ThreeChamber" / "2026-01-26" / "24332"
        exp_dir.mkdir(parents=True)

        paths = [
            str(exp_dir / "front.mp4"),
            str(exp_dir / "top.mp4"),
        ]
        result = detect_library_ref(paths, [lib_root])
        assert result is not None
        assert result["experiment"] == "ThreeChamber"
        assert result["date"] == "2026-01-26"
        assert result["subject"] == "24332"

    def test_detect_library_ref_miss_cross_subject(self, tmp_path):
        """video_paths 跨 subject → detect 返回 None。"""
        lib_root = tmp_path / "lib"
        dir1 = lib_root / "Exp" / "2026-01-01" / "subj1"
        dir2 = lib_root / "Exp" / "2026-01-01" / "subj2"
        dir1.mkdir(parents=True)
        dir2.mkdir(parents=True)

        paths = [str(dir1 / "a.mp4"), str(dir2 / "b.mp4")]
        result = detect_library_ref(paths, [lib_root])
        assert result is None

    def test_detect_library_ref_miss_outside_library(self, tmp_path):
        """video_paths 不在任何 known library 下 → detect 返回 None。"""
        other = tmp_path / "somewhere" / "else.mp4"
        paths = [str(other)]
        lib_root = tmp_path / "lib"
        lib_root.mkdir()

        result = detect_library_ref(paths, [lib_root])
        assert result is None
