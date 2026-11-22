"""The Explorer menu: the actions it starts (all platforms) and PR7ZShell.dll itself (Windows)."""

import ctypes
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pr7z import app, engine, operations, shell
from pr7z.engine import AddOptions
from pr7z.jobs import Job

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- the command line the menu uses
def test_parse_menu_actions(tmp_path):
    c = app.parse(["--add-to", r"D:\m\Stems_2.7z", "a", "b"])
    assert (c.action, c.param, c.paths) == ("--add-to", r"D:\m\Stems_2.7z", ["a", "b"])
    c = app.parse(["--hash:SHA256", "x"])
    assert (c.action, c.param, c.paths) == ("--hash", "SHA256", ["x"])
    assert app.parse(["--hash", "x"]).param == "*"
    c = app.parse(["--open-as", "#", "f.bin"])
    assert (c.action, c.param, c.paths) == ("--open-as", "#", ["f.bin"])
    with pytest.raises(SystemExit):
        app.parse(["--hash:NOPE", "x"])
    with pytest.raises(SystemExit):
        app.parse(["--add-to"])


def test_files_from_reads_and_removes_the_list(tmp_path):
    lst = tmp_path / "pr7z-list-1-2.txt"
    lst.write_text("C:\\a b\\one.txt\nC:\\ünï\\two.txt\n", encoding="utf-8")
    c = app.parse(["--add-to", "x.7z", "--files-from", str(lst)])
    assert c.paths == ["C:\\a b\\one.txt", "C:\\ünï\\two.txt"]
    assert not lst.exists()  # the shell extension's temp list is removed after reading
    keep = tmp_path / "mine.txt"
    keep.write_text("a\n")
    app.parse(["--add", "--files-from", str(keep)])
    assert keep.exists()     # anyone else's list is left alone


def _pr7z(args, **kw):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    return subprocess.run([sys.executable, "-m", "pr7z", *args], cwd=ROOT, env=env, capture_output=True, timeout=120,
                          **kw)


def test_add_to_then_extract_into(exe, tree, tmp_path, monkeypatch):
    """The menu's 'Add to "name.7z"' and 'Extract to "name\\"', run as the DLL runs them."""
    monkeypatch.setenv("PR7Z_7Z", exe)
    arc = tmp_path / "src_2.7z"
    r = _pr7z(["--add-to", str(arc), str(tree)])
    assert r.returncode == 0, r.stderr.decode()
    assert "src/sub/big.bin" in {i.path for i in engine.list_archive(str(arc), exe=exe).items}
    out = tmp_path / "src_2"
    r = _pr7z(["--extract-into", str(out), str(arc)])
    assert r.returncode == 0, r.stderr.decode()
    assert (out / "src" / "sub" / "big.bin").read_bytes() == (tree / "sub" / "big.bin").read_bytes()


def test_add_to_zip_format_follows_extension(exe, tree, tmp_path, monkeypatch):
    monkeypatch.setenv("PR7Z_7Z", exe)
    arc = tmp_path / "x.zip"
    assert _pr7z(["--add-to", str(arc), str(tree / "a.txt")]).returncode == 0
    assert engine.list_archive(str(arc), exe=exe).type == "zip"


def test_open_as_type(exe, tree, tmp_path, qapp, monkeypatch):
    """'Open archive > zip' on a zip renamed to .bin: opens it, and extraction keeps the type."""
    monkeypatch.setenv("PR7Z_7Z", exe)
    from pr7z import main_window
    arc = tmp_path / "x.zip"
    Job("", operations.add_steps(exe, str(arc), [str(tree)], AddOptions(format="zip"))).run_blocking()
    disguised = tmp_path / "data.bin"
    arc.rename(disguised)
    monkeypatch.setattr(main_window, "message", lambda *a, **k: 0)
    w = main_window.MainWindow(str(disguised), archive_type="zip")
    assert w.loc.__class__.__name__ == "ArchiveLocation" and w.loc.archive_type == "zip"
    w._set_location(w.loc.at("src"))
    assert w.loc.archive_type == "zip"  # carried into subfolders, so extract/test use -tzip too
    w.close()


def test_mail_without_windows_reports_false():
    from pr7z import mail
    if os.name != "nt":
        assert mail.send_files(["x.7z"]) is False


