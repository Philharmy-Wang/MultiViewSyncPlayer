# MultiViewSyncPlayer（MVSP）

多机位视频同步对齐与浏览工具 · PySide6 · MIT · 中英双语

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 核心特性

- 一键导入：实验 / 日期 / 个体 / 视角 四级自动归档
- 左侧媒体库：树形浏览，双击个体即刻加载全部视角
- 同步播放：环形缓冲预解码，丝滑到毫秒级
- 自动布局：视角数自动匹配窗口（1~30+ 路）
- 会话保存：`.mvsp.json` 保留偏移/标注，跨机迁移
- 帧偏移精调：逐帧 / 10帧 / 100帧微调，一键锁定同步
- 标注系统：快捷键标记关键帧，导出标注列表
- 波形预览：音频波形可视化辅助对齐拍板声
- 中英 UI 切换 / MIT 许可

## 截图

<!-- 占位：截图后补 -->
| 主窗口 | 导入向导 | 媒体库浏览器 |
|---|---|---|
| ![主窗口](docs/screenshots/main_window.png) | ![导入向导](docs/screenshots/import_wizard.png) | ![媒体库](docs/screenshots/library_browser.png) |

## 快速开始

### 方式 A：一键脚本（推荐）

**Windows：** 双击 `install.bat`

**macOS / Linux：**
```bash
bash install.sh
./run.sh
```

### 方式 B：手动安装

```bash
git clone https://github.com/Philharmy-Wang/MultiViewSyncPlayer.git
cd MultiViewSyncPlayer
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

### 方式 C：CLI 参数

```bash
# 打开指定会话
python run.py --session my_session.mvsp.json

# 启动时打开媒体库
python run.py --library /path/to/library_root

