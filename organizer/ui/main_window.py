"""Main application window: folder selection, scan trigger, preview, and the
move workflow. Uses the platform-default Qt style/native dialogs throughout
so the app inherits Windows look-and-feel automatically when run there."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import planner, updater
from ..__version__ import __version__
from ..metadata_worker import MetadataLookupWorker
from ..models import MetadataSource
from ..mover import MoveWorker
from ..scanner import ScanWorker
from .confirm_dialog import confirm_move
from .metadata_preview_dialog import MetadataPreviewDialog
from .preview_view import PreviewView
from .progress_dialog import make_progress_dialog
from .settings_dialog import SettingsDialog
from .tag_editor_dialog import TagEditorDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music Library Organizer")
        self.resize(1200, 700)

        self.source_root: Path | None = None
        self.destination_root: Path | None = None
        self._scan_worker: ScanWorker | None = None
        self._move_worker: MoveWorker | None = None
        self._scan_progress = None
        self._move_progress = None
        self._update_check_worker: updater.UpdateCheckWorker | None = None
        self._update_apply_worker: updater.UpdateApplyWorker | None = None
        self._metadata_worker: MetadataLookupWorker | None = None
        self._metadata_progress = None

        self._build_menu()
        self._build_central_widget()
        self._update_folder_label()

        # Belt-and-suspenders: aboutToQuit covers every quit path (window
        # close, explicit quit(), Ctrl+C in the launching terminal), not
        # just closeEvent -- a running QThread destroyed at interpreter
        # shutdown is a hard abort() in Qt, so this must never be skipped.
        QApplication.instance().aboutToQuit.connect(self.shutdown_workers)

        # Silent on-launch check -- only bothers the user if there's
        # actually something new. No-op when running from source (dev mode).
        self._check_for_updates(silent=True)

    def shutdown_workers(self):
        for worker in (self._scan_worker, self._move_worker, self._update_check_worker, self._metadata_worker):
            if worker is not None and worker.isRunning():
                if hasattr(worker, "cancel"):
                    worker.cancel()
                worker.wait()

    # -- UI construction -------------------------------------------------

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")

        select_action = file_menu.addAction("&Select Source Folder...")
        select_action.triggered.connect(self.select_source_folder)

        dest_action = file_menu.addAction("Choose &Destination Folder...")
        dest_action.triggered.connect(self.select_destination_folder)

        rescan_action = file_menu.addAction("&Rescan")
        rescan_action.triggered.connect(self.start_scan)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        tools_menu = self.menuBar().addMenu("&Tools")
        lookup_action = tools_menu.addAction("&Look Up Missing Metadata...")
        lookup_action.triggered.connect(self.lookup_missing_metadata)

        edit_tags_action = tools_menu.addAction("&Edit Tags...")
        edit_tags_action.triggered.connect(self.edit_selected_tags)

        tools_menu.addSeparator()
        settings_action = tools_menu.addAction("&Settings...")
        settings_action.triggered.connect(self.open_settings)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self._show_about)

        update_action = help_menu.addAction("Check for &Updates...")
        update_action.triggered.connect(lambda: self._check_for_updates(silent=False))

    def _build_central_widget(self):
        central = QWidget()
        layout = QVBoxLayout(central)

        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)

        self.select_button = QPushButton("Select Source Folder...")
        self.select_button.clicked.connect(self.select_source_folder)

        self.preview = PreviewView()

        self.move_button = QPushButton("Move Selected Files...")
        self.move_button.setEnabled(False)
        self.move_button.clicked.connect(self.start_move)

        layout.addWidget(self.folder_label)
        layout.addWidget(self.select_button)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.move_button)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Select a source folder to begin.")

    def closeEvent(self, event):
        active_worker = None
        if self._scan_worker is not None and self._scan_worker.isRunning():
            active_worker = self._scan_worker
        elif self._move_worker is not None and self._move_worker.isRunning():
            active_worker = self._move_worker

        if active_worker is not None:
            reply = QMessageBox.question(
                self,
                "Operation in Progress",
                "A scan or move is still in progress. Cancel it and quit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            active_worker.cancel()
            active_worker.wait()
            # The progress dialog is its own top-level window; closing only
            # the main window leaves it open, which blocks Qt's
            # quit-on-last-window-closed and the app never actually exits.
            for dialog in (self._scan_progress, self._move_progress):
                if dialog is not None:
                    dialog.close()

        event.accept()

    def _show_about(self):
        QMessageBox.information(
            self,
            "About Music Library Organizer",
            f"Music Library Organizer v{__version__}\n\n"
            "Reorganizes audio files into Album Artist / Album folders based on "
            "existing tags, without modifying tags. Files are moved, not copied.",
        )

    # -- Self-update ----------------------------------------------------

    def _check_for_updates(self, silent: bool):
        if self._update_check_worker is not None and self._update_check_worker.isRunning():
            return
        self._update_check_silent = silent
        self._update_check_worker = updater.UpdateCheckWorker()
        self._update_check_worker.found_update.connect(self._on_update_found)
        self._update_check_worker.no_update.connect(self._on_no_update)
        self._update_check_worker.start()

    def _on_no_update(self):
        if not self._update_check_silent:
            QMessageBox.information(
                self, "No Updates", f"You're on the latest version (v{__version__})."
            )

    def _on_update_found(self, version: str, asset_url: str):
        reply = QMessageBox.question(
            self,
            "Update Available",
            f"A new version (v{version}) is available. Download and install it now?\n\n"
            "The app will restart automatically once it's installed.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self._update_apply_had_error = False
        self._update_apply_worker = updater.UpdateApplyWorker(asset_url)
        self._update_apply_worker.progress_text.connect(
            lambda text: self.statusBar().showMessage(text)
        )
        self._update_apply_worker.failed.connect(self._on_update_failed)
        self._update_apply_worker.finished.connect(self._on_update_apply_finished)
        self._update_apply_worker.start()

    def _on_update_apply_finished(self):
        # A successful run means a detached helper is waiting to relaunch
        # the app under a new process -- quit so it can take over. If it
        # failed, _on_update_failed already reported that and set the flag
        # below, so there's nothing to quit for.
        if not self._update_apply_had_error:
            QApplication.instance().quit()

    def _on_update_failed(self, message: str):
        self._update_apply_had_error = True
        QMessageBox.critical(self, "Update Failed", f"Could not install the update:\n{message}")

    def _update_folder_label(self):
        if self.source_root is None:
            self.folder_label.setText("No source folder selected.")
            return
        dest_text = (
            "same as source (in place)"
            if self.destination_root == self.source_root
            else str(self.destination_root)
        )
        self.folder_label.setText(
            f"<b>Source:</b> {self.source_root} &nbsp;&nbsp; <b>Destination:</b> {dest_text}"
        )

    # -- Folder selection --------------------------------------------------

    def select_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Music Library Folder")
        if not folder:
            return
        self.source_root = Path(folder)
        self.destination_root = self.source_root
        self._update_folder_label()
        self.start_scan()

    def select_destination_folder(self):
        if self.source_root is None:
            QMessageBox.warning(self, "No Source Folder", "Select a source folder first.")
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Select Destination Folder (leave as source for in-place reorganization)"
        )
        if not folder:
            return
        self.destination_root = Path(folder)
        self._update_folder_label()

    # -- Scan ---------------------------------------------------------------

    def start_scan(self):
        if self.source_root is None:
            return
        self.move_button.setEnabled(False)
        self._scan_progress = make_progress_dialog(
            self, "Scanning music library...", on_cancel=self._cancel_scan
        )
        self._scan_worker = ScanWorker(self.source_root)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def _cancel_scan(self):
        if self._scan_worker is not None:
            self._scan_worker.cancel()

    def _on_scan_progress(self, done: int, total: int):
        if self._scan_progress is None:
            return
        self._scan_progress.setMaximum(max(total, 1))
        self._scan_progress.setValue(done)
        self._scan_progress.setLabelText(f"Reading tags... {done}/{total}")

    def _on_scan_finished(self, tracks):
        if self._scan_worker is not None:
            self._scan_worker.wait()
        if self._scan_progress is not None:
            self._scan_progress.setValue(self._scan_progress.maximum())
        items = planner.build_plan(tracks, self.source_root, self.destination_root)
        self.preview.set_items(items)
        self.move_button.setEnabled(len(items) > 0)
        self.statusBar().showMessage(f"Scan complete: {len(tracks)} audio files found.")

    def _on_scan_failed(self, message: str):
        QMessageBox.critical(self, "Scan Failed", f"Could not complete the scan:\n{message}")

    # -- Move -----------------------------------------------------------

    def start_move(self):
        items = self.preview.model.items()
        selected = [i for i in items if i.include and i.dest_path is not None]
        in_place = self.destination_root == self.source_root
        if not confirm_move(self, len(selected), self.destination_root, in_place):
            return

        self.move_button.setEnabled(False)
        self._move_progress = make_progress_dialog(
            self, "Moving files...", on_cancel=self._cancel_move
        )
        self._move_worker = MoveWorker(items, self.source_root)
        self._move_worker.progress.connect(self._on_move_progress)
        self._move_worker.finished_move.connect(self._on_move_finished)
        self._move_worker.start()

    def _cancel_move(self):
        if self._move_worker is not None:
            self._move_worker.cancel()

    def _on_move_progress(self, done: int, total: int):
        if self._move_progress is None:
            return
        self._move_progress.setMaximum(max(total, 1))
        self._move_progress.setValue(done)
        self._move_progress.setLabelText(f"Moving files... {done}/{total}")

    def _on_move_finished(self, result):
        if self._move_worker is not None:
            self._move_worker.wait()
        if self._move_progress is not None:
            self._move_progress.setValue(self._move_progress.maximum())

        lines = [f"Moved: {len(result.moved)}", f"Failed: {len(result.failed)}"]
        if result.already_in_place:
            lines.append(f"Already in place: {len(result.already_in_place)}")
        if result.cleaned_dirs:
            lines.append(f"Removed {len(result.cleaned_dirs)} now-empty folder(s).")
        if result.failed:
            lines.append("\nFailures:")
            for item in result.failed[:20]:
                lines.append(f"  {item.source_path.name}: {item.move_error}")
            if len(result.failed) > 20:
                lines.append(f"  ...and {len(result.failed) - 20} more.")

        QMessageBox.information(self, "Move Complete", "\n".join(lines))
        self.statusBar().showMessage(
            f"Move complete: {len(result.moved)} moved, {len(result.failed)} failed."
        )
        self.start_scan()

    # -- Metadata lookup --------------------------------------------------

    def lookup_missing_metadata(self):
        if self._metadata_worker is not None and self._metadata_worker.isRunning():
            return

        items = self.preview.model.items()
        if not items:
            QMessageBox.information(
                self, "No Files Scanned", "Scan a folder first, then look up missing metadata."
            )
            return

        candidates = [item.track for item in items if item.track.metadata_source == MetadataSource.NONE]
        if not candidates:
            QMessageBox.information(
                self, "Nothing to Look Up", "Every scanned file already has tag data — nothing is unknown."
            )
            return

        reply = QMessageBox.question(
            self,
            "Look Up Missing Metadata",
            f"{len(candidates)} file(s) have no tag data. Search MusicBrainz's free online "
            "database for likely matches based on filename?\n\n"
            "This only looks things up — nothing is written to any file until you review and "
            "confirm matches in the next screen.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self._metadata_progress = make_progress_dialog(
            self, "Looking up metadata online...", on_cancel=self._cancel_metadata_lookup
        )
        self._metadata_worker = MetadataLookupWorker(candidates)
        self._metadata_worker.progress.connect(self._on_metadata_progress)
        self._metadata_worker.finished_lookup.connect(self._on_metadata_finished)
        self._metadata_worker.failed.connect(self._on_metadata_failed)
        self._metadata_worker.start()

    def _cancel_metadata_lookup(self):
        if self._metadata_worker is not None:
            self._metadata_worker.cancel()

    def _on_metadata_progress(self, done: int, total: int):
        if self._metadata_progress is None:
            return
        self._metadata_progress.setMaximum(max(total, 1))
        self._metadata_progress.setValue(done)
        self._metadata_progress.setLabelText(f"Looking up metadata online... {done}/{total}")

    def _on_metadata_finished(self, results):
        if self._metadata_worker is not None:
            self._metadata_worker.wait()
        if self._metadata_progress is not None:
            self._metadata_progress.setValue(self._metadata_progress.maximum())

        dialog = MetadataPreviewDialog(results, parent=self)
        if dialog.exec():
            self.start_scan()  # tags changed on disk -- rescan to reflect it

    def _on_metadata_failed(self, message: str):
        if self._metadata_progress is not None:
            self._metadata_progress.close()
        QMessageBox.critical(self, "Lookup Failed", f"Could not complete the metadata lookup:\n{message}")

    # -- Settings & manual tag editing --------------------------------------

    def open_settings(self):
        SettingsDialog(self).exec()

    def edit_selected_tags(self):
        selected_rows = self.preview.table.selectionModel().selectedRows() if self.preview.table.selectionModel() else []
        if not selected_rows:
            QMessageBox.information(
                self, "No File Selected", "Select a file in the list first, then choose Edit Tags."
            )
            return

        # Only the first selected row -- editing several files' tags at once
        # in one form doesn't make sense (they'd have different values).
        proxy_index = selected_rows[0]
        source_index = self.preview.proxy.mapToSource(proxy_index)
        item = self.preview.model.items()[source_index.row()]

        dialog = TagEditorDialog(item.track, parent=self)
        if dialog.exec():
            self.start_scan()  # tags changed on disk -- rescan to reflect it
