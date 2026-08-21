# Music Library Organizer

Scans a music library folder, reads existing audio tags (via `mutagen`), and
reorganizes files into `Album Artist/Album/original filename` — moving files,
never renaming or retagging them. Duplicates and low-confidence guesses are
flagged in a preview screen; nothing moves until you explicitly confirm.

## Developing on macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

PySide6 runs natively on macOS, so you can fully exercise the scan → preview
→ confirm → move workflow during development. The window will render with
Mac-native widget styling while developing; that's expected. On Windows it
will render with Windows-native styling instead, since the app never forces
a specific Qt style — it leaves that to the platform.

## Shipping to Windows

This must be done **on a Windows machine or VM** — PyInstaller builds
platform-specific binaries and cannot cross-compile a Windows `.exe` from
macOS. There's nothing left to change in the code; these are the steps to
turn this folder into a distributable `.exe`.

1. **Copy the project to the Windows machine.** Zip this folder and transfer
   it (or clone it there if it's in git). Exclude `venv/` and `__pycache__/`
   if you zip manually — they're mac-specific and will be recreated.
2. **Install Python 3.11+ on Windows** from [python.org](https://www.python.org/downloads/windows/)
   if it isn't already there. On the installer's first screen, check **"Add
   python.exe to PATH"**.
3. **Open PowerShell** and `cd` into the copied project folder.
4. **Create and activate a fresh Windows venv** (the mac one won't work
   here):
   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```
5. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   pip install pyinstaller
   ```
6. **Build the executable:**
   ```powershell
   pyinstaller music_organizer.spec
   ```
7. **Find and test it** at `dist\MusicLibraryOrganizer.exe`. Double-click it
   (don't run it from PowerShell this time — you want to confirm it works
   the way an end user will launch it). Confirm: it opens with a native
   Windows look (in-window menu bar, native folder picker), a scan/preview/
   move cycle works end to end, and closing the window while a scan is
   running shows the "cancel and quit?" prompt instead of hanging.
8. **Expect a SmartScreen warning the first time you run it.** Since the
   `.exe` isn't code-signed, Windows will likely show "Windows protected
   your PC." Click **More info → Run anyway**. This is normal for
   unsigned PyInstaller output and not a bug — anyone you send the `.exe`
   to will see it once too. Antivirus tools occasionally flag unsigned
   PyInstaller binaries as suspicious for the same reason (a known false
   positive class, not a real issue with this app); code-signing is the
   only way to avoid it and is out of scope unless you plan wider
   distribution.
9. **Distribute** by zipping `dist\MusicLibraryOrganizer.exe` and sending
   it — it's self-contained and doesn't need Python installed on the
   receiving machine.

## Supported formats

MP3, FLAC, M4A/AAC, WAV, OGG, OGA, Opus — tag reading is handled by
`mutagen`, which supports ID3 (MP3), Vorbis comments (FLAC/Ogg), and MP4
atoms (M4A/AAC). WAV tag support is best-effort since not all WAV files
carry embedded tags.

## What the app does and does not do

- **Does**: read tags, move files into a new folder structure, clean up
  now-empty folders left behind in the source afterward.
- **Does not**: write/modify/strip any audio tags, rename files, copy files
  (it always moves), or auto-resolve duplicates/conflicts.
