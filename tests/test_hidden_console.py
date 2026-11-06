"""Checks (runnable on any OS with `python3 tests/test_hidden_console.py`) that fpcalc is started without a console window
on Windows and that other platforms are left alone."""
import os, subprocess, sys, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from organizer import metadata_lookup as ml

fails = 0
def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name); fails += (not ok)

class FakeAcoustid:        # stands in for the pyacoustid module
    subprocess = subprocess

seen = {}
real = subprocess.Popen
class Spy:                 # stands in for subprocess.Popen so nothing really runs
    def __init__(self, *a, **kw): seen.update(kw)
subprocess.Popen = Spy
try:
    fake = FakeAcoustid()
    # non-Windows: nothing changes
    check("macOS/Linux: not touched", ml.hide_helper_console_windows(fake, platform="darwin") is False and fake.subprocess is subprocess)
    # Windows: swapped, and Popen gains the hide flags
    check("Windows: swap made", ml.hide_helper_console_windows(fake, platform="win32") is True and fake.subprocess is not subprocess)
    fake.subprocess.Popen(["fpcalc.exe", "x.mp3"], stdout=fake.subprocess.PIPE, stderr=None)
    check("Windows: CREATE_NO_WINDOW added", seen.get("creationflags", 0) & 0x08000000 == 0x08000000)
    check("Windows: caller's own arguments kept", seen.get("stdout") == subprocess.PIPE)
    seen.clear()
    fake.subprocess.Popen(["x"], creationflags=0x200)
    check("Windows: existing flags are combined, not replaced", seen["creationflags"] == (0x200 | 0x08000000))
    check("shim still offers PIPE and the other subprocess names", fake.subprocess.PIPE == subprocess.PIPE and hasattr(fake.subprocess, "CalledProcessError"))
    check("the app-wide subprocess.Popen is untouched", subprocess.Popen is Spy)
    check("module without a subprocess attribute is skipped", ml.hide_helper_console_windows(types.SimpleNamespace(), platform="win32") is False)
finally:
    subprocess.Popen = real
check("importing the module on this OS left the real pyacoustid alone", ml.acoustid.subprocess is subprocess or sys.platform == "win32")
print("\n%s" % ("all passed" if not fails else "%d failed" % fails)); sys.exit(1 if fails else 0)
