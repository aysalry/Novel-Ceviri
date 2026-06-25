# -*- mode: python ; coding: utf-8 -*-
# Build with: pyinstaller NovelCeviri.spec
# Produces a single-file Windows executable in dist/NovelCeviri.exe

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app/gui/resources', 'app/gui/resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NovelCeviri',
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
    icon='app/gui/resources/icon.ico',
)
