"""Final, unambiguous confirmation before any file is moved."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox


def confirm_move(parent, count: int, destination_root: Path, in_place: bool) -> bool:
    if count == 0:
        QMessageBox.information(
            parent, "Nothing to Move", "No files are currently selected to move."
        )
        return False

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Confirm Move")
    location_note = (
        "inside your existing library folder" if in_place else f"into:\n{destination_root}"
    )
    box.setText(f"This will move {count} file(s) {location_note}.")
    box.setInformativeText(
        "Files are MOVED, not copied — this changes your existing library layout in place. "
        "Tags are never modified. This cannot be automatically undone.\n\n"
        "Continue?"
    )
    yes_btn = box.addButton("Yes, Move Files", QMessageBox.AcceptRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(yes_btn)
    box.setEscapeButton(box.buttons()[-1])
    # Make Cancel the visually/keyboard-safe default despite AcceptRole ordering.
    box.setDefaultButton(box.buttons()[-1])

    box.exec()
    return box.clickedButton() is yes_btn
