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

import os
from collections import defaultdict
from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .. import settings
from ..models import PlanItem
from .preview_player import SnippetPlayer

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


def _quality_key(item: PlanItem):
    """Higher = better copy to keep (bitrate first, then file size)."""
    return (item.track.bitrate or 0, item.track.size or 0)


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
        # Items actually deleted from disk from this dialog; the caller uses
        # this to drop them from the main list.
        self.deleted_items: List[PlanItem] = []
        # True if the user told the app some files are NOT duplicates; the
        # caller then recomputes the duplicate groups.
        self.marked_not_duplicate = False
        self._player = SnippetPlayer(self)

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
            "move list below. Tick the copies you want to delete from disk, then press "
            "'Delete Checked Files'. Nothing is deleted until you confirm."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        tree = QTreeWidget()
        self._tree = tree
        self._item_for_node: Dict[int, PlanItem] = {}
        tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        tree.setHeaderLabels(["Song (artist - title)", "Details", "Detected via", "Full path"])
        tree.header().setStretchLastSection(True)
        tree.header().resizeSection(0, 280)
        tree.header().resizeSection(1, 220)
        tree.header().resizeSection(2, 180)

        self._nodes: List[QTreeWidgetItem] = []
        self._groups = [gi for _, gi in ordered_groups]
        for group_id, group_items in ordered_groups:
            method = group_items[0].dup_method
            method_label = _METHOD_LABELS.get(method, method or "unknown")
            group_node = QTreeWidgetItem(
                [f"{_describe(group_items[0])}  ({len(group_items)} copies)", "", method_label, ""]
            )
            group_node.setFirstColumnSpanned(False)
            for item in group_items:
                child = QTreeWidgetItem(
                    group_node,
                    [
                        f"{_describe(item)}  [{item.track.path.name}]",
                        _details(item),
                        "",
                        str(item.source_path),
                    ],
                )
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)
                self._item_for_node[id(child)] = item
                self._nodes.append(child)
            tree.addTopLevelItem(group_node)
            group_node.setExpanded(True)

        layout.addWidget(tree, 1)

        self._status_label = QLabel()
        layout.addWidget(self._status_label)
        tree.itemChanged.connect(lambda *_: self._update_status())

        button_row = QHBoxLayout()
        play_btn = QPushButton("\u25b6 Play First 5 Sec")
        play_btn.setToolTip("Select a file in the list, then play the first few seconds to compare copies.")
        play_btn.clicked.connect(self._play_selected)
        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self._player.stop)
        not_dup_btn = QPushButton("Not a Duplicate")
        not_dup_btn.setToolTip(
            "Select a group (or Ctrl-click two or more copies in a group) and tell the app "
            "they are different songs. It will remember and stop flagging them."
        )
        not_dup_btn.clicked.connect(self._mark_not_duplicate)
        auto_btn = QPushButton("Auto-Check Extras (keep best quality)")
        auto_btn.setToolTip("In every group, check all copies except the highest bitrate / largest file.")
        auto_btn.clicked.connect(self._auto_check_extras)
        clear_btn = QPushButton("Uncheck All")
        clear_btn.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        self._delete_btn = QPushButton("Delete Checked Files...")
        self._delete_btn.clicked.connect(self._delete_checked)
        ok_btn = QPushButton("Close")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setDefault(True)
        button_row.addWidget(play_btn)
        button_row.addWidget(stop_btn)
        button_row.addWidget(not_dup_btn)
        button_row.addWidget(auto_btn)
        button_row.addWidget(clear_btn)
        button_row.addStretch(1)
        button_row.addWidget(self._delete_btn)
        button_row.addWidget(ok_btn)
        layout.addLayout(button_row)
        self._update_status()

    # -- selection / deletion ---------------------------------------------

    def _checked_nodes(self) -> List[QTreeWidgetItem]:
        return [n for n in self._nodes if n.checkState(0) == Qt.Checked]

    def _set_all(self, state) -> None:
        for n in self._nodes:
            n.setCheckState(0, state)

    def _auto_check_extras(self) -> None:
        by_item = {id(it): n for n, it in ((n, self._item_for_node[id(n)]) for n in self._nodes)}
        for group_items in self._groups:
            live = [it for it in group_items if id(it) in by_item]
            if len(live) < 2:
                continue
            best = max(live, key=_quality_key)
            for it in live:
                by_item[id(it)].setCheckState(0, Qt.Unchecked if it is best else Qt.Checked)

    def _play_selected(self) -> None:
        for node in self._tree.selectedItems():
            item = self._item_for_node.get(id(node))
            if item is not None:
                if not self._player.play(item.source_path):
                    QMessageBox.warning(self, "Playback Unavailable", f"Audio playback isn't available: {self._player.error}")
                return
        QMessageBox.information(self, "Select a File", "Select one of the copies (not the group heading) to play.")

    def _mark_not_duplicate(self) -> None:
        selected = self._tree.selectedItems()
        children = [n for n in selected if id(n) in self._item_for_node]
        group_nodes = [n for n in selected if id(n) not in self._item_for_node]
        paths = []
        if len(children) >= 2:
            paths = [self._item_for_node[id(n)].source_path for n in children]
        else:
            node = group_nodes[0] if group_nodes else (children[0].parent() if children else None)
            if node is not None:
                paths = [
                    self._item_for_node[id(node.child(i))].source_path
                    for i in range(node.childCount())
                    if id(node.child(i)) in self._item_for_node
                ]
        if len(paths) < 2:
            QMessageBox.information(
                self, "Select Copies", "Select a group, or two or more copies in a group, to mark as different songs."
            )
            return
        settings.add_not_duplicate_pairs(paths)
        self.marked_not_duplicate = True
        self._player.stop()
        self.accept()  # caller recomputes groups and reopens this review

    def _update_status(self) -> None:
        n = len(self._checked_nodes())
        self._status_label.setText(f"{n} file(s) checked for deletion.")
        self._delete_btn.setEnabled(n > 0)

    def _delete_checked(self) -> None:
        checked = self._checked_nodes()
        if not checked:
            return
        checked_items = {id(self._item_for_node[id(n)]) for n in checked}
        # Safety: refuse to wipe out every copy of a song.
        for group_items in self._groups:
            live = [it for it in group_items if it not in self.deleted_items]
            if live and all(id(it) in checked_items for it in live):
                QMessageBox.warning(
                    self,
                    "Keep At Least One Copy",
                    f"All copies of '{_describe(live[0])}' are checked. Uncheck at least one "
                    "copy in each group so you don't delete the song entirely.",
                )
                return
        reply = QMessageBox.question(
            self,
            "Delete Files",
            f"Permanently delete {len(checked)} file(s) from disk? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        failures = []
        for node in checked:
            item = self._item_for_node[id(node)]
            try:
                os.remove(item.source_path)
            except OSError as exc:
                failures.append(f"{item.source_path.name}: {exc}")
                continue
            self.deleted_items.append(item)
            parent = node.parent()
            if parent is not None:
                parent.removeChild(node)
            self._nodes.remove(node)
            del self._item_for_node[id(node)]
        self._update_status()
        if failures:
            QMessageBox.warning(self, "Some Files Not Deleted", "\n".join(failures[:20]))
