# 文件: K:\MultiViewSyncPlayer\packaging\run_mvsp.py
# 功能: PyInstaller 入口 launcher,以包路径 import multiview_sync_player.__main__,
#       避免直接执行 __main__.py 时 __package__ 为空导致的相对 import 失败
# 输入: -
# 输出: -
# 运行指令: python packaging/run_mvsp.py(开发期) / 由 packaging/mvsp.spec 引用(打包期)
# 生成时间: 2026-04-27 17:50

import sys

from multiview_sync_player.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
