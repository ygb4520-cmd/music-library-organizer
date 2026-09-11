# PyInstaller spec for Windows build.
# Run on Windows: pyinstaller music_organizer.spec
# (mutagen and PySide6 are pure-python/binary wheels; no special hooks needed
# beyond PyInstaller's bundled PySide6 hook, which ships with recent PyInstaller.)
#
# bin/windows/fpcalc.exe is chromaprint's official fpcalc binary, bundled for
# the audio-fingerprinting metadata-lookup fallback. It lands at
# sys._MEIPASS/bin/windows/fpcalc.exe at runtime -- see
# organizer/metadata_lookup.py's fpcalc_path().

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('bin/windows/fpcalc.exe', 'bin/windows')],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MusicLibraryOrganizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
