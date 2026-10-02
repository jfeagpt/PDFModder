# -*- mode: python ; coding: utf-8 -*-
"""Paquete de carpeta Windows x64; conserve las DLL de Qt reemplazables."""
from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH)
debug_console = os.environ.get('PDFMODDER_DEBUG_CONSOLE') == '1'
# Do not collect DLLs from unrelated tools on the developer's PATH. In
# particular Poppler's ICU exports versioned symbols incompatible with Qt's
# Windows ICU API. Qt must use the ICU supplied by supported Windows 11.
windows_root = Path(os.environ.get('SystemRoot', 'C:/Windows')).resolve()
if os.name == 'nt':
    os.environ['PATH'] = os.pathsep.join(str(path) for path in (
        Path(sys.executable).parent, Path(sys.base_prefix),
        Path(sys.base_prefix) / 'DLLs', windows_root / 'System32', windows_root,
    ))
delivery = root / 'build' / 'delivery'
if not (delivery / 'licenses' / 'INVENTARIO.json').is_file():
    raise SystemExit('Ejecute scripts/collect_licenses.py antes de empaquetar.')

datas = [
    (str(delivery / 'licenses'), 'licenses'),
    (str(delivery / 'source'), 'source'),
    (str(root / 'LICENSE'), '.'),
]
for name in ('docs', 'examples', 'assets'):
    if (root / name).is_dir():
        datas.append((str(root / name), name))
if (root / 'README.md').is_file():
    datas.append((str(root / 'README.md'), '.'))
datas += collect_data_files('pymupdf')
datas += collect_data_files('pyhanko')
datas += collect_data_files('pyhanko_certvalidator')
datas += collect_data_files('tzdata')
datas += copy_metadata('pyHanko', recursive=True)
for package in ('PyMuPDF', 'fonttools', 'pypdf', 'Pillow', 'numpy', 'PySide6', 'PySide6_Essentials', 'shiboken6'):
    datas += copy_metadata(package)

a = Analysis(
    [str(root / 'run_pdfmodder.py')],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=['pymupdf', 'pypdf', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'tkinter'],
    noarchive=False,
)
if os.name == 'nt':
    allowed_binary_roots = (Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), windows_root)
    unexpected = [(name, source) for name, source, kind in a.binaries
                  if not any(Path(source).resolve().is_relative_to(base) for base in allowed_binary_roots)]
    if unexpected:
        raise SystemExit(f'DLL ajenas al entorno Python/Windows: {unexpected}')
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDFModder',
    debug=debug_console,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=debug_console,
    disable_windowed_traceback=False,
    contents_directory='_internal',
    icon=str(root / 'assets' / 'icons' / 'pdfmodder.ico'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PDFModder')
