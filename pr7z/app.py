"""Starting PR7-Z: the window, or one action from Explorer's right-click menu.

    pr7z [path]                       the file manager, at a folder or inside an archive
    pr7z --open PATH                  same
    pr7z --open-as TYPE PATH          open a file as an archive of TYPE (7-Zip's "Open archive >": *, #, 7z, zip ...)
    pr7z --add FILES...               Add to Archive dialog
    pr7z --add-email FILES...         Add to Archive dialog, then email the archive
    pr7z --add-to ARCHIVE FILES...    straight into ARCHIVE (format from its extension)
    pr7z --add-to-email NAME FILES... compress to NAME in a temp folder and email it
    pr7z --add-7z / --add-zip FILES   straight to "<name>.7z" / "<name>.zip"
    pr7z --extract ARCHIVES...        Extract dialog
    pr7z --extract-here ARCHIVES...   into each archive's folder
    pr7z --extract-to ARCHIVES...     each into "<archive name>\\"
    pr7z --extract-into DIR ARCHIVE   into DIR
    pr7z --test ARCHIVES...           test, result window
    pr7z --hash[:METHOD] FILES...     checksums (CRC32, CRC64, XXH64, MD5, SHA1, SHA256, SHA512, BLAKE2sp, *)
    pr7z --register | --unregister    Explorer menu and "Open with" (this user only)
    ... --files-from LIST             read the FILES from LIST (UTF-8, one per line; deleted afterwards)

The Explorer menu (PR7ZShell.dll) passes every selected file in one launch. The fallback registry
menu starts one PR7-Z per selected file; the first collects the others' files for a moment, so ten
selected files still give one dialog, as 7-Zip does.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QByteArray, QElapsedTimer
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import __version__, engine, operations, theme

ACTIONS = {"--open", "--add", "--add-email", "--add-7z", "--add-zip", "--extract", "--extract-here", "--extract-to",
           "--test", "--hash"}
WITH_PARAM = {"--open-as", "--add-to", "--add-to-email", "--extract-into"}  # take one value before the files
OTHER = {"--register", "--unregister", "--version", "--help"}
HASH_METHODS = {"CRC32", "CRC64", "XXH64", "MD5", "SHA1", "SHA256", "SHA384", "SHA512", "SHA3-256", "BLAKE2sp", "*"}
COLLECT_MS = 450


@dataclass
class Command:
    action: str | None = None
    param: str = ""                 # the value of a WITH_PARAM action, or the hash method
    paths: list[str] = field(default_factory=list)


def parse(argv: list[str]) -> Command:
    cmd = Command()
    it = iter(argv)
    for a in it:
        if a == "--files-from":
            lst = next(it, None)
            if not lst:
                raise SystemExit("--files-from needs a list file.")
            cmd.paths += _read_list(lst)
        elif a.startswith("--hash"):
            cmd.action = "--hash"
            method = a.partition(":")[2] or "*"
            if method not in HASH_METHODS:
                raise SystemExit(f"Unknown checksum {method}.")
            cmd.param = method
        elif a in WITH_PARAM:
            cmd.action = a
            cmd.param = next(it, "")
            if not cmd.param:
                raise SystemExit(f"{a} needs a value.")
        elif a in ACTIONS or a in OTHER:
            cmd.action = a
        elif a.startswith("--"):
            raise SystemExit(f"Unknown option {a}. See pr7z --help.")
        else:
            cmd.paths.append(a)
    return cmd


def _read_list(path: str) -> list[str]:
    p = Path(path)
    try:
        lines = p.read_text(encoding="utf-8-sig").splitlines()
    finally:
        if p.name.startswith("pr7z-list-"):  # the shell extension's temp list: ours to remove
            p.unlink(missing_ok=True)
    return [ln for ln in lines if ln.strip()]


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


def _format_for(archive: str) -> str:
    ext = Path(archive).suffix.lower().lstrip(".")
    return next((f for f, e in engine.FORMAT_EXT.items() if e == ext), "7z")


def _compress(exe: str, archive: str, paths: list[str], opts) -> bool:
    from .dialogs import run_job
    from .jobs import Job
    return run_job(Job(f"Compressing {Path(archive).name}", operations.add_steps(exe, archive, paths, opts))).ok


def _email(archive: str) -> None:
    from . import mail
    from .dialogs import message
    if not mail.send_files([archive]):
        message(None, "PR7-Z", "No email program answered. The archive is ready here:\n" + archive)
        mail.reveal(archive)


def run_action(cmd: Command) -> int:
    """One Explorer action, without the file manager window."""
    from .add_dialog import AddDialog, default_archive_name
    from .dialogs import ExtractDialog, TextDialog, run_job
    from .engine import AddOptions, ExtractOptions
    from .jobs import Job, Step
    exe = engine.find_7z()
    action, paths = cmd.action, cmd.paths
    if action in ("--add", "--add-email"):
        mail_dir = Path(tempfile.mkdtemp(prefix="pr7z-mail-")) if action == "--add-email" else None
        default = default_archive_name(paths)
        d = AddDialog(paths, str(mail_dir / Path(default).name) if mail_dir else None)
        if d.exec() != AddDialog.Accepted:
            return 1
        ok = _compress(exe, d.archive_path(), paths, d.options())
        if ok and mail_dir:
            _email(d.archive_path())
        return 0 if ok else 2
    if action == "--add-to":
        return 0 if _compress(exe, cmd.param, paths, AddOptions(format=_format_for(cmd.param))) else 2
    if action == "--add-to-email":
        arc = str(Path(tempfile.mkdtemp(prefix="pr7z-mail-")) / Path(cmd.param).name)
        ok = _compress(exe, arc, paths, AddOptions(format=_format_for(arc)))
        if ok:
            _email(arc)
        return 0 if ok else 2
    if action in ("--add-7z", "--add-zip"):
        fmt = "7z" if action == "--add-7z" else "zip"
        arc = default_archive_name(paths, fmt)
        return 0 if _compress(exe, arc, paths, AddOptions(format=fmt)) else 2
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
    if action in ("--extract-here", "--extract-to", "--extract-into"):
        steps = []
        for a in paths:
            out = {"--extract-here": str(Path(a).parent), "--extract-to": operations.default_extract_dir(a),
                   "--extract-into": cmd.param}[action]
            steps += operations.extract_steps(exe, a, out, ExtractOptions())
        return 0 if run_job(Job("Extracting", steps)).ok else 2
    if action == "--test":
        return 0 if run_job(Job("Testing", operations.test_steps(exe, paths)), keep_open=True).ok else 2
    if action == "--hash":
        res = run_job(Job("Checksum", [Step("Calculating checksum", engine.hash_args(exe, paths, cmd.param or "*"))]))
        from .main_window import _hash_lines
        TextDialog("Checksum information", "CHECKSUM", "\n".join(_hash_lines(res.log))).exec()
        return 0 if res.ok else 2
    return 7


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = parse(argv)
    if cmd.action == "--help":
        print(__doc__)
        return 0
    if cmd.action == "--version":
        print(f"PR7-Z {__version__}")
        return 0
    if cmd.action in ("--register", "--unregister"):
        from . import shell
        if not shell.available():
            print("Explorer integration is for Windows.")
            return 1
        if cmd.action == "--register":
            shell.register_menu()
            shell.register_open_with()
        else:
            shell.unregister_menu()
            shell.unregister_open_with()
        return 0
    app = make_app([sys.argv[0]])
    if cmd.action and cmd.action not in ("--open", "--open-as"):
        if not cmd.paths:
            raise SystemExit(f"{cmd.action} needs one or more paths.")
        if cmd.action not in ("--test", "--add-to", "--add-to-email", "--extract-into"):
            all_paths = collect(cmd.action + cmd.param, cmd.paths)  # merges the registry menu's launches
            if all_paths is None:
                return 0
            cmd.paths = all_paths
        try:
            return run_action(cmd)
        except engine.EngineNotFound as e:
            from .dialogs import message
            message(None, "PR7-Z", str(e))
            return 2
    from .main_window import MainWindow
    w = MainWindow(cmd.paths[0] if cmd.paths else None,
                   archive_type=cmd.param if cmd.action == "--open-as" else "")
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