# 选择后端
python run.py --backend mpv    # 或 opencv（默认）
```

## 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10/11, Ubuntu 20.04+, macOS 12+ |
| Python | 3.9 / 3.10 / 3.11 / 3.12 |
| 显卡 | 可选；无独显也能流畅播放 1080p x6 |
| 内存 | >= 8 GB（多路 4K 建议 >= 16 GB） |
| 依赖 | PySide6 >= 6.6, OpenCV-Python >= 4.8, NumPy >= 1.24, SciPy >= 1.10 |

## 环境配置详解

### Windows

- Python 来源推荐：[python.org](https://www.python.org/downloads/) 官方 / Microsoft Store（64-bit）
- 安装时务必勾选 **Add Python to PATH**
- 如遇 `DLL load failed`：`pip install msvc-runtime` 或安装 [VC++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

### Ubuntu / Debian

```bash
sudo apt install python3-venv libxcb-cursor0 libgl1 libxkbcommon-x11-0
# Wayland 下如窗口异常：
export QT_QPA_PLATFORM=xcb
```

### macOS

- 建议用 Homebrew：`brew install python@3.11`
- Apple Silicon 无需额外配置

## 使用指南

### 1. 首次启动

启动向导中选布局预设（1x1 ~ 3x3）或自定义 NxM，命名视角。

### 2. 导入视频到库

顶部菜单 **文件 -> 导入视频到库** (`Ctrl+I`)：

1. 选库根目录（会自动创建/复用）
2. 拖入视频文件或整个文件夹
3. 填实验名 / 日期 / 个体 ID
4. 为每个文件指定视角（前/后/左/右/上/下 + 编号，可自定义）
5. 选复制 / 硬链接 / 移动，预览映射后开始导入

详细图文教程见 [docs/import_guide_zh.md](docs/import_guide_zh.md)。

### 3. 浏览与加载

左侧树形导航：**实验 -> 日期 -> 个体 -> 视角**

- 双击**个体节点** -> 该个体所有视频秒开，布局自动匹配视角数
- 双击**单个视角** -> 在空槽位打开

### 4. 同步对齐

1. 播放所有视频，找到同步声（拍板/关门声）
2. 选中某路视角，用 `<-` / `->` 键微调偏移
3. 按 `Space` 播放 / 暂停，确认同步效果
4. 点击锁定图标锁定同步

### 5. 保存与分享

`Ctrl+S` 保存为 `.mvsp.json` 文件。若视频来自媒体库，会话会自动附带 `library_ref` 引用。他人打开同一库可直接复现。

## 键盘快捷键

| 操作 | 快捷键 |
|---|---|
| 播放 / 暂停 | `Space` |
| 前/后一帧（全局） | `D` / `A` |
| 前/后 25 帧 | `W` / `S` |
| 前/后 250 帧 | `E` / `Q` |
| 选中视角微调偏移 | `<-` / `->`（+-1帧），`Shift+<-`（+-25），`Ctrl+<-`（+-250） |
| 跳到开头/结尾 | `Home` / `End` |
| 标记当前帧 | `M` |
| 重置所有偏移 | `R` |
| 选中视角 1~9 | `1` ~ `9` |
| 取消选择 | `0` / `Esc` |
| 全屏 | `F` / `F11` |
| 打开会话 | `Ctrl+O` |
| 保存会话 | `Ctrl+S` |
| 导入视频到库 | `Ctrl+I` |
| 显示/隐藏媒体库 | `Ctrl+L` |
| 显示/隐藏工具栏 | `Ctrl+T` |

## 媒体库目录规范

详见 [docs/library_spec.md](docs/library_spec.md)。

标准四层结构：

```
<library_root>/
├── library.mvsp-lib.json
├── ThreeChamber/              # 实验
│   └── 2026-01-26/           # 日期
│       ├── 24332/            # 个体
│       │   ├── _meta.json
│       │   ├── front-1.mp4
│       │   ├── back-1.mp4
│       │   └── ...
│       └── 24333/
└── OpenField/
```

## 常见问题

**Q: 导入后视频能删源文件吗？**
A: 选「移动」模式导入即可，或导入后手动删除。

**Q: 硬链接跨盘失败？**
A: NTFS/ext4 不支持跨卷硬链接，导入时会自动降级为复制。

**Q: 加载视频卡顿？**
A: 调小 `DECODE_TARGET_WIDTH`（设置 -> 高级），或改用 `--backend mpv` 后端。

**Q: 能否支持 >30 路？**
A: 原则上支持，但受内存与显卡带宽限制。建议 <= 16 路并降低分辨率。

**Q: 旧版 .mvsp.json 文件兼容吗？**
A: 完全兼容。v0.2 的会话加载器自动忽略新增的 `library_ref` 字段，不影响旧格式。

## 项目结构

```
multiview_sync_player/
├── __main__.py           # 入口（argparse）
├── main_window.py        # 主窗口 + 菜单
├── sync_controller.py    # 同步控制 + 偏移管理
├── video_cell.py         # 单视角格子（解码 + 渲染）
├── video_decoder.py      # OpenCV / MPV 后端
├── global_toolbar.py     # 全局工具栏
├── layout_manager.py     # 网格布局 + auto_grid
├── session_io.py         # 会话 I/O（save/load）
├── metadata.py           # 元数据容器
├── library/              # 媒体库模块
│   ├── schema.py         # 四层数据模型
│   ├── index.py          # LibraryIndex + scan
│   ├── browser.py        # 左侧 dock 树形浏览
│   ├── import_wizard.py  # 五页导入向导
│   ├── import_plan.py    # ImportPlan + autodetect
│   └── executor.py       # ImportExecutor（copy/link/move）
├── config.py             # 常量 + 配置
└── styles.py             # 暗色主题 QSS
```

## 贡献

欢迎 Issue 和 PR！请确保：

1. `pytest tests/` 全过
2. 新功能附带测试
3. 遵循现有代码风格

## 协议

[MIT License](LICENSE)

## 致谢

- [PySide6](https://www.qt.io/qt-for-python) — Qt for Python
- [OpenCV](https://opencv.org/) — 视频解码
- [mpv](https://mpv.io/) — 可选高性能后端
