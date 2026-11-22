"""Windows Explorer integration: the right-click menu and "Open with" for archives.

Everything lives under HKEY_CURRENT_USER\\Software\\Classes (this user only, no admin rights),
and unregister() removes exactly what register() wrote.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import engine

PROGID = "Paragon.PR7Z.Archive"
MENU_KEY = "PR7Z"
# (key, label, command switch); keys sort in this order in the menu.
FILE_VERBS = [
    ("a_open", "Open archive", "--open"),
    ("b_extract", "Extract files...", "--extract"),
    ("c_here", "Extract Here", "--extract-here"),
    ("d_to", 'Extract to "<archive name>\\"', "--extract-to"),
    ("e_test", "Test archive", "--test"),
    ("f_add", "Add to archive...", "--add"),
    ("g_add7z", 'Add to "<name>.7z"', "--add-7z"),
    ("h_addzip", 'Add to "<name>.zip"', "--add-zip"),
    ("i_hash", "CRC SHA", "--hash"),
]
FOLDER_VERBS = [v for v in FILE_VERBS if v[2] in ("--add", "--add-7z", "--add-zip", "--hash")]
ASSOCIATE_EXTS = sorted(engine.ARCHIVE_EXTS - {"img", "msi", "pkg", "apk", "jar", "xpi", "chm", "001"})


def launcher() -> list[str]:
    """How Explorer should start PR7-Z: the built exe, or pythonw -m pr7z when run from source."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else py), "-m", "pr7z"]


def _cmd(switch: str) -> str:
    parts = [f'"{p}"' if " " in p or not p.startswith("-") else p for p in launcher()]
    return " ".join(parts) + f' {switch} "%1"'


def icon() -> str:
    if getattr(sys, "frozen", False):
        return f"{sys.executable},0"
    return str(Path(__file__).parent / "icons" / "app.ico")


def available() -> bool:
    return os.name == "nt"


def _set(root, path: str, values: dict):
    import winreg
    k = winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE)
    for name, val in values.items():
        if val is None:
            winreg.SetValueEx(k, name, 0, winreg.REG_NONE, b"")
        else:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
    winreg.CloseKey(k)


def _delete_tree(root, path: str):
    import winreg
    try:
        k = winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return
    while True:
        try:
            sub = winreg.EnumKey(k, 0)
        except OSError:
            break
        _delete_tree(root, f"{path}\\{sub}")
    winreg.CloseKey(k)
    winreg.DeleteKey(root, path)


def _menu(root, base: str, verbs):
    _set(root, f"{base}\\shell\\{MENU_KEY}", {"MUIVerb": "PR7-Z", "Icon": icon(), "SubCommands": ""})
    for key, label, switch in verbs:
        _set(root, f"{base}\\shell\\{MENU_KEY}\\shell\\{key}", {"": label, "MUIVerb": label})
        _set(root, f"{base}\\shell\\{MENU_KEY}\\shell\\{key}\\command", {"": _cmd(switch)})


def register_menu():
    import winreg
    root = winreg.HKEY_CURRENT_USER
    _menu(root, r"Software\Classes\*", FILE_VERBS)
    _menu(root, r"Software\Classes\Directory", FOLDER_VERBS)
    _notify()


def unregister_menu():
    import winreg
    root = winreg.HKEY_CURRENT_USER
    for base in (r"Software\Classes\*", r"Software\Classes\Directory"):
        _delete_tree(root, f"{base}\\shell\\{MENU_KEY}")
    _notify()


def register_open_with():
    """PR7-Z under 'Open with' for archive types (Windows lets the user pick the default)."""
    import winreg
    root = winreg.HKEY_CURRENT_USER
    _set(root, rf"Software\Classes\{PROGID}", {"": "Archive (PR7-Z)"})
    _set(root, rf"Software\Classes\{PROGID}\DefaultIcon", {"": icon()})
    _set(root, rf"Software\Classes\{PROGID}\shell\open\command", {"": _cmd("--open")})
    for ext in ASSOCIATE_EXTS:
        _set(root, rf"Software\Classes\.{ext}\OpenWithProgids", {PROGID: None})
    _notify()


def unregister_open_with():
    import winreg
    root = winreg.HKEY_CURRENT_USER
    for ext in ASSOCIATE_EXTS:
        try:
            k = winreg.OpenKey(root, rf"Software\Classes\.{ext}\OpenWithProgids", 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(k, PROGID)
            winreg.CloseKey(k)
        except OSError:
            pass
    _delete_tree(root, rf"Software\Classes\{PROGID}")
    _notify()


def menu_registered() -> bool:
    if not available():
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\*\shell\{MENU_KEY}"))
        return True
    except OSError:
        return False


def open_with_registered() -> bool:
    if not available():
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROGID}"))
        return True
    except OSError:
        return False


def _notify():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass
