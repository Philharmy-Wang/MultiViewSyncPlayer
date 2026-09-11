"""
multiview_sync_player.__main__ — Entry point

Usage:
    python -m multiview_sync_player
    python -m multiview_sync_player --session session.mvsp.json
    python -m multiview_sync_player --backend mpv
"""

import argparse
import locale
import sys


def main():
    locale.setlocale(locale.LC_NUMERIC, 'C')

    parser = argparse.ArgumentParser(
        description='Multi-view video synchronized playback & alignment tool')
    parser.add_argument('--session', type=str, default=None,
                        help='Open a saved .mvsp.json session file')
    parser.add_argument('--library', type=str, default=None,
                        help='Open a media library root directory on startup')
    parser.add_argument('--backend', default='auto',
                        choices=['auto', 'precision', 'gpu', 'opencv', 'mpv'],
                        help='Playback backend (default: auto; exact-frame gated)')
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication, QDialog
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MultiViewSyncPlayer")
    app.setOrganizationName("MultiViewSyncPlayer")
    app.setStyle('Fusion')

    from .main_window import MainWindow
    from pathlib import Path

    win = None

    if args.session:
        # Direct session load, skip LaunchDialog
        win = MainWindow(session_path=args.session, backend=args.backend)
        win.show()
    else:
        # Show LaunchDialog to pick grid size
        from .launch_dialog import LaunchDialog
        from .layout_manager import LayoutConfig
        dlg = LaunchDialog()
        if dlg.exec() == QDialog.Accepted:
            layout_cfg = LayoutConfig(rows=dlg.chosen_rows,
                                      cols=dlg.chosen_cols)
            win = MainWindow(backend=args.backend, layout_config=layout_cfg)
            win.show()
        else:
            sys.exit(0)

    if win and args.library:
        lib_path = Path(args.library)
        if lib_path.is_dir():
            win._slot_library_root_changed(lib_path)
            win.library_dock.set_library_root(lib_path)
            win.library_dock.setVisible(True)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
