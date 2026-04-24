"""multiview_sync_player.library.vocabulary — View direction vocabulary, color assignment, and CJK/English alias mapping.

Provides:
- Normalization of arbitrary direction strings to 6 standard directions.
- Parsing of view names into (direction, index) tuples.
- Automatic colour assignment per direction with collision avoidance.

Input:  raw direction / view name strings from user input or file names.
Output: standardised direction keys, parsed tuples, HEX colour strings.

Generated: 2026-04-23 20:30:00
"""

import colorsys
import re
from typing import Dict, Iterable, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. Six canonical directions
# ---------------------------------------------------------------------------

DIRECTIONS = ("front", "back", "left", "right", "top", "bottom")

# ---------------------------------------------------------------------------
# 2. Alias table (all lowercase, input should be .lower().strip() before lookup)
# ---------------------------------------------------------------------------

DIRECTION_ALIASES: Dict[str, str] = {
    # Chinese
    "前": "front", "前面": "front", "正面": "front",
    "后": "back", "后面": "back", "背面": "back",
    "左": "left", "左面": "left", "左侧": "left",
    "右": "right", "右面": "right", "右侧": "right",
    "上": "top", "上面": "top", "顶": "top", "顶面": "top", "俯视": "top",
    "下": "bottom", "下面": "bottom", "底": "bottom", "底面": "bottom", "仰视": "bottom",
    # English abbreviations
    "f": "front", "fr": "front",
    "b": "back", "bk": "back", "rear": "back",
    "l": "left",
    "r": "right",
    "t": "top", "up": "top",
    "d": "bottom", "down": "bottom", "bot": "bottom",
}

# ---------------------------------------------------------------------------
# 3. Direction → Chinese display label
# ---------------------------------------------------------------------------

DIRECTION_LABELS_ZH: Dict[str, str] = {
    "front": "前", "back": "后", "left": "左",
    "right": "右", "top": "上", "bottom": "下",
}

# ---------------------------------------------------------------------------
# 4. Direction → default colour (HEX)
# ---------------------------------------------------------------------------

DIRECTION_COLORS: Dict[str, str] = {
    "front": "#42a5f5",   # 蓝
    "back": "#66bb6a",    # 绿
    "left": "#ffa726",    # 橙
    "right": "#ab47bc",   # 紫
    "top": "#ef5350",     # 红
    "bottom": "#26a69a",  # 青
}

# ---------------------------------------------------------------------------
# 5. Fallback palette (distinct from direction colours)
# ---------------------------------------------------------------------------

_PALETTE_FALLBACK = [
    "#78909c", "#8d6e63", "#d4e157", "#ff7043",
    "#5c6bc0", "#26c6da", "#ec407a", "#9ccc65",
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Build a sorted list of alias keys by length (longest first) for substring scan
_SORTED_ALIASES = sorted(DIRECTION_ALIASES.keys(), key=len, reverse=True)


def _hex_to_hsl(hex_color: str) -> Tuple[float, float, float]:
    """Convert ``#rrggbb`` to (h, s, l) with h in [0,360), s/l in [0,1]."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return colorsys.rgb_to_hls(r, g, b)  # returns (h, l, s)


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """Convert (h, l, s) back to ``#rrggbb``.  *Note*: colorsys uses HLS order."""
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _perturb_color(hex_color: str, index: int) -> str:
    """Shift saturation/lightness of *hex_color* based on *index* (≥1)."""
    h, l, s = _hex_to_hsl(hex_color)
    # Alternate lightness shifts
    shift = 0.12 * (index - 1)
    l_new = max(0.2, min(0.85, l + shift * (1 if index % 2 else -1)))
    return _hsl_to_hex(h, s, l_new)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_direction(text: str) -> Optional[str]:
    """Normalise an arbitrary string to one of the 6 canonical directions.

    Matching order:
    1. Exact match against ``DIRECTIONS`` (case-insensitive).
    2. Exact match against ``DIRECTION_ALIASES``.
    3. Substring scan — check if any alias appears inside *text*.

    Returns ``None`` if the direction cannot be identified.

    >>> normalize_direction('前')
    'front'
    >>> normalize_direction('Front')
    'front'
    >>> normalize_direction('cam') is None
    True
    """
    if not text:
        return None
    key = text.lower().strip()

    # Rule 1: exact canonical
    if key in DIRECTIONS:
        return key

    # Rule 2: exact alias
    if key in DIRECTION_ALIASES:
        return DIRECTION_ALIASES[key]

    # Rule 3: substring scan
    for alias in _SORTED_ALIASES:
        if alias in key:
            return DIRECTION_ALIASES[alias]

    return None


# Regex: separate a leading textual prefix from an optional trailing number
_VIEW_RE = re.compile(r"^(.*?)[-_]?(\d+)$")
# Camera-style patterns: cam03, camera01, CAM5 …
_CAM_RE = re.compile(r"^[a-zA-Z_]+?0*(\d+)$")


def parse_view_name(name: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract ``(direction, index)`` from a view name string.

    Supported examples::

        >>> parse_view_name('前-1')
        ('front', 1)
        >>> parse_view_name('前1')
        ('front', 1)
        >>> parse_view_name('front-2')
        ('front', 2)
        >>> parse_view_name('front_3')
        ('front', 3)
        >>> parse_view_name('top')
        ('top', None)
        >>> parse_view_name('左')
        ('left', None)
        >>> parse_view_name('cam03')
        (None, 3)
        >>> parse_view_name('随便起的')
        (None, None)
    """
    if not name:
        return (None, None)

    m = _VIEW_RE.match(name)
    if m:
        prefix, num_str = m.group(1), m.group(2)
        index = int(num_str) if num_str else None
        direction = normalize_direction(prefix) if prefix else None
        return (direction, index)

    # No trailing number — try to parse direction from the whole string
    direction = normalize_direction(name)
    if direction is not None:
        return (direction, None)

    # Camera-style name (cam03, camera01)
    cm = _CAM_RE.match(name)
    if cm:
        return (None, int(cm.group(1)))

    return (None, None)


def assign_color(
    direction: Optional[str],
    index: Optional[int],
    taken: Iterable[str] = (),
) -> str:
    """Assign a HEX colour to a view, avoiding colours already in *taken*.

    >>> assign_color('front', 1, taken=[])
    '#42a5f5'

    Args:
        direction: Canonical direction key or ``None``.
        index:     Camera index within the direction (1-based).
        taken:     Iterable of HEX colours already in use.
    """
    taken_set = set(taken)

    if direction is not None and direction in DIRECTION_COLORS:
        base = DIRECTION_COLORS[direction]
        if base not in taken_set:
            return base
        # Colour taken — perturb based on index
        idx = index if index is not None else 2
        for attempt in range(1, 10):
            candidate = _perturb_color(base, idx + attempt)
            if candidate not in taken_set:
                return candidate
        # Fallback: return perturbed anyway
        return _perturb_color(base, idx)

    # No direction — cycle through fallback palette
    for colour in _PALETTE_FALLBACK:
        if colour not in taken_set:
            return colour

    # All taken — perturb the first fallback colour
    return _perturb_color(_PALETTE_FALLBACK[0], len(taken_set))
