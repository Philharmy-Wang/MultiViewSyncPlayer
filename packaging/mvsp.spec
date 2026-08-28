# 文件: K:\MultiViewSyncPlayer\packaging\mvsp.spec
# 功能: PyInstaller 配置 — onedir 模式 + 捆绑 ffmpeg/ffprobe + 自定义图标 + 文件版本元数据
# 输入: multiview_sync_player/__main__.py / packaging/bin/{ffmpeg,ffprobe}.exe / packaging/icons/mvsp.ico / packaging/version_info.txt
# 输出: dist/MultiViewSyncPlayer/(目录及内部文件)
# 运行指令: 从仓库根目录 python -m PyInstaller --clean --noconfirm packaging/mvsp.spec
# 生成时间: 2026-04-27 16:25

import os
from pathlib import Path

# SPECPATH 由 PyInstaller 注入,值为 spec 文件所在目录(即 packaging/)
ROOT = Path(SPECPATH).parent
PKG  = ROOT / "packaging"
DIST_NAME = os.environ.get("MVSP_DIST_NAME", "MultiViewSyncPlayer")

block_cipher = None

a = Analysis(
    [str(PKG / "run_mvsp.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(PKG / "bin" / "ffmpeg.exe"),  "bin"),
        (str(PKG / "bin" / "ffprobe.exe"), "bin"),
    ],
    hiddenimports=[
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtSvg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pytest", "IPython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Qt 6 links against the Windows system ICU (unversioned exports).  A foreign
# icuuc.dll found on PATH (for example, Poppler/OpenCV's ICU 78 build) shadows
# System32 in a frozen app and makes PySide6.QtWidgets fail with WinError 127.
a.binaries = [
    entry
    for entry in a.binaries
    if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}
]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MultiViewSyncPlayer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                                  # UPX 与 Qt DLL 配合常触发杀软误报
    console=False,                              # 无黑窗
    disable_windowed_traceback=False,
    icon=str(PKG / "icons" / "mvsp.ico"),
    version=str(PKG / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=DIST_NAME,
)
