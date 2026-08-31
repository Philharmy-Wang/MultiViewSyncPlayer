"""Compare generation-safe HEVC seek results with clean linear references."""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multiview_sync_player.video_decoder import PrefetchDecoder


def qimage_array(image):
    image = image.convertToFormat(QImage.Format_RGB888)
    raw = np.frombuffer(image.bits(), dtype=np.uint8)
    rows = raw.reshape(image.height(), image.bytesPerLine())
    return rows[:, :image.width() * 3].reshape(image.height(), image.width(), 3)


def clean_references(path, targets, width=720):
    cap = cv2.VideoCapture(str(path))
    references = {}
    wanted = set(targets)
    index = 0
    while index <= max(wanted):
        ok, frame = cap.read()
        if not ok:
            break
        if index in wanted:
            height = int(frame.shape[0] * width / frame.shape[1])
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
            references[index] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        index += 1
    cap.release()
    return references


def wait_until(app, predicate, timeout=15.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.001)
    app.processEvents()
    return bool(predicate())


def validate(path):
    app = QCoreApplication.instance() or QCoreApplication([])
    sequence = [(100, -1), (125, -2), (100, -3)]
    sequence.extend((frame, -(frame - 96)) for frame in range(101, 121))
    sequence.extend([(120, 1), (145, 2)])
    references = clean_references(path, {frame for frame, _ in sequence})
    decoder = PrefetchDecoder(path, target_width=720, buffer_size=60)
    delivered = {}
    failures = []
    latest_request = [None]
    stale = [0]

    def ready(request_id, frame, image):
        if request_id != latest_request[0]:
            stale[0] += 1
        delivered[request_id] = (frame, image)

    decoder.frame_ready.connect(ready)
    decoder.frame_failed.connect(
        lambda request_id, frame, message: failures.append(
            {"request": request_id, "frame": frame, "message": message}))
    decoder.start()
    checks = []
    try:
        for index, (target, request_id) in enumerate(sequence):
            latest_request[0] = request_id
            decoder.request_frame(target, request_id)
            # The +1 x20 burst intentionally waits only for the final request.
            if 3 <= index < 22:
                continue
            if not wait_until(
                    app,
                    lambda rid=request_id, frame=target:
                    rid in delivered and delivered[rid][0] == frame):
                checks.append({"target": target, "request": request_id,
                               "timeout": True})
                continue
            image = delivered[request_id][1]
            actual = qimage_array(image)
            reference = references[target]
            mad = float(np.abs(
                actual.astype(np.int16) - reference.astype(np.int16)).mean())
            checks.append({
                "target": target,
                "request": request_id,
                "mad_vs_linear_reference": round(mad, 4),
                "stddev": round(float(actual.std()), 4),
                "blank": bool(actual.std() < 1.0),
                "gray": bool(
                    np.abs(actual.max(axis=2).astype(np.int16)
                           - actual.min(axis=2)).mean() < 1.0
                    and np.abs(reference.max(axis=2).astype(np.int16)
                               - reference.min(axis=2)).mean() >= 1.0),
                "corrupt": bool(mad > 1.0),
            })
    finally:
        decoder.stop()

    completed = [item for item in checks if not item.get("timeout")]
    return {
        "path": str(path),
        "scenarios": checks,
        "gray": sum(bool(item.get("gray")) for item in completed),
        "corrupt": sum(bool(item.get("corrupt")) for item in completed),
        "blank": sum(bool(item.get("blank")) for item in completed),
        "stale": stale[0],
        "decoder_failures": failures,
        "metrics": decoder.metrics(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = validate(args.path)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")


if __name__ == "__main__":
    main()
