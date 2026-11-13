"""Post-scan duplicate review popup: shown automatically right after a scan
finds any Status.DUPLICATE items, before the user gets to the move step --
mirrors the app's existing preview-before-action design (metadata lookup,
move itself), just for information rather than a write action.

Duplicates are already excluded from the move plan by
planner._flag_duplicates() by the time this dialog appears (unchecked in the
main preview table, where they remain individually re-includable). This
dialog doesn't change that -- it exists purely so a duplicate group's
detection method (fingerprint / tag / filename) is visible up front instead
of only as small print in the main table's Notes column, since a fingerprint
match is a much stronger signal than a filename match and the user may want
to weigh them differently before deciding what to re-include."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..models import PlanItem

_METHOD_LABELS = {
    "fingerprint": "Audio fingerprint match",
    "tag": "Tag match (artist + title)",
    "filename": "Filename match",
}
# Priority order duplicates are checked in (planner._flag_duplicates) --
# used here only to sort groups so the strongest-evidence ones surface
# first.
_METHOD_ORDER = {"fingerprint": 0, "tag": 1, "filename": 2}


def _describe(item: PlanItem) -> str:
    """Human-readable 'Artist - Title' for a file, falling back to the file name."""
    track = item.track
    title = track.title or track.path.stem
    artist = track.artist or track.album_artist
    return f"{artist} - {title}" if artist else title


def _details(item: PlanItem) -> str:
    track = item.track
    parts = []
    if track.album:
        parts.append(f"Album: {track.album}")
    if track.ext:
        parts.append(track.ext.lstrip(".").upper())
    if track.bitrate:
        parts.append(f"{int(track.bitrate)} kbps")
    if track.size:
        parts.append(f"{track.size / (1024 * 1024):.1f} MB")
    return " | ".join(parts)


class DuplicateReviewDialog(QDialog):
    def __init__(self, duplicate_items: List[PlanItem], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Possible Duplicates Found")
        self.resize(1000, 500)

        groups: Dict[str, List[PlanItem]] = defaultdict(list)
        for item in duplicate_items:
            groups[item.group_id or "?"].append(item)

        ordered_groups = sorted(
            groups.items(),
            key=lambda kv: _METHOD_ORDER.get(kv[1][0].dup_method, 99),
        )

        layout = QVBoxLayout(self)

        summary = QLabel(
            f"<b>{len(ordered_groups)}</b> duplicate group(s) found "
            f"(<b>{len(duplicate_items)}</b> file(s) total). These are unchecked in the "
            "move list below -- review here, then adjust individual files there if needed."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Song (artist - title)", "Details", "Detected via", "Full path"])
        tree.header().setStretchLastSection(True)
        tree.header().resizeSection(0, 280)
        tree.header().resizeSection(1, 220)
        tree.header().resizeSection(2, 180)

        for group_id, group_items in ordered_groups:
            method = group_items[0].dup_method
            method_label = _METHOD_LABELS.get(method, method or "unknown")
            group_node = QTreeWidgetItem(
                [f"{_describe(group_items[0])}  ({len(group_items)} copies)", "", method_label, ""]
            )
            group_node.setFirstColumnSpanned(False)
            for item in group_items:
                QTreeWidgetItem(
                    group_node,
                    [
                        f"{_describe(item)}  [{item.track.path.name}]",
                        _details(item),
                        "",
                        str(item.source_path),
                    ],
                )
            tree.addTopLevelItem(group_node)
            group_node.setExpanded(True)

        layout.addWidget(tree, 1)

        button_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setDefault(True)
        button_row.addStretch(1)
        button_row.addWidget(ok_btn)
        layout.addLayout(button_row)
