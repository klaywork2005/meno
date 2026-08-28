# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build configuration for Meno.

Build with ``pyinstaller meno.spec``, or run ``build.ps1``, which does this and
then compiles the installer.

Two configuration choices:

*one directory, not one file*
    ``--onefile`` produces a self-extracting executable that unpacks the whole
    bundle to a temporary directory on every launch, which delays startup by
    seconds and is a common antivirus heuristic trigger. The output is
    packaged by an installer, so the directory is not user-visible.

*windowed, not console*
    ``console=False`` suppresses the console window. Consequently
    ``meno/__main__.py`` installs a crash handler that shows a message box; an
    unhandled exception would otherwise produce no output.
"""

from pathlib import Path

BUILD_DIR = Path(SPECPATH)

# The PySide6 hook collects every Qt module not explicitly excluded. The front
# end uses QtCore, QtGui and QtWidgets only; none of the modules below are
# imported anywhere in meno.
EXCLUDED_QT = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNfc",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtPositioning", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtTest",
    "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    # No module opens a socket. Excluding this also excludes Qt's bundled
    # OpenSSL, about 8MB.
    "PySide6.QtNetwork",
]

# Packages collected incidentally and unused at runtime.
EXCLUDED_OTHER = [
    "tkinter", "matplotlib", "PIL", "scipy", "pandas", "pytest",
    "setuptools", "pip", "IPython", "notebook",
]

# main.py, not meno/__main__.py. PyInstaller executes the entry script as a
# top-level module, so a module using relative imports fails at startup with
# "attempted relative import with no known parent package". The shim at the
# repository root imports the package by name and works either way.
a = Analysis(
    ["main.py"],
    pathex=[str(BUILD_DIR)],
    binaries=[],
    # Destination "assets" matches config.asset_path(), which resolves under
    # sys._MEIPASS/assets when frozen. Both must be changed together.
    datas=[("meno/assets", "assets")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED_QT + EXCLUDED_OTHER,
    noarchive=False,
)

# Two large libraries that are unreachable from this application.
#
# ffmpeg is OpenCV's decoder for video files. Meno reads a webcam through
# DirectShow and writes PNGs through imwrite, and opens no video files. 29MB.
#
# opengl32sw is Qt's software OpenGL implementation, used on machines with no
# usable GL driver. Qt Widgets paints through the raster engine and requests no
# GL context, so it is never loaded. 20MB.
#
# Remove the matching entry if a future feature requires either.
UNUSED_BINARIES = ("opencv_videoio_ffmpeg", "opengl32sw")

a.binaries = [entry for entry in a.binaries
              if not any(name in entry[0].lower() for name in UNUSED_BINARIES)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Meno",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX-packed Qt DLLs trigger antivirus false positives
    console=False,
    disable_windowed_traceback=False,
    icon=str(BUILD_DIR / "meno" / "assets" / "meno.ico"),
    version=str(BUILD_DIR / "installer" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Meno",
)
