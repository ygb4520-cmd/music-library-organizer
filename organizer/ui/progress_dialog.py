"""Shared modal progress UI for both the scan and the move phases."""
from __future__ import annotations

from PySide6.QtWidgets import QProgressDialog
from PySide6.QtCore import Qt


def make_progress_dialog(parent, label: str, on_cancel=None) -> QProgressDialog:
    dialog = QProgressDialog(label, "Cancel", 0, 100, parent)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(True)
    dialog.setAutoReset(True)
    dialog.setValue(0)
    if on_cancel is not None:
        dialog.canceled.connect(on_cancel)
    return dialog
