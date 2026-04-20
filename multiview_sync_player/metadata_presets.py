"""
multiview_sync_player.metadata_presets — Preset metadata templates

Common field templates for different use scenarios.
Each preset is a dict with 'name' (display name) and 'fields' (OrderedDict).
"""

from collections import OrderedDict

PRESETS = [
    {
        "name": "General Experiment",
        "fields": OrderedDict([
            ("session_name", ""),
            ("date", ""),
            ("operator", ""),
            ("notes", ""),
        ]),
    },
    {
        "name": "Animal Behavior",
        "fields": OrderedDict([
            ("subject_id", ""),
            ("species", ""),
            ("date", ""),
            ("experiment", ""),
            ("operator", ""),
        ]),
    },
    {
        "name": "Sports Analysis",
        "fields": OrderedDict([
            ("event", ""),
            ("athlete", ""),
            ("date", ""),
            ("location", ""),
        ]),
    },
    {
        "name": "Industrial Monitoring",
        "fields": OrderedDict([
            ("station_id", ""),
            ("shift", ""),
            ("date", ""),
        ]),
    },
    {
        "name": "Custom",
        "fields": OrderedDict(),
    },
]


def get_preset_names() -> list:
    """Return list of preset display names."""
    return [p["name"] for p in PRESETS]


def get_preset_by_name(name: str) -> dict:
    """Get preset dict by display name. Returns None if not found."""
    for p in PRESETS:
        if p["name"] == name:
            return p
    return None
