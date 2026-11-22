# PyInstaller build of PR7-Z: pyinstaller pr7z.spec  ->  dist/PR7-Z/PR7-Z.exe
# A folder build (not one-file) so Explorer's right-click actions start instantly.
import re
from pathlib import Path

root = Path(SPECPATH)
version = re.search(r'__version__ = "([^"]+)"', (root / "pr7z" / "__init__.py").read_text()).group(1)

a = Analysis(
    [str(root / "tools" / "launcher.py")],
    pathex=[str(root)],
    datas=[
        (str(root / "pr7z" / "fonts"), "pr7z/fonts"),
        (str(root / "pr7z" / "icons"), "pr7z/icons"),
        (str(root / "engine"), "engine"),
    ],
    hiddenimports=["psutil"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PR7-Z", console=False,
          icon=str(root / "pr7z" / "icons" / "app.ico"), version=None)
coll = COLLECT(exe, a.binaries, a.datas, name="PR7-Z")
