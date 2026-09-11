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

Automated via GitHub Actions — no Windows machine needed to build.
`.github/workflows/build.yml` runs `pyinstaller music_organizer.spec` on a
`windows-latest` hosted runner on every push, and on a version tag (`v1.2.3`)
also publishes a GitHub Release with `MusicLibraryOrganizer.exe` attached.

**To ship a new version:**
```bash
# bump organizer/__version__.py first, then:
git tag v0.1.1
git push origin v0.1.1
```
That triggers the build + release. Download the `.exe` from the release's
Assets, or — once someone's already running an earlier version — the app
checks for updates on launch itself (see below) and offers to install the
new one with no manual download needed.

**First run on Windows still needs one manual step**: since the `.exe` isn't
code-signed, Windows will show "Windows protected your PC" (SmartScreen).
Click **More info → Run anyway**. This is normal for unsigned PyInstaller
output, not a bug. Antivirus tools occasionally flag unsigned PyInstaller
binaries as suspicious for the same reason (a known false-positive class);
code-signing is the only way to avoid it and is out of scope unless you plan
wider distribution.

## Self-update

The Windows `.exe` checks `github.com/ygb4520-cmd/music-library-organizer`'s
latest release on launch (silently — only interrupts you if there's actually
something new) and offers a one-click install via **Help → Check for
Updates...** too. This only does anything when running the built `.exe`; it's
a no-op when running from source (`python main.py`) during development.

## Supported formats

MP3, FLAC, M4A/AAC, WAV, OGG, OGA, Opus — tag reading is handled by
`mutagen`, which supports ID3 (MP3), Vorbis comments (FLAC/Ogg), and MP4
atoms (M4A/AAC). WAV tag support is best-effort since not all WAV files
carry embedded tags.

## What the app does and does not do

- **Does**: read tags, move files into a new folder structure, clean up
  now-empty folders left behind in the source afterward.
- **Does not by default**: write/modify/strip any audio tags, rename files,
  copy files (it always moves), or auto-resolve duplicates/conflicts.
- **Opt-in exception**: **Tools → Look Up Missing Metadata...** searches
  MusicBrainz's free database for files with no tag data at all, guessing
  artist/title from the filename. Nothing is written until you review and
  explicitly confirm matches in a preview screen — this is the one place in
  the app that writes tags, and only for files you've checked.

## Looking up missing metadata

For files with no tags whatsoever (not just incomplete — genuinely no tag
data mutagen can read), **Tools → Look Up Missing Metadata...**:

1. Guesses artist/title from the filename (same pattern-matching already
   used for folder-placement fallback — e.g. `Artist - Title.mp3`).
2. Searches MusicBrainz's free API (no key needed) for a matching recording.
3. Shows every result in a preview table with a confidence score. Matches
   scoring 80%+ are pre-checked; lower-confidence ones need a deliberate
   opt-in per row.
4. Only writes ARTIST/TITLE/ALBUM tags to files you leave checked, after one
   more explicit confirmation.

Accuracy depends entirely on the filename — garbled names ("track03.mp3")
or very obscure/independent releases not in MusicBrainz's database will
correctly come back with no match rather than a wrong guess. A more accurate
audio-fingerprinting fallback (identifies the song from its actual audio
content, not just the filename) is a possible future addition but isn't
built yet — it needs bundling an extra binary (`fpcalc`) and a free AcoustID
API key, real added complexity saved for if the filename-only approach
proves insufficient in practice.

## Support / Feedback

Found a bug or have a question? Open an issue: https://github.com/ygb4520-cmd/music-library-organizer/issues
