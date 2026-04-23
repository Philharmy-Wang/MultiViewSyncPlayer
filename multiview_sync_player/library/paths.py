"""multiview_sync_player.library.paths — Path sanitization and directory layout.

Provides helpers to build the canonical library directory structure:
    <library_root>/<experiment>/<YYYY-MM-DD>/<subject>/<view>.<ext>

All functions accept and return pathlib.Path objects.
Dates are always ISO-formatted (YYYY-MM-DD).

Generated: 2026-04-23 20:00:00
"""

import datetime
import re
from pathlib import Path

# Characters forbidden in Windows file/directory names
_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRAILING_RE = re.compile(r'[ .]+$')


def sanitize(name: str, replacement: str = "_") -> str:
    """Replace illegal filesystem characters in *name*.

    Strips Windows-forbidden chars (<>:"/\\|?*), control chars (0x00-0x1f),
    and trailing spaces/dots.

    Args:
        name:        Raw name string.
        replacement: Character to substitute for each illegal char.

    Returns:
        Sanitized string safe for use as a path segment.
    """
    cleaned = _ILLEGAL_RE.sub(replacement, name)
    cleaned = _TRAILING_RE.sub("", cleaned)
    return cleaned


def is_safe_segment(name: str) -> bool:
    """Return True if *name* contains no illegal path characters."""
    return _ILLEGAL_RE.search(name) is None and _TRAILING_RE.search(name) is None


def build_subject_dir(
    library_root: Path,
    experiment: str,
    date: datetime.date,
    subject: str,
) -> Path:
    """Build the canonical path for a subject directory.

    Args:
        library_root: Root of the media library.
        experiment:   Experiment name (will be sanitized).
        date:         Session date.
        subject:      Subject / individual ID (will be sanitized).

    Returns:
        ``library_root / sanitize(experiment) / YYYY-MM-DD / sanitize(subject)``
    """
    return (
        library_root
        / sanitize(experiment)
        / date.isoformat()
        / sanitize(subject)
    )


def build_view_path(
    library_root: Path,
    experiment: str,
    date: datetime.date,
    subject: str,
    view_name: str,
    ext: str,
) -> Path:
    """Build the full path for a single view video file.

    Args:
        library_root: Root of the media library.
        experiment:   Experiment name.
        date:         Session date.
        subject:      Subject / individual ID.
        view_name:    View display name (will be sanitized).
        ext:          File extension **without** leading dot (e.g. ``"mp4"``).

    Returns:
        ``<subject_dir> / sanitize(view_name).<ext>``
    """
    base = build_subject_dir(library_root, experiment, date, subject)
    return base / f"{sanitize(view_name)}.{ext}"