def test_deploy_dll_copies_by_content(tmp_path, monkeypatch):
    """Registering copies the DLL under a content-hash name, so an update never overwrites the copy
    Explorer has locked; old copies go when they can."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    v1 = tmp_path / "v1.dll"
    v1.write_bytes(b"build one")
    a = shell.deploy_dll(v1)
    assert a.parent == tmp_path / "appdata" / "Paragon" / "PR7-Z" / "shellext"
    assert a.read_bytes() == b"build one"
    assert shell.deploy_dll(v1) == a                       # same build: same file, no rewrite
    v2 = tmp_path / "v2.dll"
    v2.write_bytes(b"build two")
    b = shell.deploy_dll(v2)
    assert b != a and b.read_bytes() == b"build two"
    assert not a.exists()                                  # the old copy was free, so it went
    real_unlink = Path.unlink

    def locked(self, *args, **kw):                         # Explorer holding a copy: unlink fails
        if self == b:
            raise PermissionError("in use")
        return real_unlink(self, *args, **kw)

    monkeypatch.setattr(Path, "unlink", locked)
    assert shell.remove_old_dlls() == [b] and b.exists()   # left alone, reported, retried later


# ---------------------------------------------------------------- PR7ZShell.dll (Windows)
windows = pytest.mark.skipif(os.name != "nt", reason="Explorer's shell extension is Windows-only")


@pytest.fixture()
def dll():
    p = shell.shell_dll()
    if p is None:
        pytest.skip("PR7ZShell.dll isn't built (cmake -S shellext -B shellext/build -A x64)")
    return ctypes.WinDLL(str(p))


@pytest.fixture()
def menu_settings():
    """Point the menu at this Python for the test; put the user's own settings back afterwards."""
    import winreg
    key = shell.SETTINGS_KEY
    saved = {}
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key)
        i = 0
        while True:
            try:
                name, val, typ = winreg.EnumValue(k, i)
            except OSError:
                break
            saved[name] = (val, typ)
            i += 1
        winreg.CloseKey(k)
    except OSError:
        saved = None

    def set_(cascaded=True, items=shell.ALL_ITEMS, command=f'"{sys.executable}" -m pr7z'):
        k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_WRITE)
        if command is None:
            try:
                winreg.DeleteValue(k, "Command")
            except OSError:
                pass
        else:
            winreg.SetValueEx(k, "Command", 0, winreg.REG_SZ, command)
        winreg.SetValueEx(k, "Cascaded", 0, winreg.REG_DWORD, int(cascaded))
        winreg.SetValueEx(k, "Items", 0, winreg.REG_DWORD, items)
        winreg.CloseKey(k)

    set_()
    yield set_
    shell._delete_tree(winreg.HKEY_CURRENT_USER, key)
    if saved is not None:
        k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_WRITE)
        for name, (val, typ) in saved.items():
            winreg.SetValueEx(k, name, 0, typ, val)
        winreg.CloseKey(k)


def self_test(dll, files):
    buf = ctypes.create_unicode_buffer(400_000)
    f = dll.PR7Z_SelfTest
    f.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    f.restype = ctypes.c_int
    n = f("\n".join(str(x) for x in files), buf, len(buf))
    assert n >= 0, f"self-test failed: {n}"
    items, cmds = [], {}
    for line in buf.value.splitlines():
        parts = line.split("\t")
        if parts[0] == "cmd":
            cmds[parts[1]] = parts[2]
        elif parts[0].isdigit():
            items.append((int(parts[0]), parts[1], parts[2] if len(parts) > 2 else None))
    return items, cmds


def argv_of(cmdline: str) -> list[str]:
    """Split a command line exactly as Windows does for PR7-Z's process."""
    from ctypes import wintypes
    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    n = ctypes.c_int()
    p = shell32.CommandLineToArgvW(cmdline, ctypes.byref(n))
    out = [p[i] for i in range(n.value)]
    ctypes.windll.kernel32.LocalFree(p)
    return out


def menu_command(items, cmds, label) -> app.Command:
    ident = next(i for d, lab, i in items if lab == label and i)
    argv = argv_of(cmds[ident])
    return app.parse(argv[argv.index("pr7z") + 1:])


def labels(items, depth=1):
    return [lab for d, lab, _ in items if d == depth]


