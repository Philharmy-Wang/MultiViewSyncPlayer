"""tests/test_session_io — Pure-function tests for session_io module."""

import json
from pathlib import Path

import pytest

from multiview_sync_player.session_io import (
    SESSION_FORMAT,
    SESSION_VERSION,
    SessionData,
    SessionFormatError,
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
