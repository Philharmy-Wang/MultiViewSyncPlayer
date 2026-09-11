"""Measure real GUI session startup and child-process launches."""

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

SOURCE_ROOT = Path(os.environ.get(
    "MVSP_BENCH_SOURCE_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(SOURCE_ROOT))

from multiview_sync_player.main_window import MainWindow


def wait_until(app, predicate, timeout):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    return False


def benchmark(session, timeout=120):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    heartbeats = [0]
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeats.__setitem__(0, heartbeats[0] + 1))
    timer.start()

    running = True
    children = {}
    process = psutil.Process(os.getpid())

    def sample_children():
        while running:
            try:
                for child in process.children(recursive=True):
                    children[child.pid] = child.name().lower()
            except (psutil.Error, OSError):
                pass
            time.sleep(0.005)

    sampler = threading.Thread(target=sample_children, daemon=True)
    sampler.start()
    started = time.perf_counter()
    before_call_heartbeats = heartbeats[0]
    window._load_session(str(Path(session).resolve()))
    call_return_ms = (time.perf_counter() - started) * 1000
    call_heartbeats = heartbeats[0] - before_call_heartbeats

    first_ok = wait_until(
        app, lambda: any(cell._pixmap is not None
                        for cell in window.cells.values()), timeout)
    first_frame_ms = (time.perf_counter() - started) * 1000
    all_ok = wait_until(
        app, lambda: bool(window.cells) and window._backend_init_complete
        and window._seek_barrier.active is None
        and all(cell._pixmap is not None for cell in window.cells.values()),
        timeout)
    all_ready_ms = (time.perf_counter() - started) * 1000
    wait_until(app, lambda: not getattr(window, "_audio_loading_active", False), 2)
    gui_metrics = {
        name: cell.performance_metrics()
        for name, cell in window.cells.items()
        if hasattr(cell, "performance_metrics")
    }
    running = False
    sampler.join(timeout=1)
    timer.stop()
    window._clear_all()
    app.processEvents()
    names = list(children.values())
    result = {
        "source_root": str(SOURCE_ROOT),
        "session": str(Path(session).resolve()),
        "load_call_return_ms": round(call_return_ms, 2),
        "gui_heartbeats_during_load_call": call_heartbeats,
        "first_frame_ms": round(first_frame_ms, 2),
        "all_views_ready_ms": round(all_ready_ms, 2),
        "first_frame_ok": first_ok,
        "all_views_ready_ok": all_ok,
        "ffprobe_process_count": sum("ffprobe" in name for name in names),
        "ffmpeg_process_count": sum("ffmpeg" in name for name in names),
        "child_processes": sorted(set(names)),
        "initial_seek_barrier_ms": round(
            getattr(window, "_last_seek_latency_ms", 0.0), 3),
        "gui_metrics": gui_metrics,
    }
    try:
        from multiview_sync_player.media_cache import cache_metrics
        result["cache_metrics"] = cache_metrics()
    except ImportError:
        pass
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("session")
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    result = benchmark(args.session, args.timeout)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
