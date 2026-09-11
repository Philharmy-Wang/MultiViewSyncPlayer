"""PyInstaller Windows onedir specification for v0.2.3-test."""

import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "packaging"
DIST_NAME = os.environ.get(
    "MVSP_DIST_NAME", "MultiViewSyncPlayer-v0.2.3-test-win64")

a = Analysis(
    [str(PKG / "run_mvsp.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(PKG / "bin" / "ffmpeg.exe"), "bin"),
        (str(PKG / "bin" / "ffprobe.exe"), "bin"),
    ],
    hiddenimports=[
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtSvg",
    ],
    excludes=["tkinter", "unittest", "pytest", "IPython"],
    noarchive=False,
)
a.binaries = [
    entry for entry in a.binaries
    if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="MultiViewSyncPlayer", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    icon=str(PKG / "icons" / "mvsp.ico"),
    version=str(PKG / "version_info.txt"),
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name=DIST_NAME,
)
