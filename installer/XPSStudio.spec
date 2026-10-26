# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from pathlib import Path
root = Path(SPECPATH).parent

datas = []
datas += collect_data_files('lmfit')


a = Analysis(
    [str(root / 'windows_launcher.py')],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['openpyxl', 'xlrd', 'matplotlib.backends.backend_pdf',
                   'matplotlib.backends.backend_svg', 'matplotlib.backends.backend_ps'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6'],
    noarchive=False,
    optimize=0,
)
# Qt needs the Windows ICU API, not the incompatible Poppler DLL on the build PATH.
a.binaries = [item for item in a.binaries if item[0].lower() != 'icuuc.dll']
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='XPSStudio',
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
    icon=[str(root / 'installer' / 'xps.ico')],
)
