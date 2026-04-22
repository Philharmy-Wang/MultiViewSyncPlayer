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
    parser.add_argument('--backend', default='opencv',
                        choices=['opencv', 'mpv'],
                        help='Video decode backend (default: opencv)')
    args = parser.parse_args()

    # Try mpv backend
    if args.backend == 'mpv':
        try:
            import mpv
        except OSError:
            print("[Warning] mpv DLL not found, falling back to opencv backend")
            print("  Download: https://github.com/shinchiro/mpv-winbuild-cmake/releases")
            args.backend = 'opencv'

    from PySide6.QtWidgets import QApplication, QDialog
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion')

    from .main_window import MainWindow

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

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
