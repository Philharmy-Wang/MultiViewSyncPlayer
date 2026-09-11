"""PyInstaller Linux x86_64 onedir specification for v0.2.3-test.

Build natively on Linux. ffmpeg, ffprobe, and libmpv are system dependencies
in this first Linux prototype; Windows executables are never bundled.
"""

import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "packaging"
DIST_NAME = os.environ.get(
    "MVSP_DIST_NAME", "MultiViewSyncPlayer-v0.2.3-test-linux-x86_64")

a = Analysis(
    [str(PKG / "run_mvsp.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtSvg",
    ],
    excludes=["tkinter", "unittest", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="MultiViewSyncPlayer", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name=DIST_NAME,
)
