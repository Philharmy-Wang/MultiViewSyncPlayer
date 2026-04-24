"""multiview_sync_player.library.import_plan — Import plan data model, auto-detection, and preview.

Defines the complete intent for a single import operation (ImportPlan) and
provides utilities to batch-infer view directions / colours from source
file names.

Input:  list of source video paths, library root / experiment / date / subject metadata.
Output: ImportPlan with ViewMapping list, validation errors, ASCII preview.

Generated: 2026-04-23 21:00:00
"""

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .paths import build_subject_dir, sanitize
from .schema import ViewEntry
from .vocabulary import assign_color, parse_view_name

# ---------------------------------------------------------------------------
# 1. ViewMapping — per-file mapping decision
# ---------------------------------------------------------------------------


@dataclass
class ViewMapping:
    """单个源文件的映射决策。"""

    source: Path  # 原始视频绝对路径
    view_name: str  # 目标视角显示名（默认 = source.stem）
    direction: Optional[str] = None  # 标准方向 key
    index: Optional[int] = None  # 同方向编号
    color: Optional[str] = None  # HEX 颜色
    include: bool = True  # 是否纳入导入

    def target_basename(self) -> str:
        """目标文件基础名（不含扩展名），经 sanitize 处理。

        >>> from pathlib import Path
        >>> ViewMapping(Path('x.mp4'), '前/1').target_basename()
        '前_1'
        """
        return sanitize(self.view_name)

    def target_filename(self) -> str:
        """目标文件名 = sanitize(view_name) + 源文件扩展名。

        >>> from pathlib import Path
        >>> ViewMapping(Path('x.MP4'), '前-1').target_filename()
        '前-1.MP4'
        """
        return f"{sanitize(self.view_name)}{self.source.suffix}"

    def to_view_entry(self, relative_video_path: Path) -> ViewEntry:
        """转换为 schema.ViewEntry。

        Args:
            relative_video_path: 相对于库根的相对路径。

        >>> from pathlib import Path
        >>> vm = ViewMapping(Path('s.mp4'), '前-1', 'front', 1, '#42a5f5')
        >>> ve = vm.to_view_entry(Path('前-1.mp4'))
        >>> ve.name
        '前-1'
        """
        return ViewEntry(
            name=self.view_name,
            direction=self.direction,
            index=self.index,
            color=self.color,
            video_path=relative_video_path,
        )


# ---------------------------------------------------------------------------
# 2. ImportPlan — complete import intent
# ---------------------------------------------------------------------------


@dataclass
class ImportPlan:
    """一次完整导入的意图描述。"""

    library_root: Path  # 媒体库根目录（绝对路径）
    experiment: str  # 实验名称
    date: datetime.date  # 录制日期
    subject_id: str  # 个体 ID
    notes: str = ""  # 备注
    view_mappings: List[ViewMapping] = field(default_factory=list)  # 文件映射列表
    conflict_policy: str = "skip"  # 冲突策略: 'skip' / 'rename' / 'overwrite'
    copy_mode: str = "copy"  # 复制模式: 'copy' / 'hardlink' / 'move'

    def target_subject_dir(self) -> Path:
        """构造目标 subject 目录绝对路径。

        >>> import datetime
        >>> ImportPlan(Path('K:/lib'), 'Exp', datetime.date(2026,1,26), 's1').target_subject_dir()
        WindowsPath('K:/lib/Exp/2026-01-26/s1')
        """
        return build_subject_dir(
            self.library_root, self.experiment, self.date, self.subject_id
        )

    def target_mapping(self) -> List[Tuple[Path, Path]]:
        """返回 [(source, target_abs_path), ...]，仅 include=True 的项。

        >>> import datetime
        >>> vm = ViewMapping(Path('/src/f.mp4'), 'f')
        >>> plan = ImportPlan(Path('K:/lib'), 'Exp', datetime.date(2026,1,26), 's1', view_mappings=[vm])
        >>> plan.target_mapping()[0][1].name
        'f.mp4'
        """
        base = self.target_subject_dir()
        result: List[Tuple[Path, Path]] = []
        for m in self.view_mappings:
            if m.include:
                result.append((m.source, base / m.target_filename()))
        return result

    def validate(self) -> List[str]:
        """校验 plan，返回问题列表（空 = 无问题）。

        >>> import datetime
        >>> ImportPlan(Path('rel'), '', datetime.date(2026,1,26), 's').validate()  # doctest: +ELLIPSIS
        ['library_root 必须是绝对路径', 'experiment 不能为空']
        """
        errors: List[str] = []

        if not self.library_root.is_absolute():
            errors.append("library_root 必须是绝对路径")

        if not self.experiment or not self.experiment.strip():
            errors.append("experiment 不能为空")
        elif not sanitize(self.experiment):
            errors.append("experiment 经 sanitize 后为空")

        if not self.subject_id or not self.subject_id.strip():
            errors.append("subject_id 不能为空")
        elif not sanitize(self.subject_id):
            errors.append("subject_id 经 sanitize 后为空")

        included = [m for m in self.view_mappings if m.include]
        if not included:
            errors.append("view_mappings 中没有 include=True 的项")

        # Duplicate target filenames
        seen: dict[str, Path] = {}
        for m in included:
            fname = m.target_filename()
            if fname in seen:
                errors.append(f"目标文件名重复: {fname}（{seen[fname]} 与 {m.source}）")
            else:
                seen[fname] = m.source

        # Source existence
        for m in included:
            if not m.source.exists():
                errors.append(f"源文件不存在: {m.source}")

        return errors


