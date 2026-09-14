"""Cross-platform child-process helpers used by media tooling.

All application-launched console programs go through this module so a frozen
Windows GUI never flashes a console window.  Non-Windows platforms receive no
Windows-only subprocess flags.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Sequence


def hidden_process_kwargs() -> dict[str, Any]:
    """Return safe platform-specific kwargs for a non-interactive child."""

    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "shell": False,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
        if startupinfo_factory is not None:
            startupinfo = startupinfo_factory()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = startupinfo
    return kwargs


def run_hidden(command: Sequence[str], **kwargs):
    """Run a child process without opening a Windows console window."""

    options = hidden_process_kwargs()
    options.update(kwargs)
    options["shell"] = False
    options.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(list(command), **options)


def popen_hidden(command: Sequence[str], **kwargs):
    """Start a child process without opening a Windows console window."""

    options = hidden_process_kwargs()
    options.update(kwargs)
    options["shell"] = False
    options.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.Popen(list(command), **options)
