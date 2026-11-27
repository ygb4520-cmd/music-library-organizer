"""Checks (runnable on any OS with `python3 tests/test_hidden_console.py`) that fpcalc is started without a console window
on Windows, that other platforms are left alone, and that the third-party acoustid module is no longer patched."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from organizer import metadata_lookup as ml

fails = 0
def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name); fails += (not ok)

NO_WINDOW = 0x08000000

check("macOS/Linux: no extra Popen arguments", ml.hidden_window_popen_kwargs("darwin") == {} and ml.hidden_window_popen_kwargs("linux") == {})
win = ml.hidden_window_popen_kwargs("win32")
check("Windows: CREATE_NO_WINDOW requested", win.get("creationflags", 0) & NO_WINDOW == NO_WINDOW)

calls = []
class FakePopen:           # stands in for subprocess.Popen so nothing really runs
    returncode = 0
    def __init__(self, command, **kw): calls.append((command, kw))
    def communicate(self, timeout=None): return b"DURATION=12.5\nFINGERPRINT=AQAAabc\n", b""

duration, fp = ml.run_fpcalc("x.mp3", fpcalc="fpcalc.exe", platform="win32", popen=FakePopen)
command, kw = calls[-1]
check("Windows: run_fpcalc starts the process hidden", kw.get("creationflags", 0) & NO_WINDOW == NO_WINDOW)
check("run_fpcalc passes the file and captures stdout", command[0] == "fpcalc.exe" and command[-1] == "x.mp3" and kw.get("stdout") == subprocess.PIPE)
check("run_fpcalc parses duration and fingerprint", duration == 12.5 and fp == b"AQAAabc")
ml.run_fpcalc("x.mp3", fpcalc="fpcalc", platform="darwin", popen=FakePopen)
check("macOS: run_fpcalc adds no creationflags/startupinfo", "creationflags" not in calls[-1][1] and "startupinfo" not in calls[-1][1])

def raises(exc, fn):
    try: fn()
    except exc: return True
    except Exception: return False
    return False
class Missing:
    def __init__(self, *a, **k): raise FileNotFoundError("no such file")
check("missing fpcalc -> FpcalcMissingError", raises(ml.FpcalcMissingError, lambda: ml.run_fpcalc("x", fpcalc="nope", popen=Missing)))
class Bad(FakePopen):
    returncode = 1
check("fpcalc non-zero exit -> FpcalcFailedError", raises(ml.FpcalcFailedError, lambda: ml.run_fpcalc("x", fpcalc="f", popen=Bad)))
check("garbage output -> FpcalcFailedError", raises(ml.FpcalcFailedError, lambda: ml.parse_fpcalc_output(b"nonsense")))

check("importing the module no longer touches pyacoustid's subprocess", ml.acoustid.subprocess is subprocess)
check("no import-time patch function remains", not hasattr(ml, "hide_helper_console_windows"))
print("\n%s" % ("all passed" if not fails else "%d failed" % fails)); sys.exit(1 if fails else 0)
