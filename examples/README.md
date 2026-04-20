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

## 项目模板示例

项目模板（`.mvsp.project.json`）描述视频目录的命名规则，工具可自动扫描并按规则分组加载。

使用方式：菜单「文件 → 从项目模板加载」→ 选择模板文件 → 浏览器中选一组 → 加载到会话。

### three_chamber_1.26.mvsp.project.json

三箱实验 1.26 数据（正面笼2 + 正面笼3 + 顶部监控，三视角）。

按 `subject_id`（猕猴编号）分组，每个个体自动匹配三个视角的视频文件。

### three_chamber_1.28.mvsp.project.json

三箱实验 1.28 数据（顶部 Cam2 + Cam3 + Cam4，三机位）。

按 `subject_id` 分组，文件名带 `jk` 或 `jk-` 后缀。

### 自定义模板

可按相同格式创建自己的项目模板：

1. `patterns` 中每个视角定义一个文件名正则（使用 `(?P<name>...)` 命名组）
2. `group_by` 指定命名组名（如 `subject_id`），扫描结果按此字段分组
3. `layout` 指定网格行列数
4. `metadata_template` 指定默认元数据字段