# ---------------------------------------------------------------------------
# 3. autodetect_view_mappings — batch auto-detect
# ---------------------------------------------------------------------------


def autodetect_view_mappings(
    sources: List[Path],
    taken_colors: Iterable[str] = (),
) -> List[ViewMapping]:
    """批量从源文件名推断视角方向和颜色。

    对每个 source 依次执行:
    1. view_name = source.stem
    2. (direction, index) = parse_view_name(stem)
    3. color = assign_color(direction, index, taken_colors ∪ 已分配)
    4. include = True

    >>> from pathlib import Path
    >>> ms = autodetect_view_mappings([Path('/tmp/前-1.mp4')])
    >>> ms[0].direction
    'front'
    >>> ms[0].index
    1
    """
    assigned: list[str] = list(taken_colors)
    result: List[ViewMapping] = []

    for src in sources:
        stem = src.stem
        direction, index = parse_view_name(stem)
        color = assign_color(direction, index, assigned)
        assigned.append(color)
        result.append(
            ViewMapping(
                source=src,
                view_name=stem,
                direction=direction,
                index=index,
                color=color,
                include=True,
            )
        )

    return result


# ---------------------------------------------------------------------------
# 4. render_plan_preview — ASCII tree preview
# ---------------------------------------------------------------------------


def render_plan_preview(plan: ImportPlan, include_excluded: bool = False) -> str:
    """渲染 ImportPlan 的 ASCII 目录树预览。

    >>> import datetime
    >>> from pathlib import Path
    >>> ms = [ViewMapping(Path('/a/前-1.mp4'), '前-1', 'front', 1, '#42a5f5')]
    >>> plan = ImportPlan(Path('K:/library'), 'Exp', datetime.date(2026,1,26), 's1', view_mappings=ms)
    >>> 'Exp' in render_plan_preview(plan)
    True
    """
    lines: List[str] = []

    # Root line
    lines.append(f"{plan.library_root.as_posix()}/")

    # Tree branch characters
    exp_line = f"└── {sanitize(plan.experiment)}/"
    date_line = f"    └── {plan.date.isoformat()}/"
    subj_line = f"        └── {sanitize(plan.subject_id)}/"
    lines.append(exp_line)
    lines.append(date_line)
    lines.append(subj_line)

    mappings = plan.view_mappings
    if include_excluded:
        shown = mappings
    else:
        shown = [m for m in mappings if m.include]

    n = len(shown)
    for i, m in enumerate(shown):
        is_last = i == n - 1
        connector = "└──" if is_last else "├──"
        fname = m.target_filename()

        # Direction / index label
        if m.direction:
            dir_label = m.direction
            if m.index is not None:
                dir_label += f" #{m.index}"
        else:
            dir_label = "—"
            if m.index is not None:
                dir_label = f"#{m.index}"

        color_label = m.color or "—"
        excluded = "  [excluded]" if not m.include else ""
        src_label = f"← {m.source.name}"

        lines.append(
            f"            {connector} {fname}  ({dir_label}, {color_label})  {src_label}{excluded}"
        )

    return "\n".join(lines)
