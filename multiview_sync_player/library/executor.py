"""multiview_sync_player.library.executor — Execute an ImportPlan to disk.

Copies / hardlinks / moves source videos into the canonical library
directory structure and writes a ``_meta.json`` per subject.

Input:  ImportPlan (from import_wizard or constructed manually).
Output: ImportResult with success/skip/fail lists + _meta.json on disk.

Generated: 2026-04-23 23:00:00
"""

import datetime
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .import_plan import ImportPlan

# ---------------------------------------------------------------------------
# Progress callback protocol
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[int, int, Path], None]
# (current_index_1_based, total, current_source_path)

# ---------------------------------------------------------------------------
# ImportResult
# ---------------------------------------------------------------------------


@dataclass
class ImportResult:
    """执行结果汇总。"""

    successes: List[Tuple[Path, Path]] = field(default_factory=list)
    # (src_abs, tgt_abs) —— 已成功落盘
    skipped: List[Tuple[Path, Path, str]] = field(default_factory=list)
    # (src_abs, tgt_abs, reason)
    failed: List[Tuple[Path, Path, str]] = field(default_factory=list)
    # (src_abs, tgt_abs, error_msg)
    hardlink_fallbacks: List[Tuple[Path, Path]] = field(default_factory=list)
    # hardlink 降级到 copy 的记录
    meta_path: Optional[Path] = None
    dry_run: bool = False

    def summary(self) -> str:
        """返回一行汇总。"""
        return (
            f"成功 {len(self.successes)} / "
            f"跳过 {len(self.skipped)} / "
            f"失败 {len(self.failed)}"
        )


# ---------------------------------------------------------------------------
# ImportExecutor
# ---------------------------------------------------------------------------


class ImportExecutor:
    """执行 ImportPlan，落盘 + 写 _meta.json。"""

    def __init__(
        self,
        plan: ImportPlan,
        on_progress: Optional[ProgressCallback] = None,
    ):
        self.plan = plan
        self.on_progress = on_progress

    # -- public API --------------------------------------------------------

    def run(self, dry_run: bool = False) -> ImportResult:
        """完整执行流程。

        Args:
            dry_run: True 时只记录不写盘。
        """
        result = ImportResult(dry_run=dry_run)

        # 1. Validate
        errs = self.plan.validate()
        if errs:
            for e in errs:
                result.failed.append((Path("."), Path("."), f"validate: {e}"))
            return result

        mappings = self.plan.view_mappings
        total = len(mappings)

        # Build target path for each mapping
        base = self.plan.target_subject_dir()

        # 2. Create directories
        if not dry_run:
            base.mkdir(parents=True, exist_ok=True)

        # 3. Process each file
        # Track (mapping, tgt) for _write_meta
        success_mappings: List[Tuple[object, Path]] = []
        for i, m in enumerate(mappings, 1):
            src = m.source
            tgt = base / m.target_filename()

            # Excluded
            if not m.include:
                result.skipped.append((src, tgt, "excluded"))
                if self.on_progress:
                    self.on_progress(i, total, src)
                continue

            # Conflict resolution
            actual_tgt, skip_reason = self._resolve_conflict(
                tgt, self.plan.conflict_policy, dry_run
            )
            if skip_reason:
                result.skipped.append((src, tgt, skip_reason))
                if self.on_progress:
                    self.on_progress(i, total, src)
                continue

            # Copy / hardlink / move
            if dry_run:
                result.successes.append((src, actual_tgt))
                success_mappings.append((m, actual_tgt))
            else:
                try:
                    fallback = self._copy_one(src, actual_tgt, self.plan.copy_mode)
                    result.successes.append((src, actual_tgt))
                    success_mappings.append((m, actual_tgt))
                    if fallback:
                        result.hardlink_fallbacks.append((src, actual_tgt))
                except RuntimeError as exc:
                    result.failed.append((src, actual_tgt, str(exc)))

            if self.on_progress:
                self.on_progress(i, total, src)

        # 4. Write _meta.json
        if not dry_run and result.successes:
            self._write_meta(success_mappings, result)

        return result

    # -- internal helpers --------------------------------------------------

    def _copy_one(self, src: Path, tgt: Path, mode: str) -> bool:
        """执行文件操作。返回 True 表示发生了 hardlink→copy 降级。

        Raises:
            RuntimeError: 操作失败。
        """
        fallback = False
        try:
            if mode == "copy":
                shutil.copy2(src, tgt)
            elif mode == "hardlink":
                try:
                    os.link(src, tgt)
                except OSError:
                    shutil.copy2(src, tgt)
                    fallback = True
            elif mode == "move":
                shutil.move(str(src), str(tgt))
            else:
                raise RuntimeError(f"unknown copy_mode: {mode}")
        except Exception as exc:
            raise RuntimeError(f"{mode} failed: {exc}") from exc
        return fallback

    def _resolve_conflict(
        self, tgt: Path, policy: str, dry_run: bool
    ) -> Tuple[Optional[Path], Optional[str]]:
        """返回 (actual_tgt, skip_reason)；skip_reason 非 None 表示跳过。"""
        exists = tgt.exists()
        if not exists:
            return (tgt, None)

        if policy == "skip":
            return (tgt, "conflict_skip")
        elif policy == "rename":
            stem = tgt.stem
            suffix = tgt.suffix
            parent = tgt.parent
            idx = 1
            while True:
                candidate = parent / f"{stem}_{idx}{suffix}"
                if not candidate.exists():
                    return (candidate, None)
                idx += 1
        elif policy == "overwrite":
            if not dry_run:
                tgt.unlink()
            return (tgt, None)
        else:
            return (tgt, f"conflict_unknown_policy:{policy}")

    def _write_meta(
        self,
        success_mappings: List[Tuple[object, Path]],
        result: ImportResult,
    ) -> None:
        """在 subject_dir 写 _meta.json。"""
        subject_dir = self.plan.target_subject_dir()
        views = []
        for m, tgt in success_mappings:
            views.append({
                "name": m.view_name,
                "direction": m.direction,
                "index": m.index,
                "color": m.color,
                "video": tgt.name,
                "imported_from": str(m.source),
                "notes": getattr(m, "notes", ""),
            })

        meta = {
            "schema_version": 1,
            "experiment": self.plan.experiment,
            "date": self.plan.date.isoformat(),
            "subject_id": self.plan.subject_id,
            "notes": self.plan.notes,
            "imported_at": datetime.datetime.now().astimezone().isoformat(),
            "views": views,
        }

        meta_path = subject_dir / "_meta.json"
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result.meta_path = meta_path
