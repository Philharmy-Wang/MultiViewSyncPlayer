import os
from pathlib import Path

import cv2
import numpy as np
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def synthetic_videos(tmp_path_factory):
    """Create three deterministic 25 FPS videos with machine-visible frames."""
    root = tmp_path_factory.mktemp("mvsp_synthetic")
    paths = {}
    width, height, fps, total = 320, 180, 25.0, 180
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    for camera_index, camera in enumerate(("camA", "camB", "camC")):
        path = root / f"{camera}.avi"
        writer = cv2.VideoWriter(
            str(path), fourcc, fps, (width, height))
        assert writer.isOpened()
        for frame_index in range(total):
            # The full-frame color encodes both camera and frame index.
            color = (
                (frame_index * 17 + camera_index * 31) % 256,
                (frame_index * 29 + camera_index * 47) % 256,
                (frame_index * 43 + camera_index * 59) % 256,
            )
            frame = np.full((height, width, 3), color, dtype=np.uint8)
            cv2.putText(
                frame, f"{camera} F{frame_index:04d}", (12, 72),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
                cv2.LINE_AA)
            cv2.putText(
                frame, f"T={frame_index / fps:07.3f}s", (12, 116),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2,
                cv2.LINE_AA)
            writer.write(frame)
        writer.release()
        paths[camera] = Path(path)
    return paths

