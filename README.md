# Music Library Organizer

Scans a music library folder, reads existing audio tags (via `mutagen`), and
reorganizes files into `Album Artist/Album/original filename` — moving files,
never renaming or retagging them. Duplicates and low-confidence guesses are
flagged in a preview screen; nothing moves until you explicitly confirm.

## Download

**Windows**: go to **[the latest release](https://github.com/ygb4520-cmd/music-library-organizer/releases/latest)**,
scroll to **Assets**, and click `MusicLibraryOrganizer.exe`. Run it — if
SmartScreen warns "Windows protected your PC," click **More info** → **Run
anyway** (normal for this unsigned build, not a bug). Once installed, it
checks for updates itself.

**Mac**: there's no separate download — this app only ships a compiled
build for Windows. On a Mac, run it from source instead (a few one-time
Terminal commands, not a double-click app) — see below.

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
- **Opt-in exceptions**: **Tools → Look Up Missing Metadata...** and
  **Tools → Edit Tags...** — see below. Nothing is written to any file
  until you explicitly confirm in one of these two screens; everywhere
  else in the app stays strictly read-only.

## Looking up missing metadata

For files with no tags whatsoever (not just incomplete — genuinely no tag
data mutagen can read), **Tools → Look Up Missing Metadata...**:

1. Guesses artist/title from the filename (same pattern-matching already
   used for folder-placement fallback — e.g. `Artist - Title.mp3`).
2. Searches MusicBrainz's free API (no key needed) for a matching recording.
3. If that finds nothing confident **and** an AcoustID API key is set in
   Settings, falls back to audio fingerprinting — identifies the song from
   its actual audio content via the bundled `fpcalc` tool, regardless of
   filename. Slower (has to read the audio), which is why it's a fallback,
   not the default.
4. Shows every result in a preview table: which strategy found it ("Found
   Via" column), a confidence score, and editable Artist/Title/Album
   fields — fix anything before writing. Matches scoring 80%+ are
   pre-checked; lower-confidence ones need a deliberate opt-in per row.
   Click any column header to re-sort (default order is set in Settings).
5. For tracks with a "feat./ft./featuring" credit, a "Main Artist Only"
   checkbox lets you drop the featured artist when writing — defaults to
   your Settings preference, overridable per row. (Deliberately does *not*
   split on "&", ",", or "/" — those are too often part of a real single
   act's name, e.g. "Earth, Wind & Fire", to safely treat as separators.)
6. Only writes ARTIST/TITLE/ALBUM tags to files you leave checked, after one
   more explicit confirmation.

Some tracks genuinely won't be found by either strategy — very
obscure/independent releases may not be in MusicBrainz's or AcoustID's
databases at all. That correctly comes back as "no match" rather than a
wrong guess.

## Duplicate detection

Every scan checks for duplicates using three methods, in priority order —
the first one that groups a file with another wins:

1. **Audio fingerprint match** — identifies each track's actual audio
   content via the same AcoustID/fingerprinting integration as the metadata
   lookup above, so a re-encoded copy or a differently-tagged rip of the
   same song is still caught even if its filename and tags look nothing
   alike. Only runs when an AcoustID API key is set in Settings (see
   above) — leave it blank and this tier is skipped entirely, same as the
   metadata-lookup fallback. Slower, since it reads and fingerprints every
   file, which is the tradeoff for catching duplicates the other two
   methods miss.
2. **Tag match** — same artist + title (from tags).
3. **Filename match** — same filename, ignoring a leading track number and
   punctuation/case differences.

A popup lists every duplicate group found and which method caught it right
after the scan finishes. Duplicates are unchecked in the move list by
default (never auto-deleted or auto-resolved) — review the popup, then
recheck any file in the main list yourself if it isn't actually a
duplicate.

## Editing tags manually

**Tools → Edit Tags...** (select a file in the list first) opens a plain
form for Artist/Title/Album/Album Artist/Track # on that one file — for
fixing something by hand, independent of the online lookup. Same
explicit-Save-required rule as everywhere else that touches tags.

## Settings

**Tools → Settings...**:
- **Sort order** for the metadata-lookup results table (confidence
  high-to-low, low-to-high, or A-Z) — just the default; you can still
  re-sort by clicking any column header afterward.
- **Multi-artist default** — keep the full artist credit, or default to
  main-artist-only (per-row override always available in the lookup table).
- **AcoustID API key** — free at [acoustid.org/api-key](https://acoustid.org/api-key).
  Used for the metadata-lookup fingerprinting fallback and the
  fingerprint-based duplicate-detection tier; leave blank to skip both and
  rely on filename search / tag+filename duplicate matching alone.

## Support / Feedback

Found a bug or have a question? Open an issue: https://github.com/ygb4520-cmd/music-library-organizer/issues
