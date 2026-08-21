import sys

from PySide6.QtWidgets import QApplication

from organizer.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Music Library Organizer")
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
