from PySide6.QtGui import QPixmap

from multiview_sync_player.video_cell import VideoDisplay


def test_same_pixmap_does_not_invalidate_scaled_cache(qtbot):
    display = VideoDisplay()
    qtbot.addWidget(display)
    pixmap = QPixmap(320, 180)
    display.set_pixmap(pixmap)
    cached = QPixmap(160, 90)
    display._cached_scaled = cached
    display._cached_size = (320, 180)

    display.set_pixmap(pixmap)
    assert display._cached_scaled.cacheKey() == cached.cacheKey()
