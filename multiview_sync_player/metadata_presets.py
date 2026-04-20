"""
multiview_sync_player.metadata_presets — 预设元数据模板

常见场景的字段模板。每个预设有 'name'（显示名）和 'fields'（OrderedDict）。
"""

from collections import OrderedDict

PRESETS = [
    {
        "name": "通用实验",
        "fields": OrderedDict([
            ("session_name", ""),
            ("date", ""),
            ("operator", ""),
            ("notes", ""),
        ]),
    },
    {
        "name": "动物行为",
        "fields": OrderedDict([
            ("subject_id", ""),
            ("species", ""),
            ("date", ""),
            ("experiment", ""),
            ("operator", ""),
        ]),
    },
    {
        "name": "多视角同步对齐",
        "fields": OrderedDict([
            ("session_name", ""),
            ("date", ""),
            ("subject_id", ""),
            ("experiment", ""),
            ("operator", ""),
            ("notes", ""),
        ]),
    },
    {
        "name": "体育分析",
        "fields": OrderedDict([
            ("event", ""),
            ("athlete", ""),
            ("date", ""),
            ("location", ""),
        ]),
    },
    {
        "name": "工业监控",
        "fields": OrderedDict([
            ("station_id", ""),
            ("shift", ""),
            ("date", ""),
        ]),
    },
    {
        "name": "自定义",
        "fields": OrderedDict(),
    },
]


def get_preset_names() -> list:
    return [p["name"] for p in PRESETS]


def get_preset_by_name(name: str) -> dict:
    for p in PRESETS:
        if p["name"] == name:
            return p
    return None
