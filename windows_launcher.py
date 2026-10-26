"""Windowed entry point with a diagnostic mode for release verification."""
import sys
import traceback
from pathlib import Path


if __name__ == '__main__':
    try:
        if '--self-test' in sys.argv:
            from xps_studio.release_check import run
            run(Path(sys.argv[sys.argv.index('--self-test') + 1]))
        else:
            from xps_studio.app import main
            main()
    except Exception:
        error = traceback.format_exc()
        if '--self-test' in sys.argv:
            Path(sys.argv[sys.argv.index('--self-test') + 1]).write_text(error, encoding='utf-8')
        else:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(None, 'XPS Studio could not start', error)
        sys.exit(1)
