"""Playback backend capability detection and safety-gated selection."""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BackendCapability:
    available: bool
    embedded_render: bool
    wayland_native: bool
    frame_accuracy_verified: bool
    reason: str = ""
    properties: tuple[str, ...] = (
        "time-pos", "estimated-frame-number", "decoder-frame-drop-count",
        "vo-drop-frame-count", "hwdec-current", "video-codec",
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BackendDecision:
    requested: str
    active: str
    mode: str
    reason: str
    capability: BackendCapability


def _import_mpv():
    import mpv
    return mpv


def detect_mpv_capability() -> BackendCapability:
    """Inspect python-mpv/libmpv availability without creating a player."""

    try:
        _import_mpv()
    except (ImportError, OSError) as exc:
        return BackendCapability(
            False, False, False, False,
            f"libmpv unavailable: {type(exc).__name__}: {exc}")
    wayland = (
        sys.platform.startswith("linux")
        and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland")
    has_xwayland = bool(os.environ.get("DISPLAY"))
    embedded = not wayland or has_xwayland
    reason = ""
    if wayland and not has_xwayland:
        reason = "current wid embedding has no native Wayland render path"
    return BackendCapability(
        True, embedded, False, False, reason)


def choose_backend(requested: str) -> BackendDecision:
    """Select a backend while enforcing the frame-accuracy hard gate."""

    aliases = {"opencv": "precision", "mpv": "gpu"}
    requested = aliases.get((requested or "auto").lower(),
                            (requested or "auto").lower())
    if requested not in {"auto", "precision", "gpu"}:
        raise ValueError(f"unsupported backend: {requested}")
    capability = detect_mpv_capability()
    if requested == "precision":
        return BackendDecision(
            requested, "opencv", "Strict", "explicit Precision backend",
            capability)
    if requested == "gpu":
        if capability.available and capability.embedded_render:
            return BackendDecision(
                requested, "mpv", "GPU Prototype",
                "MPV prototype is not frame-accuracy certified", capability)
        return BackendDecision(
            requested, "opencv", "Strict",
            capability.reason or "MPV embedding unavailable", capability)
    # Auto may use MPV only after the exact-frame gate is actually recorded as
    # passing.  This build intentionally leaves that flag false until runtime
    # validation exists for the target host.
    if (capability.available and capability.embedded_render
            and capability.frame_accuracy_verified):
        return BackendDecision(
            requested, "mpv", "Strict", "verified MPV backend", capability)
    return BackendDecision(
        requested, "opencv", "Strict",
        capability.reason or "MPV has not passed the frame-accuracy gate",
        capability)


def frame_to_time(frame: int, fps: float) -> float:
    """Map a zero-based target frame to its nominal MPV timestamp."""

    if fps <= 0:
        raise ValueError("fps must be positive")
    return max(0, int(frame)) / float(fps)
