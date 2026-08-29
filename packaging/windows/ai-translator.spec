# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ai-translator (Windows, onedir, windowed).
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent

datas = [
    (str(ROOT / "app" / "ui" / "themes"), "app/ui/themes"),
]

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
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
    [],
    exclude_binaries=True,
    name="ai-translator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ai-translator",
)
