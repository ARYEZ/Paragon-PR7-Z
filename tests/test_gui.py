"""The window and the app entry point, offscreen, against real archives."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from pr7z import engine, main_window, operations
from pr7z.engine import AddOptions
from pr7z.jobs import Job
from pr7z.models import ArchiveLocation, ArchiveTree, FsLocation


@pytest.fixture()
def win(qapp, exe, tree, tmp_path, monkeypatch):
    monkeypatch.setenv("PR7Z_7Z", exe)
    arc = tmp_path / "Stems.7z"
    Job("", operations.add_steps(exe, str(arc), [str(tree)], AddOptions())).run_blocking()
    # dialogs that would wait for a click answer "yes"
    monkeypatch.setattr(main_window, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(main_window, "message", lambda *a, **k: 0)
    w = main_window.MainWindow(str(tmp_path))
    yield w
    w.close()


def names(w):
    return [w.proxy.index(r, 0).data(main_window.ENTRY_ROLE).name for r in range(w.proxy.rowCount())]


def headers(w):
    return [w.model.headerData(i, Qt.Horizontal) for i in range(w.model.columnCount())]


def test_folder_listing_folders_first(win, tmp_path):
    (tmp_path / "zeta").mkdir()
    win.refresh()
    n = names(win)
    assert n.index("src") < n.index("Stems.7z") and n.index("zeta") < n.index("Stems.7z")
    assert headers(win) == ["NAME", "SIZE", "MODIFIED", "CREATED", "ATTRIBUTES"]


def test_open_archive_and_browse(win, tmp_path):
    win._select_name("Stems.7z")
    win.open_selected()
    assert isinstance(win.loc, ArchiveLocation)
    assert headers(win)[:3] == ["NAME", "SIZE", "PACKED SIZE"]
    assert names(win) == ["src"]
    win._select_name("src")
    win.open_selected()
    assert names(win) == ["sub", "a.txt"]
    sizes = {e.name: e.size for e in (win.proxy.index(r, 0).data(main_window.ENTRY_ROLE)
                                      for r in range(win.proxy.rowCount()))}
    assert sizes["sub"] == 300_002  # folder total: big.bin + the 2-byte unicode file
    win.go_up()
    assert names(win) == ["src"] and win.focused().name == "src"   # Backspace re-selects where we came from
    win.go_up()
    assert isinstance(win.loc, FsLocation) and win.focused().name == "Stems.7z"


def test_address_bar_into_archive(win, tmp_path):
    assert win.navigate(str(tmp_path / "Stems.7z" / "src" / "sub"))
    assert isinstance(win.loc, ArchiveLocation) and win.loc.inner == "src/sub"
    assert sorted(names(win)) == ["big.bin", "ünï cødé.txt"]
    assert win.path.currentText().rstrip("\\/").endswith(str(Path("Stems.7z") / "src" / "sub"))


def test_flat_view(win, tmp_path):
    win.navigate(str(tmp_path / "Stems.7z"))
    win.flat_act.trigger()
    assert sorted(names(win)) == ["src/a.txt", "src/sub/big.bin", "src/sub/ünï cødé.txt"]


def test_drop_into_archive_subfolder(win, tmp_path):
    extra = tmp_path / "dropped.txt"
    extra.write_text("d")
    win.navigate(str(tmp_path / "Stems.7z" / "src" / "sub"))
    win.drop_in([str(extra)])
    assert "dropped.txt" in names(win)
    paths = {i.path for i in engine.list_archive(str(tmp_path / "Stems.7z"), exe=win.exe).items}
    assert "src/sub/dropped.txt" in paths


def test_delete_and_rename_in_archive(win, tmp_path, monkeypatch):
    win.navigate(str(tmp_path / "Stems.7z" / "src"))
    win._select_name("a.txt")
    win.view.selectionModel().select(win.view.currentIndex(), win.view.selectionModel().SelectionFlag.Select |
                                     win.view.selectionModel().SelectionFlag.Rows)
    win.do_delete()
    assert names(win) == ["sub"]
    monkeypatch.setattr(main_window, "ask_text", lambda *a, **k: "renamed")
    win._select_name("sub")
    win.do_rename()
    assert names(win) == ["renamed"]


def test_encrypted_archive_asks_password(win, tmp_path, exe, tree, monkeypatch):
    arc = tmp_path / "secret.7z"
    Job("", operations.add_steps(exe, str(arc), [str(tree)], AddOptions(password="pw", encrypt_names=True))) \
        .run_blocking()
    answers = iter(["wrong", "pw"])
    monkeypatch.setattr(main_window.PasswordDialog, "get", staticmethod(lambda *a, **k: next(answers)))
    assert win.open_archive(str(arc))
    assert win.loc.password == "pw" and names(win) == ["src"]


def test_not_an_archive_opens_quietly(win, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(win, "_shell_open", opened.append)
    (tmp_path / "notes.txt").write_text("hi")
    win.refresh()
    win._select_name("notes.txt")
    win.open_selected()
    assert opened == [str(tmp_path / "notes.txt")] and isinstance(win.loc, FsLocation)


def test_tree_fills_implied_folders():
    info = engine.ArchiveInfo(path="x", items=[engine.Item(path="a/b/c.txt", is_dir=False, size=5, packed=3),
                                              engine.Item(path="a/d.txt", is_dir=False, size=7, packed=7)])
    t = ArchiveTree(info)
    assert [e.name for e in t.list("")] == ["a"]
    a = t.list("")[0]
    assert a.size == 12 and a.packed == 10
    assert {e.name for e in t.list("a")} == {"b", "d.txt"}
    assert t.all_under(["a/b"]) == ["a/b/c.txt"]


def test_cli_parse():
    from pr7z.app import parse
    c = parse(["--extract-here", "a.7z", "b.zip"])
    assert (c.action, c.paths) == ("--extract-here", ["a.7z", "b.zip"])
    c = parse(["D:/x"])
    assert (c.action, c.paths) == (None, ["D:/x"])
    with pytest.raises(SystemExit):
        parse(["--nope"])


def test_collector_merges_explorer_launches(tmp_path):
    """Explorer starts one PR7-Z per selected file; they must end up as one list in one process."""
    script = textwrap.dedent(f"""
        import sys, os
        sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["USER"] = "pr7ztest{os.getpid()}"
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication([])
        from pr7z.app import collect
        r = collect("--add", [sys.argv[1]])
        print("COLLECTOR" if r is not None else "SENT", sorted(r) if r else "")
    """)
    f = tmp_path / "c.py"
    f.write_text(script)
    procs = []
    for i in range(4):
        procs.append(subprocess.Popen([sys.executable, str(f), f"file{i}"], stdout=subprocess.PIPE, text=True))
        if i == 0:
            import time
            time.sleep(0.25)  # the first one is listening before the rest arrive (as with Explorer)
    outs = [p.communicate(timeout=30)[0].strip() for p in procs]
    collectors = [o for o in outs if o.startswith("COLLECTOR")]
    assert len(collectors) == 1, outs
    assert all(f"file{i}" in collectors[0] for i in range(4)), outs


def test_big_archive_listing_is_fast(win):
    """100 000 items (a game or ISO-sized archive): building the tree and the list stays quick."""
    import time
    items = [engine.Item(path=f"d{i % 100}/sub{i % 7}/file{i}.bin", is_dir=False, size=i, packed=i // 2)
             for i in range(100_000)]
    t = time.monotonic()
    tree = ArchiveTree(engine.ArchiveInfo(path="big.7z", type="7z", items=items))
    win._set_location(ArchiveLocation("big.7z", "big.7z", tree, outer=win.loc))
    win._set_location(win.loc.at("d5/sub3"))
    elapsed = time.monotonic() - t
    assert win.proxy.rowCount() > 100
    assert elapsed < 5.0, elapsed
    win.flat_act.trigger()  # flat view of a 1 000-file folder
    assert win.proxy.rowCount() > 100
