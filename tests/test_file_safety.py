"""Headless checks (python3 tests/test_file_safety.py) for the code that touches real files or installs software:
the mover (never overwrites, handles already-in-place, cleans only empty folders), the 'not a duplicate' splitting in the
planner, and the self-updater's integrity helpers (trusted URL, checksum parsing/verification)."""
import os, sys, tempfile, hashlib
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile as _tf
os.environ["MLO_UNDO_DIR"] = _tf.mkdtemp(prefix="mlo-undo-test-")  # never write logs to the real app-data folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from organizer.models import PlanItem, Status, TrackInfo
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

    # ---- undo log ----
    from organizer import undo_log
    check("undo log written for the run", undo_log.find_latest_log() is not None)
    # a file moved again by hand after the run must be skipped, not overwritten
    (root / "Artist" / "Album" / "b.mp3").rename(root / "Artist" / "b_moved_by_hand.mp3")
    c_dest_blocker = root / "messy" / "a.mp3"; c_dest_blocker.parent.mkdir(exist_ok=True); c_dest_blocker.write_bytes(b"BLOCK")
    res = undo_log.undo_last_run()
    check("undo: no error", res.error is None, res.error)
    check("undo: file whose original spot is occupied is skipped, not overwritten", c_dest_blocker.read_bytes() == b"BLOCK" and (root / "Artist" / "Album" / "a.mp3").exists() and any("occupied" in r for _, r in res.skipped), res.skipped)
    check("undo: file moved by hand is skipped", any("b.mp3" in p and "no longer" in r for p, r in res.skipped), res.skipped)
    check("undo: unmoved-by-hand file restored where it started", (root / "messy" / "t.mp3").read_bytes() == b"NEW")
    check("undo: log consumed", undo_log.find_latest_log() is None)

with tempfile.TemporaryDirectory() as d:
    from organizer import undo_log
    root = Path(d); (root / "m").mkdir(); (root / "e" / "s").mkdir(parents=True)
    f1 = root / "m" / "1.mp3"; f1.write_bytes(b"1"); f2 = root / "e" / "s" / "2.mp3"; f2.write_bytes(b"2")
    MoveWorker([item(f1, root / "A" / "B" / "1.mp3"), item(f2, root / "A" / "B" / "2.mp3")], root).run()
    check("clean run: emptied folder removed", not (root / "e").exists())
    res = undo_log.undo_last_run()
    check("undo restores every file to its original path", f1.read_bytes() == b"1" and f2.read_bytes() == b"2" and not res.skipped, res.skipped)
    check("undo recreates removed folders", (root / "e" / "s").is_dir())
    check("undo with nothing left reports an error", undo_log.undo_last_run().error is not None)

# ---- planner: duration-aware duplicate grouping ----
def di(name, dur, artist="Art", title="Song"):
    t = TrackInfo(path=Path("/m/" + name), ext=".mp3", artist=artist, title=title, duration=dur)
    return PlanItem(track=t, dest_path=Path("/d/" + name))
def flag(items):
    planner._flag_duplicates(items, fingerprint=False)
l1, l2 = di("a.mp3", 210.0), di("b.mp3", 285.0)
flag([l1, l2]); check("3:30 vs 4:45 not grouped", l1.status != Status.DUPLICATE and l2.status != Status.DUPLICATE)
l1, l2 = di("a.mp3", 210.0), di("b.mp3", 211.0)
flag([l1, l2]); check("3:30 vs 3:31 grouped", l1.status == Status.DUPLICATE and l1.group_id == l2.group_id)
l1, l2 = di("a.mp3", 210.0), di("b.mp3", 216.0)
flag([l1, l2]); check("beyond tolerance (6s) not grouped", l1.status != Status.DUPLICATE)
l1, l2 = di("a.mp3", 210.0), di("b.mp3", None)
flag([l1, l2]); check("unknown length still grouped, with a note", l2.status == Status.DUPLICATE and "length unknown" in l2.notes.lower() and "length unknown" not in l1.notes.lower(), l2.notes)
f1, f2 = di("01 - Intro.mp3", 30.0, None, ""), di("Intro.mp3", 200.0, None, "")
f1.track.title = f2.track.title = None
flag([f1, f2]); check("filename tier: same name, different lengths not grouped", f1.status != Status.DUPLICATE)

# ---- mover: a destination occupied by another pending item's source ----
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    (root / "in").mkdir()
    # chain: a -> b's spot, b -> c's spot, c -> free spot; listed in the "wrong" order on purpose
    fa, fb, fc = root / "in" / "a.mp3", root / "in" / "b.mp3", root / "in" / "c.mp3"
    for f, data in ((fa, b"A"), (fb, b"B"), (fc, b"C")): f.write_bytes(data)
    free = root / "out" / "c.mp3"
    chain = [item(fa, fb), item(fb, fc), item(fc, free)]
    MoveWorker(chain, root).run()
    check("chained moves all succeed", not any(i.move_error for i in chain) and fb.read_bytes() == b"A" and fc.read_bytes() == b"B" and free.read_bytes() == b"C")
    # circular swap: nothing overwritten, both reported failed with a clear reason
    sa, sb = root / "in" / "sa.mp3", root / "in" / "sb.mp3"
    sa.write_bytes(b"SA"); sb.write_bytes(b"SB")
    swap = [item(sa, sb), item(sb, sa)]
    seen = []
    w = MoveWorker(swap, root); w.finished_move.connect(seen.append); w.run()
    check("swap: nothing overwritten", sa.read_bytes() == b"SA" and sb.read_bytes() == b"SB")
    check("swap: both reported failed with a reason", len(seen[0].failed) == 2 and all("circular" in (i.move_error or "") for i in swap))
    # a blocker that is itself unmovable (its own destination is taken by an unrelated file)
    ba, bb, other = root / "in" / "ba.mp3", root / "in" / "bb.mp3", root / "out" / "other.mp3"
    ba.write_bytes(b"BA"); bb.write_bytes(b"BB"); other.write_bytes(b"OTHER")
    stuck = [item(ba, bb), item(bb, other)]
    MoveWorker(stuck, root).run()
    check("blocked chain: no file lost or overwritten", ba.read_bytes() == b"BA" and bb.read_bytes() == b"BB" and other.read_bytes() == b"OTHER")
    check("blocked chain: both reported failed", all(i.move_error for i in stuck))

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
