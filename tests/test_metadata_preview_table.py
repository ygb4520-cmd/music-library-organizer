"""Headless checks (python3 tests/test_metadata_preview_table.py) for the metadata-lookup results dialog:
1. every row is filled in (an old bug left most rows blank because sorting was on while the table was being filled), and
2. after the user clicks a column header to re-sort, "Write Selected Tags" still writes each row's own file."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from organizer import settings, tag_writer
from organizer.metadata_lookup import MatchCandidate
from organizer.models import TrackInfo
from organizer.ui import metadata_preview_dialog as mpd

app = QApplication.instance() or QApplication([])
fails = 0
def check(name, ok, extra=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (("  " + extra) if (extra and not ok) else "")); fails += (not ok)

# never touch the real saved preferences
settings.get_sort_order = lambda: settings.SORT_CONFIDENCE_DESC
settings.get_multi_artist_mode = lambda: settings.MULTI_ARTIST_FULL

DATA = [(95, "Queen", "Bohemian Rhapsody", "A Night at the Opera"), (40, "Abba", "Waterloo", None), (88, "Adele", "Hello", "25"),
        (30, "Zed", "Song Z", None), (99, "Beatles", "Yesterday", "Help!"), (55, "Muse", "Uprising", "The Resistance"),
        (91, "Coldplay", "Yellow", "Parachutes"), (20, "Bob", "Track B", None)]
def make():
    rows = [(TrackInfo(path=Path(f"/music/file_{i}.mp3"), ext=".mp3"), MatchCandidate(score=s, artist=a, title=t, album=al))
            for i, (s, a, t, al) in enumerate(DATA)]
    return mpd.MetadataPreviewDialog(rows)

dlg = make(); t = dlg.table
def cell(r, c): return t.item(r, c).text() if t.item(r, c) else None

check("all 8 rows exist", t.rowCount() == 8)
check("no blank File/Artist/Title cell in any row", all(cell(r, c) for r in range(8) for c in (mpd.COL_FILE, mpd.COL_ARTIST, mpd.COL_TITLE)),
      str([[cell(r, c) for c in range(9)] for r in range(8)]))
check("each row's File matches its own Artist/Title", all(
    (cell(r, mpd.COL_ARTIST), cell(r, mpd.COL_TITLE)) == DATA[int(cell(r, mpd.COL_FILE).split('_')[1].split('.')[0])][1:3] for r in range(8)))
check("starts in the order chosen in Settings (confidence high to low)", [int(cell(r, mpd.COL_CONFIDENCE)) for r in range(8)] == sorted([d[0] for d in DATA], reverse=True))
check("the table is sortable by clicking headers", t.isSortingEnabled())

# re-sort by Artist (A to Z), tick two rows, write -> the right files must be written
t.sortByColumn(mpd.COL_ARTIST, Qt.AscendingOrder)
check("table really re-sorted by artist", [cell(r, mpd.COL_ARTIST) for r in range(8)] == sorted(d[1] for d in DATA))
for r in range(8):
    t.item(r, mpd.COL_INCLUDE).setCheckState(Qt.Checked if cell(r, mpd.COL_ARTIST) in ("Muse", "Adele") else Qt.Unchecked)
written = []
tag_writer.write_tags = lambda path, artist, title, album: written.append((Path(path).name, artist, title))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
dlg.accept = lambda: None
dlg._write_selected()
check("after re-sorting, tags go to the right files", sorted(written) == [("file_2.mp3", "Adele", "Hello"), ("file_5.mp3", "Muse", "Uprising")], str(written))

# editing a cell then writing uses the edited text for that row
dlg2 = make(); t2 = dlg2.table
for r in range(8): t2.item(r, mpd.COL_INCLUDE).setCheckState(Qt.Unchecked)
t2.item(0, mpd.COL_INCLUDE).setCheckState(Qt.Checked); t2.item(0, mpd.COL_TITLE).setText("Edited Title")
written.clear(); dlg2.accept = lambda: None; dlg2._write_selected()
check("an edited title is what gets written", len(written) == 1 and written[0][2] == "Edited Title", str(written))
print("\n" + ("all passed" if not fails else f"{fails} failed")); sys.exit(1 if fails else 0)
