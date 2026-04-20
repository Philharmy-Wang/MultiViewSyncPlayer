"""
multiview_sync_player.styles — QSS stylesheet definitions
"""

from .config import (
    COLOR_WINDOW_BG, COLOR_PANEL_BG, COLOR_TEXT, COLOR_ACCENT,
    COLOR_BTN_NORMAL, COLOR_BTN_HOVER, COLOR_BTN_PRESSED,
)

DARK_THEME_QSS = f"""
QMainWindow {{
    background-color: {COLOR_WINDOW_BG};
}}
QWidget {{
    color: {COLOR_TEXT};
}}
QPushButton {{
    background-color: {COLOR_BTN_NORMAL};
    color: {COLOR_TEXT};
    border: 1px solid #555;
    border-radius: 4px;
    padding: 4px 10px;
    min-height: 24px;
    font-size: 10pt;
}}
QPushButton:hover {{
    background-color: {COLOR_BTN_HOVER};
    border-color: {COLOR_ACCENT};
}}
QPushButton:pressed {{
    background-color: {COLOR_BTN_PRESSED};
}}
QPushButton#btn_play {{
    min-height: 28px;
    font-weight: bold;
    padding: 4px 16px;
}}
QComboBox {{
    background-color: {COLOR_BTN_NORMAL};
    color: {COLOR_TEXT};
    border: 1px solid #555;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 24px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background-color: {COLOR_PANEL_BG};
    color: {COLOR_TEXT};
    selection-background-color: {COLOR_ACCENT};
}}
QStatusBar {{
    background-color: #1a1a1a;
    color: {COLOR_TEXT};
    font-size: 9pt;
}}
QLabel {{
    background: transparent;
}}
QSlider::groove:horizontal {{
    background: #3c3c3c;
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {COLOR_ACCENT};
    width: 12px;
    height: 12px;
    margin: -3px 0;
    border-radius: 6px;
}}
QSlider::sub-page:horizontal {{
    background: {COLOR_ACCENT};
    border-radius: 3px;
}}
"""

CELL_BTN_STYLE = (
    f"QPushButton {{ background: {COLOR_BTN_NORMAL}; color: {COLOR_TEXT}; "
    f"border: 1px solid #555; border-radius: 3px; "
    f"padding: 1px 4px; font-size: 9pt; min-height: 18px; }}"
    f"QPushButton:hover {{ background: {COLOR_BTN_HOVER}; }}"
    f"QPushButton:pressed {{ background: {COLOR_BTN_PRESSED}; }}"
)

SPEED_BTN_ACTIVE = (
    f"background: {COLOR_ACCENT}; color: white; "
    f"border: 1px solid {COLOR_ACCENT}; border-radius: 4px; "
    f"padding: 2px 4px; min-height: 20px;"
)

PROGRESS_SLIDER_STYLE = f"""
QSlider::groove:horizontal {{
    background: #3c3c3c;
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {COLOR_ACCENT};
    width: 10px;
    height: 10px;
    margin: -2px 0;
    border-radius: 5px;
}}
QSlider::sub-page:horizontal {{
    background: {COLOR_ACCENT};
    border-radius: 3px;
}}
"""
