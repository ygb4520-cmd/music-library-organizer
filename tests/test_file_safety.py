"""Headless checks (python3 tests/test_file_safety.py) for the code that touches real files or installs software:
the mover (never overwrites, handles already-in-place, cleans only empty folders), the 'not a duplicate' splitting in the
planner, and the self-updater's integrity helpers (trusted URL, checksum parsing/verification)."""
import os, sys, tempfile, hashlib
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from organizer.models import PlanItem, TrackInfo
from organizer.mover import MoveWorker
from organizer import planner, updater

fails = 0
def check(name, ok, extra=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (("  " + str(extra)) if (extra and not ok) else "")); fails += (not ok)

def item(src, dest, include=True):
    return PlanItem(track=TrackInfo(path=Path(src), ext=Path(src).suffix), dest_path=Path(dest) if dest else None, include=include)

# ---- mover ----
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    (root / "messy").mkdir(); (root / "empty_after" / "sub").mkdir(parents=True); (root / "keep").mkdir()
    a = root / "messy" / "a.mp3"; a.write_bytes(b"A")
    b = root / "empty_after" / "sub" / "b.mp3"; b.write_bytes(b"B")
    c = root / "messy" / "c.mp3"; c.write_bytes(b"C")
    already = root / "Artist" / "Album" / "x.mp3"; already.parent.mkdir(parents=True); already.write_bytes(b"X")
    taken_src = root / "messy" / "t.mp3"; taken_src.write_bytes(b"NEW")
    taken_dest = root / "Other" / "Album" / "t.mp3"; taken_dest.parent.mkdir(parents=True); taken_dest.write_bytes(b"OLD")
    skipped = root / "messy" / "skip.mp3"; skipped.write_bytes(b"S")
    unresolved = root / "messy" / "u.mp3"; unresolved.write_bytes(b"U")
    (root / "keep" / "other.txt").write_text("not audio, folder must stay")

    items = [item(a, root / "Artist" / "Album" / "a.mp3"), item(b, root / "Artist" / "Album" / "b.mp3"),
             item(already, already), item(taken_src, taken_dest),
             item(skipped, root / "Artist" / "Album" / "skip.mp3", include=False), item(unresolved, None)]
    w = MoveWorker(items, root); w.run()  # run() directly (same thread) so the test needs no event loop
    check("moved file lands at destination with content intact", (root / "Artist" / "Album" / "a.mp3").read_bytes() == b"A" and not a.exists())
    check("second file moved too", (root / "Artist" / "Album" / "b.mp3").read_bytes() == b"B" and not b.exists())
    check("already-in-place file untouched", already.read_bytes() == b"X")
    check("existing destination is NEVER overwritten", taken_dest.read_bytes() == b"OLD" and taken_src.read_bytes() == b"NEW")
    check("failed item records why", items[3].move_error is not None and "already exists" in items[3].move_error.lower())
    check("unchecked item not moved", skipped.exists() and not (root / "Artist" / "Album" / "skip.mp3").exists())
    check("item with no destination not moved", unresolved.exists())
    check("emptied folders removed", not (root / "empty_after").exists())
    check("non-empty folders kept (even with non-audio files)", (root / "keep" / "other.txt").exists() and (root / "messy").exists())
    check("source root itself kept", root.exists())

# ---- planner: 'not a duplicate' splitting ----
def pi(p): return item(p, "/dest/" + Path(p).name)
x, y, z = pi("/m/1.mp3"), pi("/m/2.mp3"), pi("/m/3.mp3")
same = planner._split_by_not_dupes([[x, y, z]], set())
check("no marks: group unchanged", [len(g) for g in same] == [3])
split = planner._split_by_not_dupes([[x, y, z]], {frozenset(("/m/1.mp3", "/m/2.mp3"))})
check("marked pair is separated", not any(x in g and y in g for g in split), [[str(i.source_path) for i in g] for g in split])
check("no file lost or duplicated by splitting", sorted(str(i.source_path) for g in split for i in g) == ["/m/1.mp3", "/m/2.mp3", "/m/3.mp3"])

# ---- updater integrity helpers ----
good = "https://github.com/ygb4520-cmd/music-library-organizer/releases/download/v1.0.0/MusicLibraryOrganizer.exe"
check("official release URL trusted", updater.is_trusted_asset_url(good))
check("other repo rejected", not updater.is_trusted_asset_url(good.replace("ygb4520-cmd", "evil")))
check("other host rejected", not updater.is_trusted_asset_url("https://evil.example/ygb4520-cmd/music-library-organizer/releases/download/x.exe"))
check("http (not https) rejected", not updater.is_trusted_asset_url(good.replace("https", "http")))
check("lookalike prefix rejected", not updater.is_trusted_asset_url("https://github.com/ygb4520-cmd/music-library-organizer-evil/releases/download/x.exe"))
check("non-string rejected", not updater.is_trusted_asset_url(None))
digest = hashlib.sha256(b"hello").hexdigest()
check("parses bare hash", updater.parse_sha256_text(digest + "\n") == digest)
check("parses sha256sum format, uppercase", updater.parse_sha256_text(f"{digest.upper()}  MusicLibraryOrganizer.exe\n") == digest)
check("garbage / short hash -> None", updater.parse_sha256_text("not a hash") is None and updater.parse_sha256_text("abc123") is None and updater.parse_sha256_text("") is None)
with tempfile.NamedTemporaryFile(delete=False) as f:
    f.write(b"hello")
check("file hash matches known sha256", updater.sha256_of_file(f.name) == digest)
os.unlink(f.name)
check("version compare: newer / same / older", updater._is_newer("v0.6.2", "0.6.1") and not updater._is_newer("0.6.1", "0.6.1") and not updater._is_newer("0.5.9", "0.6.1"))

print("\n%s" % ("all passed" if not fails else "%d failed" % fails)); sys.exit(1 if fails else 0)
