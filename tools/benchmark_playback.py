"""Numeric OpenCV playback/seek benchmark for baseline and candidate code.

Run this script from the source tree being measured.  It intentionally adapts
to the v0.2.1 decoder API and the generation-aware decoder API so the same
workload can compare both revisions.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QCoreApplication

BENCH_SOURCE_ROOT = Path(os.environ.get(
    "MVSP_BENCH_SOURCE_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(BENCH_SOURCE_ROOT))

from multiview_sync_player.video_decoder import PrefetchDecoder


def wait_until(app, predicate, timeout):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.001)
    app.processEvents()
    return bool(predicate())


def benchmark(view_count, sources, duration, media_label):
    app = QCoreApplication.instance() or QCoreApplication([])
    decoders = [
        PrefetchDecoder(sources[index % len(sources)], target_width=720,
                        buffer_size=60)
        for index in range(view_count)
    ]
    delivered = [None] * view_count

    for index, decoder in enumerate(decoders):
        decoder.frame_ready.connect(
            lambda *args, i=index: delivered.__setitem__(i, int(args[-2])))

    generation = 0

    def request_all(frame):
        nonlocal generation
        generation += 1
        for index, decoder in enumerate(decoders):
            delivered[index] = None
            if hasattr(decoder, "request_frame"):
                decoder.request_frame(frame, generation)
            else:
                decoder.seek(frame)

    process = psutil.Process(os.getpid())
    process.cpu_percent(None)
    started = time.perf_counter()
    for decoder in decoders:
        decoder.start()
    request_all(0)
    first_ok = wait_until(
        app, lambda: all(frame == 0 for frame in delivered), 10.0)
    startup_ms = (time.perf_counter() - started) * 1000.0
    if not first_ok:
        raise RuntimeError("first-frame timeout")

    request_all(100)
    if not wait_until(app, lambda: all(frame == 100 for frame in delivered), 10.0):
        raise RuntimeError("warm-up seek timeout")

    started = time.perf_counter()
    request_all(101)
    if not wait_until(app, lambda: all(frame == 101 for frame in delivered), 10.0):
        raise RuntimeError("single-step timeout")
    step_ms = (time.perf_counter() - started) * 1000.0

    started = time.perf_counter()
    for frame in range(102, 112):
        request_all(frame)
    if not wait_until(app, lambda: all(frame == 111 for frame in delivered), 10.0):
        raise RuntimeError("rapid-step timeout")
    rapid_ms = (time.perf_counter() - started) * 1000.0

    started = time.perf_counter()
    request_all(300)
    if not wait_until(app, lambda: all(frame == 300 for frame in delivered), 10.0):
        raise RuntimeError("random-seek timeout")
    random_seek_ms = (time.perf_counter() - started) * 1000.0

    request_all(0)
    if not wait_until(app, lambda: all(frame == 0 for frame in delivered), 10.0):
        raise RuntimeError("playback reset timeout")
    for decoder in decoders:
        decoder.set_playing(True)

    strict_api = all(hasattr(decoder, "has_frame") for decoder in decoders)
    base = 0
    displayed = [0] * view_count
    misses = 0
    stalls = 0
    max_drift = 0
    interval = 1.0 / 25.0
    next_tick = time.perf_counter() + interval
    playback_started = time.perf_counter()
    cpu_samples = []
    rss_samples = []
    next_sample = playback_started + 0.2

    while time.perf_counter() - playback_started < duration:
        app.processEvents()
        now = time.perf_counter()
        if now >= next_sample:
            cpu_samples.append(process.cpu_percent(None))
            rss_samples.append(process.memory_info().rss)
            next_sample += 0.2
        if now < next_tick:
            time.sleep(min(0.001, next_tick - now))
            continue
        next_tick += interval
        target = base + 1

        if strict_api:
            if not all(decoder.has_frame(target) for decoder in decoders):
                stalls += 1
                continue
            images = [decoder.get_frame(target) for decoder in decoders]
            if any(image is None for image in images):
                stalls += 1
                continue
            base = target
            displayed = [target] * view_count
        else:
            base = target
            for index, decoder in enumerate(decoders):
                if decoder.get_frame(target) is None:
                    misses += 1
                else:
                    displayed[index] = target
        max_drift = max(max_drift, max(displayed) - min(displayed))

    playback_elapsed = time.perf_counter() - playback_started
    for decoder in decoders:
        decoder.set_playing(False)

    decoder_metrics = [
        decoder.metrics() for decoder in decoders
        if hasattr(decoder, "metrics")
    ]
    for decoder in decoders:
        decoder.stop()

    return {
        "views": view_count,
        "policy": "strict" if strict_api else "v0.2.1-independent",
        "resolution": media_label,
        "startup_latency_ms": round(startup_ms, 2),
        "first_frame_latency_ms": round(startup_ms, 2),
        "single_step_latency_ms": round(step_ms, 2),
        "rapid_step_x10_latency_ms": round(rapid_ms, 2),
        "random_seek_latency_ms": round(random_seek_ms, 2),
        "playback_effective_fps": round(base / playback_elapsed, 3),
        "cpu_percent_mean": round(sum(cpu_samples) / len(cpu_samples), 2)
        if cpu_samples else 0.0,
        "ram_mb_peak": round(max(rss_samples) / (1024 * 1024), 2)
        if rss_samples else 0.0,
        "individual_frame_misses": misses,
        "strict_stall_ticks": stalls,
        "max_inter_view_drift_frames": max_drift,
        "decoder_metrics": decoder_metrics,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--views", type=int, action="append", default=[])
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument(
        "--media-label",
        default="1920x1080 H.264 source / 720px decode")
    parser.add_argument("--output")
    args = parser.parse_args()
    view_counts = args.views or [2, 4, 6]
    results = [benchmark(count, args.source, args.duration, args.media_label)
               for count in view_counts]
    payload = {
        "python": sys.version,
        "source_root": str(BENCH_SOURCE_ROOT),
        "results": results,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
