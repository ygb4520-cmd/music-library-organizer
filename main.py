import logging
import logging.handlers
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from organizer.ui.main_window import MainWindow


def _setup_logging():
    """Logs warnings/errors (with tracebacks) to a file in the user's app-data folder so lookup problems can be diagnosed later."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or Path.home() / ".music-library-organizer")
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(folder / "organizer.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Music Library Organizer")
    _setup_logging()  # after the app name is set so the log lands in this app's own data folder
    window = MainWindow()
    window.show()
    try:
        exit_code = app.exec()
    finally:
        # Guarantee worker threads are joined even if exec() exits via an
        # unhandled exception (e.g. Ctrl+C) rather than a normal quit signal.
        window.shutdown_workers()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
