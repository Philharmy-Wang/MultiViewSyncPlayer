# 示例文件说明

## multiview_example.mvsp.json

动物行为多视角同步会话的示例文件（2×3 布局，6 个视角）。

### 使用方法

1. 将此文件中的 `videos/*.mp4` 路径替换为你实际的视频文件路径
2. 在多视角同步播放器中选择「文件 → 打开会话」或「📂 打开会话」按钮
3. 选择此 `.mvsp.json` 文件即可加载完整会话

### 字段说明

- `metadata`：会话元数据（实验名称、日期、被试编号等）
- `layout`：网格布局（行列数 + 各视角名称）
- `videos`：每个视角的视频路径和元信息
- `offsets`：每个视角相对于基准帧的帧偏移（用于同步对齐）
- `markers`：标记帧列表（记录关键时间点）

## animal_behavior_template.json

动物行为场景的元数据模板，包含 subject_id、species、date、experiment、operator、notes 字段。

在元数据编辑器中可一键加载此模板。
