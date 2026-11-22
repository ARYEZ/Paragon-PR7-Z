"""Check a real install of PR7-Z-Setup.exe (CI, Windows): python tools/verify_install.py installed|uninstalled

installed:   files, Start menu shortcut, uninstall entry, the Explorer menu registered to a hashed copy
             of the installed DLL with the installed PR7-Z as its command, the DLL building the menu for
             an archive (its own self-test, the same COM path Explorer uses), and "Open with".
uninstalled: all of that gone (retried for a while: the uninstaller finishes in a background copy).
"""
import ctypes
import os
import sys
import tempfile
import time
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pr7z import shell  # noqa: E402

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-Z"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-Z.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{9914C6C8-01EC-476F-845D-98F814A0426E}_is1"


def value(path: str, name: str = ""):
    try:
        k = winreg.OpenKey(HKCU, path)
    except OSError:
        return None
    try:
        return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None
    finally:
        winreg.CloseKey(k)


def check(ok: bool, what: str, problems: list):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        problems.append(what)


def installed() -> list:
    p: list = []
    exe = APP / "PR7-Z.exe"
    installed_dll = APP / "_internal" / "shellext" / "PR7ZShell.dll"
    for f in (exe, APP / "_internal" / "engine" / "7z.exe", installed_dll, APP / "unins000.exe"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(UNINSTALL, "DisplayName") == "Paragon PR7-Z", "Installed apps entry", p)
    check(value(rf"Software\Classes\*\shellex\ContextMenuHandlers\{shell.HANDLER}") == shell.CLSID,
          "menu handler on files", p)
    check(value(rf"Software\Classes\Directory\shellex\ContextMenuHandlers\{shell.HANDLER}") == shell.CLSID,
          "menu handler on folders", p)
    dll = value(rf"Software\Classes\CLSID\{shell.CLSID}\InprocServer32")
    check(bool(dll) and Path(dll).parent == shell.deploy_dir(), f"registered DLL is the per-user copy ({dll})", p)
    if dll and Path(dll).is_file() and installed_dll.is_file():
        check(Path(dll).read_bytes() == installed_dll.read_bytes(), "the copy is this build's DLL", p)
    cmd = value(shell.SETTINGS_KEY, "Command") or ""
    check(str(exe).lower() in cmd.lower(), f"menu starts the installed PR7-Z ({cmd})", p)
    check(value(r"Software\Classes\.7z\OpenWithProgids", shell.PROGID) is not None, '"Open with" for .7z', p)
    if dll and Path(dll).is_file():
        arc = Path(tempfile.mkdtemp()) / "Stems.7z"
        arc.write_bytes(b"7z")
        buf = ctypes.create_unicode_buffer(100_000)
        f = ctypes.WinDLL(dll).PR7Z_SelfTest
        f.argtypes, f.restype = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int
        n = f(str(arc), buf, len(buf))
        text = buf.value
        check(n > 0 and "\tPR7-Z" in text and 'Extract to "Stems\\"' in text and 'Add to "Stems_2.7z"' in text,
              "the installed menu builds for an archive", p)
        check(f'"{exe}"'.lower() in text.lower(), "its commands run the installed PR7-Z", p)
        print(text)
    return p


def uninstalled() -> list:
    deadline = time.time() + 60
    while True:
        p: list = []
        check(not (APP / "PR7-Z.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        check(value(rf"Software\Classes\*\shellex\ContextMenuHandlers\{shell.HANDLER}") is None, "menu removed", p)
        check(value(rf"Software\Classes\CLSID\{shell.CLSID}\InprocServer32") is None, "DLL registration removed", p)
        check(value(r"Software\Classes\.7z\OpenWithProgids", shell.PROGID) is None, '"Open with" removed', p)
        check(not list(shell.deploy_dir().glob("PR7ZShell-*.dll")), "the DLL copy removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
