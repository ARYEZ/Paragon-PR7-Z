"""Starting PR7-Z: the window, or one action from Explorer's right-click menu.

    pr7z [path]                 the file manager, at a folder or inside an archive
    pr7z --open PATH            same
    pr7z --add FILES...         Add to Archive dialog
    pr7z --add-7z FILES...      straight to "<name>.7z"      (--add-zip: "<name>.zip")
    pr7z --extract ARCHIVES...  Extract dialog
    pr7z --extract-here A...    into the archive's folder    (--extract-to: into "<archive name>\\")
    pr7z --test ARCHIVES...     test, result window
    pr7z --hash FILES...        CRC / SHA checksums
    pr7z --register | --unregister   Explorer menu and "Open with" (this user only)

Explorer starts one PR7-Z per selected file; the first one collects the others' files for a
moment, so ten selected files give one Add dialog, as 7-Zip does.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QElapsedTimer
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import __version__, engine, operations, theme

ACTIONS = {"--open", "--add", "--add-7z", "--add-zip", "--extract", "--extract-here", "--extract-to", "--test",
           "--hash"}
COLLECT_MS = 450


def parse(argv: list[str]) -> tuple[str | None, list[str]]:
    action, paths = None, []
    for a in argv:
        if a in ACTIONS or a in ("--register", "--unregister", "--version", "--help"):
            action = a
        elif a.startswith("--"):
            raise SystemExit(f"Unknown option {a}. See pr7z --help.")
        else:
            paths.append(a)
    return action, paths


def _server_name(action: str) -> str:
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return f"pr7z-{user}-{action.strip('-')}"


def collect(action: str, paths: list[str]) -> list[str] | None:
    """Gather the files from PR7-Zs started at the same moment for the same action.
    Returns all paths (we're the collector), or None (we handed ours over: exit)."""
    name = _server_name(action)
    for _ in range(3):
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(150):
            sock.write(QByteArray("\n".join(paths).encode("utf-8")))
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()
            return None
        server = QLocalServer()
        if server.listen(name):
            break
        QLocalServer.removeServer(name)
    else:
        return paths
    got = list(paths)
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < COLLECT_MS:
        server.waitForNewConnection(50)  # PySide returns (ok, timed_out): check for a connection instead
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is None:
                break
            data = bytes(conn.readAll())
            while conn.state() == QLocalSocket.ConnectedState and conn.waitForReadyRead(300):
                data += bytes(conn.readAll())
            data += bytes(conn.readAll())
            got += [p for p in data.decode("utf-8").split("\n") if p]
            timer.restart()
    server.close()
    return list(dict.fromkeys(got))  # de-duplicated, order kept


def make_app(argv: list[str]) -> QApplication:
    QApplication.setApplicationName("PR7-Z")
    QApplication.setOrganizationName("Paragon")
    app = QApplication.instance() or QApplication(argv)
    theme.load_fonts()
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())
    ico = Path(__file__).parent / "icons" / "app.ico"
    if ico.exists():
        app.setWindowIcon(QIcon(str(ico)))
    return app


def run_action(action: str, paths: list[str]) -> int:
    """One Explorer action, without the file manager window."""
    from .add_dialog import AddDialog, default_archive_name
    from .dialogs import ExtractDialog, TextDialog, message, run_job
    from .engine import AddOptions, ExtractOptions
    from .jobs import Job, Step
    exe = engine.find_7z()
    if action == "--add":
        d = AddDialog(paths)
        if d.exec() != AddDialog.Accepted:
            return 1
        r = run_job(Job(f"Compressing {Path(d.archive_path()).name}",
                        operations.add_steps(exe, d.archive_path(), paths, d.options())))
        return 0 if r.ok else 2
    if action in ("--add-7z", "--add-zip"):
        fmt = "7z" if action == "--add-7z" else "zip"
        arc = default_archive_name(paths, fmt)
        r = run_job(Job(f"Compressing {Path(arc).name}", operations.add_steps(exe, arc, paths, AddOptions(format=fmt))))
        return 0 if r.ok else 2
    if action == "--extract":
        first = paths[0]
        d = ExtractDialog(first if len(paths) == 1 else f"{len(paths)} archives", operations.default_extract_dir(first)
                          if len(paths) == 1 else str(Path(first).parent / "*"))
        if d.exec() != ExtractDialog.Accepted:
            return 1
        opts, dest = d.options(), d.destination()
        steps = []
        for a in paths:
            steps += operations.extract_steps(exe, a, dest.replace("*", Path(operations.default_extract_dir(a)).name),
                                              opts)
        return 0 if run_job(Job("Extracting", steps)).ok else 2
    if action in ("--extract-here", "--extract-to"):
        steps = []
        for a in paths:
            out = str(Path(a).parent) if action == "--extract-here" else operations.default_extract_dir(a)
            steps += operations.extract_steps(exe, a, out, ExtractOptions())
        return 0 if run_job(Job("Extracting", steps)).ok else 2
    if action == "--test":
        return 0 if run_job(Job("Testing", operations.test_steps(exe, paths)), keep_open=True).ok else 2
    if action == "--hash":
        res = run_job(Job("Checksum", [Step("Calculating checksum", engine.hash_args(exe, paths, "*"))]))
        from .main_window import _hash_lines
        TextDialog("Checksum information", "CHECKSUM", "\n".join(_hash_lines(res.log))).exec()
        return 0 if res.ok else 2
    message(None, "PR7-Z", f"Unknown action {action}")
    return 7


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    action, paths = parse(argv)
    if action == "--help":
        print(__doc__)
        return 0
    if action == "--version":
        print(f"PR7-Z {__version__}")
        return 0
    if action in ("--register", "--unregister"):
        from . import shell
        if not shell.available():
            print("Explorer integration is for Windows.")
            return 1
        if action == "--register":
            shell.register_menu()
            shell.register_open_with()
        else:
            shell.unregister_menu()
            shell.unregister_open_with()
        return 0
    app = make_app([sys.argv[0]])
    if action in ACTIONS - {"--open"}:
        if not paths:
            raise SystemExit(f"{action} needs one or more paths.")
        if action not in ("--test",):
            all_paths = collect(action, paths)
            if all_paths is None:
                return 0
            paths = all_paths
        try:
            return run_action(action, paths)
        except engine.EngineNotFound as e:
            from .dialogs import message
            message(None, "PR7-Z", str(e))
            return 2
    from .main_window import MainWindow
    w = MainWindow(paths[0] if paths else None)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
