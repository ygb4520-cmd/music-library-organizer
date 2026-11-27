"""Checks (python3 tests/test_lookup_status.py) that metadata lookups report WHY they found nothing, without hitting the network."""
import logging, os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import acoustid
from organizer import metadata_lookup as ml
from organizer.metadata_lookup import LookupStatus as S

fails = 0
def check(name, ok, extra=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (("  " + str(extra)) if (extra and not ok) else "")); fails += (not ok)

ml._acoustid_limiter.interval = 0
_real_fingerprint_lookup = ml.fingerprint_lookup
logs = []
class H(logging.Handler):
    def emit(self, r): logs.append(r)
ml.logger.addHandler(H())

def status(fp=None, response=None, lookup_exc=None):
    def run_fpcalc(path):
        if isinstance(fp, Exception): raise fp
        return 10.0, b"AQ"
    def lookup(*a, **k):
        if lookup_exc: raise lookup_exc
        return response
    ml.run_fpcalc, acoustid.lookup = run_fpcalc, lookup
    return ml.fingerprint_lookup(Path("x.mp3"), "key")

check("empty key -> NO_API_KEY", ml.fingerprint_lookup(Path("x.mp3"), "").status is S.NO_API_KEY)
check("fpcalc missing -> FPCALC_MISSING", status(fp=ml.FpcalcMissingError("gone")).status is S.FPCALC_MISSING)
check("fpcalc fails -> CORRUPT_AUDIO", status(fp=ml.FpcalcFailedError("bad")).status is S.CORRUPT_AUDIO)
bad = status(response={"status": "error", "error": {"code": 4, "message": "invalid API key"}})
check("wrong key -> BAD_KEY", bad.status is S.BAD_KEY and "invalid API key" in bad.message, bad)
check("BAD_KEY is logged", any("rejected" in r.getMessage() for r in logs))
check("rate limit -> RATE_LIMITED", status(response={"status": "error", "error": {"code": 14, "message": "rate limit exceeded"}}).status is S.RATE_LIMITED)
check("network failure -> NETWORK_ERROR", status(lookup_exc=acoustid.WebServiceError("HTTP request failed: boom")).status is S.NETWORK_ERROR)
check("timeout -> NETWORK_ERROR", status(lookup_exc=TimeoutError("slow")).status is S.NETWORK_ERROR)
crash = status(lookup_exc=RuntimeError("odd"))
check("unexpected error -> UNKNOWN_ERROR with traceback logged", crash.status is S.UNKNOWN_ERROR and any(r.exc_info for r in logs))
check("song absent from the database -> NO_MATCH", status(response={"status": "ok", "results": []}).status is S.NO_MATCH)
ok = status(response={"status": "ok", "results": [{"score": 0.95, "recordings": [{"id": "1", "title": "T", "artists": [{"name": "A"}]}]}]})
check("a match -> OK with candidate", ok.status is S.OK and ok.candidates[0].score == 95)
check("fingerprint_candidates stays list-returning and fails closed", status(fp=ml.FpcalcMissingError("x")).candidates == [] and ml.fingerprint_candidates(Path("x"), "key") == [])

# best_match_with_status: real problems win over plain "no match"
ml.search_with_status = lambda a, t, timeout=10.0: ml.LookupResult([], S.NO_MATCH)
m, r = ml.best_match_with_status(Path("a - b.mp3"), api_key="key")
ml.fingerprint_lookup = lambda *a, **k: ml.LookupResult([], S.BAD_KEY, "invalid API key")
m, r = ml.best_match_with_status(Path("a - b.mp3"), api_key="key")
check("wrong key surfaces as BAD_KEY", m is None and r.status is S.BAD_KEY)
ml.fingerprint_lookup = lambda *a, **k: ml.LookupResult([], S.NO_MATCH)
m, r = ml.best_match_with_status(Path("a - b.mp3"), api_key="key")
check("really absent -> NO_MATCH", m is None and r.status is S.NO_MATCH)
ml.search_with_status = lambda a, t, timeout=10.0: ml.LookupResult([], S.NETWORK_ERROR, "down")
m, r = ml.best_match_with_status(Path("a - b.mp3"), api_key="")
check("filename search network error surfaces", m is None and r.status is S.NETWORK_ERROR)
ml.fingerprint_lookup = _real_fingerprint_lookup
m, r = ml.best_match_with_status(Path("a - b.mp3"), api_key="", fingerprint_only=True)
check("fingerprint-only without key -> NO_API_KEY", m is None and r.status is S.NO_API_KEY)

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # e.g. a headless box without the system GL libraries
    print('SKIP dialog checks (Qt widgets unavailable: %s)' % exc)
else:
    # the preview dialog shows the reasons
    app = QApplication.instance() or QApplication([])
    from organizer.models import TrackInfo
    from organizer.ui import metadata_preview_dialog as mpd
    t1, t2 = TrackInfo(path=Path("/m/one.mp3"), ext=".mp3"), TrackInfo(path=Path("/m/two.mp3"), ext=".mp3")
    dlg = mpd.MetadataPreviewDialog([(t1, None), (t2, None)], reasons={t1.path: ml.LookupResult([], S.BAD_KEY, "invalid API key")})
    text = dlg.reason_label.text()
    check("dialog shows BAD_KEY reason", "BAD_KEY" in text)
    check("dialog still shows NO_MATCH for the other file", "NO_MATCH" in text)
print("\n%s" % ("all passed" if not fails else "%d failed" % fails)); sys.exit(1 if fails else 0)
