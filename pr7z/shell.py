"""Windows Explorer integration: the right-click menu and "Open with" for archives.

The menu is PR7ZShell.dll (shellext/), a shell extension like 7-Zip's 7-zip.dll: it shows the real
names ('Add to "Stems.7z"'), archive-only items only on archives, and passes every selected file in
one launch. It reads its settings from HKCU\\Software\\Paragon\\PR7-Z\\Shell (written here). Without
the DLL (running from source, not built) a fixed-text registry menu is used instead.

Everything lives under HKEY_CURRENT_USER (this user only, no admin rights), and the unregister
functions remove exactly what the register functions wrote.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import engine

PROGID = "Paragon.PR7Z.Archive"
MENU_KEY = "PR7Z"
CLSID = "{ED2155D5-4754-4F17-A401-780852864C71}"   # PR7ZShell.dll's class (fixed: never change it)
HANDLER = "PR7-Z"
SETTINGS_KEY = r"Software\Paragon\PR7-Z\Shell"
# The DLL's menu items, in its bit order (shellext/PR7ZShell.cpp, enum Item).
MENU_ITEMS = ["Open archive", "Open archive >", "Extract files...", "Extract Here", 'Extract to "name\\"',
              "Test archive", "Add to archive...", "Compress and email...", 'Add to "name.7z"',
              'Compress to "name.7z" and email', 'Add to "name.zip"', 'Compress to "name.zip" and email', "CRC SHA >"]
ALL_ITEMS = (1 << len(MENU_ITEMS)) - 1
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


def shell_dll() -> Path | None:
    """PR7ZShell.dll: next to the app when built, or shellext/build/... when running from source."""
    env = os.environ.get("PR7Z_SHELLEXT")
    if env:
        return Path(env) if Path(env).is_file() else None
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for c in (base / "shellext" / "PR7ZShell.dll", base / "shellext" / "build" / "Release" / "PR7ZShell.dll"):
        if c.is_file():
            return c
    return None


def command_line() -> str:
    """How the DLL starts PR7-Z (it appends the action and the files)."""
    parts = launcher()
    return " ".join(f'"{p}"' if (" " in p or p.endswith((".exe", ".EXE"))) else p for p in parts)


def read_settings() -> dict:
    out = {"cascaded": True, "items": ALL_ITEMS}
    if not available():
        return out
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
    except OSError:
        return out
    for name, key in (("Cascaded", "cascaded"), ("Items", "items")):
        try:
            v, _ = winreg.QueryValueEx(k, name)
            out[key] = bool(v) if key == "cascaded" else int(v)
        except OSError:
            pass
    winreg.CloseKey(k)
    return out


def write_settings(cascaded: bool | None = None, items: int | None = None):
    import winreg
    k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, SETTINGS_KEY, 0, winreg.KEY_WRITE)
    winreg.SetValueEx(k, "Command", 0, winreg.REG_SZ, command_line())
    winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon().rsplit(",", 1)[0])
    if cascaded is not None:
        winreg.SetValueEx(k, "Cascaded", 0, winreg.REG_DWORD, int(cascaded))
    if items is not None:
        winreg.SetValueEx(k, "Items", 0, winreg.REG_DWORD, int(items) & ALL_ITEMS)
    winreg.CloseKey(k)


def register_menu():
    """The right-click menu: the shell extension if it's here, else the fixed-text registry menu."""
    import winreg
    root = winreg.HKEY_CURRENT_USER
    dll = shell_dll()
    if dll is None:
        _menu(root, r"Software\Classes\*", FILE_VERBS)
        _menu(root, r"Software\Classes\Directory", FOLDER_VERBS)
        _notify()
        return
    _remove_static_menu(root)
    s = read_settings()
    write_settings(s["cascaded"], s["items"])
    _set(root, rf"Software\Classes\CLSID\{CLSID}", {"": "PR7-Z Shell Extension"})
    _set(root, rf"Software\Classes\CLSID\{CLSID}\InprocServer32", {"": str(dll), "ThreadingModel": "Apartment"})
    for base in ("*", "Directory"):
        _set(root, rf"Software\Classes\{base}\shellex\ContextMenuHandlers\{HANDLER}", {"": CLSID})
    _set(root, r"Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved",
         {CLSID: "PR7-Z Shell Extension"})
    _notify()


def _remove_static_menu(root):
    for base in (r"Software\Classes\*", r"Software\Classes\Directory"):
        _delete_tree(root, f"{base}\\shell\\{MENU_KEY}")


def unregister_menu():
    """Removes both kinds of menu. Explorer keeps a loaded DLL until it restarts or unloads it."""
    import winreg
    root = winreg.HKEY_CURRENT_USER
    _remove_static_menu(root)
    for base in ("*", "Directory"):
        _delete_tree(root, rf"Software\Classes\{base}\shellex\ContextMenuHandlers\{HANDLER}")
    _delete_tree(root, rf"Software\Classes\CLSID\{CLSID}")
    try:
        k = winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved", 0,
                           winreg.KEY_SET_VALUE)
        winreg.DeleteValue(k, CLSID)
        winreg.CloseKey(k)
    except OSError:
        pass
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


def menu_registered() -> str:
    """'extension', 'basic' (the fixed-text registry menu) or '' (none)."""
    if not available():
        return ""
    import winreg
    for kind, path in (("extension", rf"Software\Classes\*\shellex\ContextMenuHandlers\{HANDLER}"),
                       ("basic", rf"Software\Classes\*\shell\{MENU_KEY}")):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, path))
            return kind
        except OSError:
            pass
    return ""


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
