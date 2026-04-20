"""
multiview_sync_player.project_template — 项目模板数据类与扫描引擎

按文件名正则规则扫描视频目录，按 group_by 字段聚合为分组。
"""

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional


@dataclass
class ViewPattern:
    """单个视角的匹配规则。"""
    view_name: str
    view_color: str = "#42a5f5"
    pattern: str = ""           # 文件名正则，命名组对应 group_by 字段
    subdirectory: str = ""      # 相对 root_dir 的子目录

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class GroupEntry:
    """扫描结果中的一个分组。"""
    keys: Dict[str, str]                            # e.g. {'subject_id': '24332'}
    videos: Dict[str, str] = field(default_factory=dict)   # view_name -> abs path
    missing_views: List[str] = field(default_factory=list)

    @property
    def complete(self):
        return len(self.missing_views) == 0

    @property
    def display_key(self):
        return " | ".join(f"{k}={v}" for k, v in self.keys.items())


@dataclass
class ProjectTemplate:
    """项目模板：描述目录结构和匹配规则。"""
    name: str
    description: str = ""
    root_dir: str = ""
    group_by: List[str] = field(default_factory=lambda: ["subject_id"])
    patterns: List[ViewPattern] = field(default_factory=list)
    layout_rows: int = 2
    layout_cols: int = 2
    metadata_template: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "format": "mvsp.project",
            "version": "1.0",
            "name": self.name,
            "description": self.description,
            "root_dir": self.root_dir,
            "group_by": list(self.group_by),
            "patterns": [p.to_dict() for p in self.patterns],
            "layout": {"rows": self.layout_rows, "cols": self.layout_cols},
            "metadata_template": dict(self.metadata_template),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectTemplate":
        layout = d.get("layout", {})
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            root_dir=d.get("root_dir", ""),
            group_by=d.get("group_by", ["subject_id"]),
            patterns=[ViewPattern.from_dict(p) for p in d.get("patterns", [])],
            layout_rows=layout.get("rows", 2),
            layout_cols=layout.get("cols", 2),
            metadata_template=d.get("metadata_template", {}),
        )

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "ProjectTemplate":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def scan(self, root_override=None) -> List[GroupEntry]:
        """扫描目录，按 group_by 聚合所有匹配到的视频。"""
        root = Path(root_override or self.root_dir)
        if not root.exists() or not root.is_dir():
            return []

        all_view_names = [p.view_name for p in self.patterns]
        groups: Dict[Tuple[str, ...], Dict[str, str]] = {}

        for vp in self.patterns:
            try:
                regex = re.compile(vp.pattern)
            except re.error:
                continue
            search_dir = root / vp.subdirectory if vp.subdirectory else root
            if not search_dir.exists():
                continue
            for entry in search_dir.iterdir():
                if not entry.is_file():
                    continue
                m = regex.match(entry.name)
                if not m:
                    continue
                try:
                    key_values = tuple(m.group(k) for k in self.group_by)
                except (IndexError, re.error):
                    continue
                if not all(key_values):
                    continue
                groups.setdefault(key_values, {})[vp.view_name] = str(entry.resolve())

        result = []
        for key_tuple in sorted(groups.keys()):
            key_dict = dict(zip(self.group_by, key_tuple))
            view_map = groups[key_tuple]
            missing = [v for v in all_view_names if v not in view_map]
            result.append(GroupEntry(
                keys=key_dict, videos=view_map, missing_views=missing))
        return result