@windows
def test_menu_on_an_archive(dll, menu_settings, exe, tree, tmp_path):
    arc = tmp_path / "Stems.7z"
    Job("", operations.add_steps(exe, str(arc), [str(tree)], AddOptions())).run_blocking()
    items, cmds = self_test(dll, [arc])
    assert [lab for d, lab, _ in items if d == 0] == ["-", "PR7-Z", "-"]
    assert labels(items) == ["Open archive", "Open archive", "Extract files...", "Extract Here", 'Extract to "Stems\\"',
                             "Test archive", "Add to archive...", "Compress and email...", 'Add to "Stems_2.7z"',
                             'Compress to "Stems_2.7z" and email', 'Add to "Stems.zip"',
                             'Compress to "Stems.zip" and email', "CRC SHA"]
    assert "#" in labels(items, 2) and "SHA-256" in labels(items, 2)
    c = menu_command(items, cmds, 'Extract to "Stems\\"')
    assert (c.action, c.param, c.paths) == ("--extract-into", str(tmp_path / "Stems"), [str(arc)])
    c = menu_command(items, cmds, 'Add to "Stems_2.7z"')
    assert (c.action, c.param, c.paths) == ("--add-to", str(tmp_path / "Stems_2.7z"), [str(arc)])
    c = menu_command(items, cmds, 'Compress to "Stems.zip" and email')
    assert (c.action, c.param) == ("--add-to-email", "Stems.zip")
    c = menu_command(items, cmds, "SHA-256")
    assert (c.action, c.param, c.paths) == ("--hash", "SHA256", [str(arc)])
    c = menu_command(items, cmds, "#")
    assert (c.action, c.param, c.paths) == ("--open-as", "#", [str(arc)])


@windows
def test_menu_on_plain_files_and_folders(dll, menu_settings, tree, tmp_path):
    notes = tmp_path / "notes for mix.txt"
    notes.write_bytes(b"x")
    items, _ = self_test(dll, [notes])
    got = labels(items)
    assert "Extract files..." not in got and "Test archive" not in got
    assert 'Add to "notes for mix.7z"' in got and "Open archive" in got
    pack = tmp_path / "Pack"
    pack.mkdir()
    (pack / "a.txt").write_bytes(b"a")
    (pack / "b.wav").write_bytes(b"b")
    items, cmds = self_test(dll, [pack / "a.txt", pack / "b.wav"])
    got = labels(items)
    assert "Open archive" not in got and 'Add to "Pack.7z"' in got
    c = menu_command(items, cmds, 'Add to "Pack.7z"')
    assert c.paths == [str(pack / "a.txt"), str(pack / "b.wav")]  # all selected files in one launch
    items, _ = self_test(dll, [tree])
    got = labels(items)
    assert "Open archive" not in got and 'Add to "src.7z"' in got and "CRC SHA" in got


@windows
def test_unicode_and_spaces_survive_the_command_line(dll, menu_settings, tmp_path):
    odd = tmp_path / "ünï cødé (final) & mix.7z"
    odd.write_bytes(b"not really an archive")
    items, cmds = self_test(dll, [odd])
    c = menu_command(items, cmds, "Extract Here")
    assert c.paths == [str(odd)]


@windows
def test_flat_menu_and_item_choice(dll, menu_settings, tmp_path):
    f = tmp_path / "a.zip"
    f.write_bytes(b"x")
    menu_settings(cascaded=False, items=shell.ALL_ITEMS & ~(1 << 8) & ~(1 << 9))  # no 'Add to "a.7z"' pair
    items, _ = self_test(dll, [f])
    top = labels(items, 0)
    assert top[0] == "-" and top[-1] == "-" and "Extract Here" in top and "PR7-Z" not in top
    assert not any(lab.startswith('Add to "a') and lab.endswith('.7z"') for lab in top)
    assert 'Add to "a_2.zip"' in top  # the archive itself is a.zip: 7-Zip's _2


@windows
def test_no_command_no_menu(dll, menu_settings, tmp_path):
    f = tmp_path / "a.7z"
    f.write_bytes(b"x")
    menu_settings(command=None)
    items, cmds = self_test(dll, [f])
    assert items == [] and cmds == {}


@windows
def test_huge_selection_uses_a_list_file(dll, menu_settings, tmp_path):
    many = []
    for i in range(400):
        p = tmp_path / (f"{i:03d}_" + "long_name_" * 9 + ".wav")
        p.write_bytes(b"")
        many.append(p)
    items, cmds = self_test(dll, many)
    ident = next(i for d, lab, i in items if lab == "Add to archive...")
    assert "--files-from" in cmds[ident] and len(cmds[ident]) < 2000
    c = menu_command(items, cmds, "Add to archive...")
    assert c.paths == [str(p) for p in many]


@windows
@pytest.mark.skipif(not os.environ.get("CI"), reason="writes the Explorer registration; CI machines only")
def test_register_and_unregister(dll, menu_settings):
    import winreg
    shell.register_menu()
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\CLSID\{shell.CLSID}\InprocServer32")
        path, _ = winreg.QueryValueEx(k, "")
        # a hashed copy in the per-user folder, byte-identical to the built DLL
        assert Path(path).parent == shell.deploy_dir() and Path(path).name.startswith("PR7ZShell-")
        assert Path(path).read_bytes() == shell.shell_dll().read_bytes()
        assert shell.menu_registered() == "extension"
    finally:
        shell.unregister_menu()
    assert shell.menu_registered() == ""
