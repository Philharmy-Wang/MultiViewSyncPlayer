"""Automated real-media Qt smoke for unlinked-view stepping semantics."""

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtWidgets import QApplication

from multiview_sync_player.layout_manager import LayoutConfig
from multiview_sync_player.main_window import MainWindow
from multiview_sync_player.session_io import SessionData
from multiview_sync_player.video_cell import VideoCell
from multiview_sync_player.video_decoder import (
    probe_keyframe_index, probe_video_metadata,
)


def wait_until(app, predicate, timeout=30.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.001)
    app.processEvents()
    return bool(predicate())


def image_health(cell):
    if cell._pixmap is None or cell._pixmap.isNull():
        return {"blank": True, "stddev": 0.0}
    image = cell._pixmap.toImage()
    values = []
    for y in range(0, image.height(), max(1, image.height() // 12)):
        for x in range(0, image.width(), max(1, image.width() // 20)):
            color = image.pixelColor(x, y)
            values.append((color.red(), color.green(), color.blue()))
    stddev = float(np.asarray(values).std())
    return {"blank": bool(stddev < 1.0), "stddev": round(stddev, 4)}


def validate(paths):
    app = QApplication.instance() or QApplication([])
    VideoCell.load_audio = lambda self, path: None
    names = [f"View{index}" for index in range(1, 7)]
    metadata = []
    preindex_started = time.perf_counter()
    for path in paths:
        info = probe_video_metadata(path)
        probe_keyframe_index(path, info["fps"])
        metadata.append(info)
    preindex_ms = (time.perf_counter() - preindex_started) * 1000.0
    cells = [{
        "view_name": name,
        "video_path": str(path),
        "total_frames": info["total_frames"],
        "fps": info["fps"],
        "has_audio": False,
        "offset": 0,
    } for name, path, info in zip(names, paths, metadata)]
    session = SessionData(
        cells=cells,
        layout={"rows": 2, "cols": 3, "view_names": names,
                "view_colors": ["#ff0000"] * 6},
        global_state={"offsets": {name: 0 for name in names},
                      "markers": [], "metadata": {}},
    )
    window = MainWindow(layout_config=LayoutConfig(
        rows=2, cols=3, view_names=names,
        view_colors=["#ff0000"] * 6))
    window.show()
    barrier_history = []
    real_begin = window._seek_barrier.begin

    def record_begin(base_frame, targets, retry_count=0):
        barrier_history.append({
            "base": base_frame, "participants": list(targets),
            "targets": dict(targets), "retry": retry_count,
        })
        return real_begin(base_frame, targets, retry_count)

    window._seek_barrier.begin = record_begin
    scenarios = []
    local_step_ms = []

    def wait_global(timeout=30.0):
        return wait_until(app, lambda: window._seek_barrier.active is None,
                          timeout)

    def local_step(name, delta):
        cell = window.cells[name]
        target = max(0, min(
            cell.local_frame + delta, max(0, cell.total_frames - 1)))
        started = time.perf_counter()
        cell._request_local_step(delta)
        ok = wait_until(app, lambda: cell.current_frame == target)
        return ok, (time.perf_counter() - started) * 1000.0, target

    try:
        window._apply_session_data(session)
        if not wait_until(
                app,
                lambda: len(window.cells) == 6
                and window._backend_init_complete
                and window._seek_barrier.active is None
                and all(cell._pixmap is not None
                        for cell in window.cells.values()),
                timeout=60.0):
            raise RuntimeError("six-view GUI initialization timeout")

        window.controller.seek_to(100)
        if not wait_global():
            raise RuntimeError("initial seek timeout")

        for delta in (1, -1):
            before = window.controller.base_frame
            window._step_frames(delta)
            ok = wait_global()
            scenarios.append({
                "name": f"all_linked_global_{delta:+d}", "pass": ok,
                "base_before": before,
                "base_after": window.controller.base_frame,
            })

        view1 = window.cells["View1"]
        unlink_frame = view1.current_frame
        view1._toggle_sync()
        wait_global()
        scenarios.append({
            "name": "unlink_view1_preserves_frame",
            "pass": view1.current_frame == view1.local_frame == unlink_frame,
            "frame": view1.current_frame,
        })

        others_before = {name: window.cells[name].current_frame
                         for name in names[1:]}
        for delta in [1] * 5 + [-1] * 5:
            ok, latency, target = local_step("View1", delta)
            local_step_ms.append(latency)
            scenarios.append({
                "name": f"view1_local_{delta:+d}", "pass": ok,
                "frame": target, "latency_ms": round(latency, 2),
            })
        scenarios.append({
            "name": "local_steps_leave_other_views_unchanged",
            "pass": all(window.cells[name].current_frame == frame
                        for name, frame in others_before.items()),
        })

        local_25 = {}
        for delta in (25, -25):
            ok, latency, target = local_step("View1", delta)
            local_25[f"{delta:+d}"] = round(latency, 2)
            scenarios.append({
                "name": f"view1_local_{delta:+d}", "pass": ok,
                "frame": target, "latency_ms": round(latency, 2),
            })

        fixed = view1.current_frame
        started = time.perf_counter()
        window._step_frames(25)
        global_25_ok = wait_global()
        global_25_ms = (time.perf_counter() - started) * 1000.0
        scenarios.append({
            "name": "global_+25_ignores_view1",
            "pass": global_25_ok and view1.current_frame == fixed,
            "view1_frame": view1.current_frame,
            "participants": barrier_history[-1]["participants"],
            "latency_ms": round(global_25_ms, 2),
        })

        relink_before = view1.current_frame
        expected_offset = relink_before - window.controller.base_frame
        view1._toggle_sync()
        relink_ok = wait_global()
        scenarios.append({
            "name": "relink_view1_preserves_frame",
            "pass": relink_ok and view1.current_frame == relink_before
                    and window.controller.offsets["View1"] == expected_offset,
            "frame_before": relink_before,
            "frame_after": view1.current_frame,
            "offset": window.controller.offsets["View1"],
        })

        local_targets = {}
        for name, delta in (("View1", 7), ("View4", -5)):
            window.cells[name]._toggle_sync()
            wait_global()
            ok, _, target = local_step(name, delta)
            local_targets[name] = target
            scenarios.append({"name": f"two_unlinked_{name}_step",
                              "pass": ok, "frame": target})
        window._step_frames(1)
        mixed_ok = wait_global()
        synced = [name for name in names if name not in local_targets]
        normalized = [window.cells[name].current_frame
                      - window.controller.offsets[name] for name in synced]
        scenarios.append({
            "name": "two_unlinked_global_group",
            "pass": mixed_ok
                    and all(window.cells[name].current_frame == target
                            for name, target in local_targets.items())
                    and max(normalized) - min(normalized) == 0,
            "participants": barrier_history[-1]["participants"],
            "strict_drift": max(normalized) - min(normalized),
        })
        for name, target in local_targets.items():
            window.cells[name]._toggle_sync()
            ok = wait_global()
            scenarios.append({
                "name": f"two_unlinked_relink_{name}",
                "pass": ok and window.cells[name].current_frame == target,
                "frame": window.cells[name].current_frame,
            })

        health = {name: image_health(cell)
                  for name, cell in window.cells.items()}
        return {
            "preindex_ms": round(preindex_ms, 2),
            "status": "PASS" if all(item["pass"] for item in scenarios)
                      and not any(item["blank"] for item in health.values())
                      else "FAIL",
            "scenarios": scenarios,
            "performance": {
                "single_local_step_ms_median": round(
                    statistics.median(local_step_ms), 2),
                "local_25_ms": local_25,
                "global_25_ms": round(global_25_ms, 2),
            },
            "image_health": health,
            "barrier_history": barrier_history,
        }
    finally:
        window._clear_all()
        window.close()
        app.processEvents()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    if len(args.source) != 6:
        parser.error("exactly six --source arguments are required")
    result = validate(args.source)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
