"""The file-manager window: 7-Zip File Manager's behaviour in the Paragon look."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, QPointF, QRectF, QSettings, QSize, QSortFilterProxyModel, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QDrag, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QMainWindow, QMenu, QStatusBar, QTreeView, QVBoxLayout, QWidget)

from . import engine, operations, theme
from .add_dialog import AddDialog
from .dialogs import (AboutDialog, CopyDialog, ExtractDialog, HistoryDialog, PasswordDialog, PropertiesDialog,
                      TextDialog, ask_text, confirm, engine_version, fmt_size, message, run_job)
from .engine import AddOptions, ExtractOptions
from .jobs import Job, Step
from .models import ArchiveLocation, ArchiveTree, Entry, FsLocation, NUMERIC, split_archive_path
from .widgets import Header, KeyButton, Toolbar, file_icon

ENTRY_ROLE = Qt.UserRole + 1
SORT_ROLE = Qt.UserRole + 2
HASHES = [("CRC-32", "CRC32"), ("CRC-64", "CRC64"), ("XXH64", "XXH64"), ("SHA-1", "SHA1"), ("SHA-256", "SHA256"),
          ("BLAKE2sp", "BLAKE2sp"), ("All", "*")]


class EntryModel(QAbstractTableModel):
    """The list's rows as a plain Python list; Qt asks for each cell. (No QStandardItems: their
    Python/Qt ownership crashed PySide on clear(), and a 100 000-item archive builds instantly.)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[Entry] = []
        self.cols: list[str] = []
        self._icons = {}

    def set_entries(self, entries: list[Entry], cols: list[str]):
        self.beginResetModel()
        self.entries, self.cols = entries, cols
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cols)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < len(self.cols):
            return self.cols[section].upper()
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        col = self.cols[index.column()]
        if role == Qt.DisplayRole:
            return e.value(col)[0]
        if role == SORT_ROLE:
            return e.value(col)[1]
        if role == ENTRY_ROLE:
            return e
        if role == Qt.DecorationRole and index.column() == 0:
            kind = "folder" if e.is_dir else e.kind
            if kind not in self._icons:
                self._icons[kind] = file_icon(kind)
            return self._icons[kind]
        if role == Qt.TextAlignmentRole and col in NUMERIC:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


class FolderFirstProxy(QSortFilterProxyModel):
    """7-Zip's order: folders before files whichever way a column is sorted."""

    def lessThan(self, left, right):
        a, b = left.siblingAtColumn(0).data(ENTRY_ROLE), right.siblingAtColumn(0).data(ENTRY_ROLE)
        if a is not None and b is not None and a.is_dir != b.is_dir:
            return a.is_dir if self.sortOrder() == Qt.AscendingOrder else b.is_dir
        x, y = left.data(SORT_ROLE), right.data(SORT_ROLE)
        try:
            return x < y
        except TypeError:
            return str(x) < str(y)


class FileView(QTreeView):
    """The list. A selected row gets one family-gradient band across its width; drags extract."""

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.win = window
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDrop)

    def drawRow(self, painter: QPainter, option, index):
        super().drawRow(painter, option, index)
        if self.selectionModel().isRowSelected(index.row(), index.parent()):
            r = QRectF(option.rect)
            r.setLeft(0)
            r.setRight(self.viewport().width())
            painter.save()
            painter.fillRect(r, theme.family_gradient(r.left(), 0, r.right(), 0, theme.LIT, 0.22))
            painter.setPen(QPen(theme.family_gradient(r.left(), 0, r.right(), 0), 1))
            painter.drawLine(QPointF(r.left(), r.top() + 0.5), QPointF(r.right(), r.top() + 0.5))
            painter.drawLine(QPointF(r.left(), r.bottom() - 0.5), QPointF(r.right(), r.bottom() - 0.5))
            painter.restore()

    def startDrag(self, actions):
        paths = self.win.paths_for_drag()
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is not self:
            e.acceptProposedAction()
        else:
            e.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            move = bool(e.modifiers() & Qt.ShiftModifier)
            QTimer.singleShot(0, lambda: self.win.drop_in(paths, move))


class MainWindow(QMainWindow):
    def __init__(self, start: str | None = None, archive_type: str = ""):
        super().__init__()
        self.settings = QSettings(QSettings.defaultFormat(), QSettings.UserScope, "Paragon", "PR7-Z")
        self.resize(self.settings.value("size", QSize(1280, 760)))
        try:
            self.exe = engine.find_7z()
        except engine.EngineNotFound as e:
            message(self, "PR7-Z", str(e))
            self.exe = "7z"
        self.temp_root = Path(tempfile.gettempdir()) / f"pr7z-{os.getpid()}"
        self.loc = FsLocation("")
        self.watches: dict[str, tuple] = {}
        self.show_hidden = self.settings.value("show_hidden", True, type=bool)
        from PySide6.QtCore import QFileSystemWatcher
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._temp_file_changed)
        self.dir_watcher = QFileSystemWatcher(self)
        self.dir_watcher.directoryChanged.connect(lambda _: self.auto_refresh.isChecked() and self.refresh())

        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(Header())
        self.toolbar = Toolbar()
        self.toolbar.triggered.connect(self._toolbar)
        col.addWidget(self.toolbar)
        addr = QHBoxLayout()
        addr.setContentsMargins(16, 4, 16, 8)
        addr.setSpacing(8)
        up = KeyButton("up", "")
        up.setFixedSize(QSize(40, 36))
        up.setToolTip("Up One Level (Backspace)")
        up.clicked.connect(self.go_up)
        self.path = QComboBox()
        self.path.setEditable(True)
        self.path.setInsertPolicy(QComboBox.NoInsert)
        self.path.lineEdit().returnPressed.connect(lambda: self.navigate(self.path.currentText()))
        self.path.activated.connect(lambda i: self.navigate(self.path.itemText(i)))
        addr.addWidget(up)
        addr.addWidget(self.path, 1)
        col.addLayout(addr)

        self.view = FileView(self)
        self.view.setRootIsDecorated(False)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSortingEnabled(True)
        self.view.setUniformRowHeights(True)
        self.view.setIconSize(QSize(18, 18))
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.activated.connect(lambda _i: self.open_selected())
        self.model = EntryModel(self)
        self.proxy = FolderFirstProxy(self)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setSourceModel(self.model)
        self.view.setModel(self.proxy)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._update_status())
        self.view.header().setSectionResizeMode(QHeaderView.Interactive)
        self.view.header().setStretchLastSection(True)
        self.view.header().sectionResized.connect(lambda *_: self._save_widths())
        wrap = QHBoxLayout()
        wrap.setContentsMargins(16, 0, 16, 12)
        wrap.addWidget(self.view)
        col.addLayout(wrap, 1)
        self.setCentralWidget(central)
        QShortcut(QKeySequence(Qt.Key_Backspace), self.view, self.go_up)

        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.status = [QLabel("") for _ in range(4)]
        for i, lab in enumerate(self.status):
            sb.addWidget(lab, 1 if i == 3 else 0)
        self.setStatusBar(sb)

        self._build_menus()
        if start and archive_type and Path(start).is_file():  # "Open archive >" from Explorer
            if self.open_archive(start, archive_type=archive_type):
                return
        self.navigate(start or self.settings.value("last_folder", str(Path.home())))

    # ================================================================ navigation
    def navigate(self, text: str, select: str | None = None) -> bool:
        text = (text or "").strip().strip('"')
        if not text or text in ("Computer", "\\") and os.name == "nt":
            return self._set_location(FsLocation(""), select)
        # Inside the archive already open: a path below its display path.
        if isinstance(self.loc, ArchiveLocation):
            base = self.loc.display_archive.rstrip("\\/")
            if text.rstrip("\\/").lower().startswith(base.lower()) and len(text.rstrip("\\/")) >= len(base):
                inner = text.rstrip("\\/")[len(base):].replace("\\", "/").strip("/")
                if self.loc.tree.exists(inner):
                    return self._set_location(self.loc.at(inner), select)
        p = Path(text)
        if p.is_dir():
            return self._set_location(FsLocation(str(p.resolve())), select)
        if p.is_file():
            return self.open_archive(str(p))
        found = split_archive_path(text)
        if found:
            arc, inner = found
            if self.open_archive(arc, quiet=False):
                if inner and isinstance(self.loc, ArchiveLocation) and self.loc.tree.exists(inner):
                    self._set_location(self.loc.at(inner))
                return True
            return False
        message(self, "PR7-Z", f"Can't find '{text}'.")
        self.path.setEditText(self.loc.display)
        return False

    def _set_location(self, loc, select: str | None = None) -> bool:
        if isinstance(loc, FsLocation) and loc.path and not os.access(loc.path, os.R_OK):
            message(self, "PR7-Z", f"Access is denied: {loc.path}")
            return False
        self.loc = loc
        self.populate(select)
        if isinstance(loc, FsLocation) and loc.path:
            self.settings.setValue("last_folder", loc.path)
            for d in self.dir_watcher.directories():
                self.dir_watcher.removePath(d)
            self.dir_watcher.addPath(loc.path)
        self._remember(loc.display)
        return True

    def populate(self, select: str | None = None):
        loc = self.loc
        try:
            entries = loc.entries(self.show_hidden)
        except OSError as e:
            message(self, "PR7-Z", str(e))
            entries = []
        cols = loc.columns
        sort_col = self.proxy.sortColumn()
        sort_order = self.proxy.sortOrder()
        same = cols == self.model.cols
        self._populating = True
        self._restoring = True  # the reset puts column widths back to defaults: don't save those as the user's
        self.model.set_entries(entries, cols)
        widths = self.settings.value("widths/" + ",".join(cols))
        defaults = {"Name": 320, "Size": 110, "Packed Size": 110, "Modified": 150, "Created": 150,
                    "Attributes": 90, "Encrypted": 90, "CRC": 100, "Method": 150, "Total Size": 130,
                    "Free Space": 130, "Type": 90}
        self._restoring = True
        for i, c in enumerate(cols):
            w = int(widths[i]) if widths and i < len(widths) else defaults.get(c, 120)
            self.view.header().resizeSection(i, w)
        self._restoring = False
        self.view.sortByColumn(sort_col if same and sort_col >= 0 else 0, sort_order if same else Qt.AscendingOrder)
        self.path.blockSignals(True)
        self.path.setEditText(loc.display)
        self.path.blockSignals(False)
        title = loc.display if not isinstance(loc, FsLocation) or loc.path else "Computer"
        self.setWindowTitle(f"{title} - Paragon PR7-Z")
        self._populating = False
        if select:
            self._select_name(select)
        elif self.proxy.rowCount():
            self.view.setCurrentIndex(self.proxy.index(0, 0))
            self.view.clearSelection()
        self._update_actions()
        self._update_status()

    def _select_name(self, name: str):
        for r in range(self.proxy.rowCount()):
            idx = self.proxy.index(r, 0)
            if idx.data(ENTRY_ROLE).name == name:
                self.view.setCurrentIndex(idx)
                self.view.scrollTo(idx)
                return

    def _save_widths(self):
        if getattr(self, "_restoring", False) or not self.model.cols:
            return
        cols = self.loc.columns
        self.settings.setValue("widths/" + ",".join(cols),
                               [self.view.header().sectionSize(i) for i in range(len(cols))])

    def refresh(self):
        cur = self.view.currentIndex()
        name = cur.siblingAtColumn(0).data(ENTRY_ROLE).name if cur.isValid() else None
        if isinstance(self.loc, ArchiveLocation):
            self._reload_archive()
        self.populate(name)

    def go_up(self):
        loc = self.loc
        parent = loc.parent()
        if parent is None:
            return
        if isinstance(loc, ArchiveLocation):
            came_from = loc.inner.rsplit("/", 1)[-1] if loc.inner else Path(loc.display_archive).name
        else:
            came_from = Path(loc.path).name or loc.path
        self._set_location(parent, came_from)

    def open_root(self):
        if isinstance(self.loc, ArchiveLocation):
            self._set_location(self.loc.at(""))
        elif self.loc.path:
            self._set_location(FsLocation(Path(self.loc.path).anchor))

    def _remember(self, display: str):
        hist = [h for h in (self.settings.value("history") or []) if h != display]
        hist.insert(0, display)
        hist = hist[:30]
        self.settings.setValue("history", hist)
        self.path.blockSignals(True)
        self.path.clear()
        self.path.addItems(hist)
        self.path.setEditText(display)
        self.path.blockSignals(False)

    # ================================================================ selection
    def selected(self) -> list[Entry]:
        rows = self.view.selectionModel().selectedRows(0)
        return [r.data(ENTRY_ROLE) for r in sorted(rows, key=lambda i: i.row())]

    def focused(self) -> Entry | None:
        i = self.view.currentIndex()
        return i.siblingAtColumn(0).data(ENTRY_ROLE) if i.isValid() else None

    def targets(self) -> list[Entry]:
        """The selection, or the focused item if nothing is selected (as 7-Zip acts)."""
        sel = self.selected()
        if sel:
            return sel
        f = self.focused()
        return [f] if f else []

    def _update_status(self):
        if getattr(self, "_populating", False):
            return
        sel = self.selected()
        entries = sel or self.model.entries
        size = sum(e.size or 0 for e in entries if e.kind != "drive")
        packed = sum(e.packed or 0 for e in entries if e.kind != "drive")
        self.status[0].setText(f"{len(sel)} object(s) selected" if sel else f"{len(entries)} object(s)")
        self.status[1].setText(fmt_size(size) if entries else "")
        self.status[2].setText(fmt_size(packed) if isinstance(self.loc, ArchiveLocation) and entries else "")
        f = self.focused()
        self.status[3].setText(f.modified.strftime("%Y-%m-%d %H:%M:%S") if f and f.modified else "")
        self._update_actions()

    # ================================================================ opening
    def open_selected(self, inside: bool = False, outside: bool = False):
        e = self.focused()
        if not e:
            return
        if e.is_dir and not outside:
            if isinstance(self.loc, ArchiveLocation):
                return self._set_location(self.loc.at(e.path))
            return self._set_location(FsLocation(e.path))
        if isinstance(self.loc, FsLocation):
            if outside:
                return self._shell_open(e.path)
            if inside or e.kind == "archive":
                if self.open_archive(e.path, quiet=not inside):
                    return
                if inside:
                    return
            return self._shell_open(e.path)
        # inside an archive
        if (inside or e.kind == "archive") and not outside:
            path = self._extract_to_temp([e])
            if path:
                self.open_archive(path[0], display=self.loc.display + e.name, outer=self.loc,
                                  quiet=not inside)
            return
        paths = self._extract_to_temp([e], watch=True)
        if paths:
            self._shell_open(paths[0])

    def open_archive(self, path: str, display: str | None = None, outer=None, quiet: bool = False,
                     archive_type: str = "") -> bool:
        password = None
        while True:
            try:
                info = engine.list_archive(path, password, self.exe, archive_type)
                break
            except engine.ArchiveError as e:
                if e.kind == "password":
                    if password is not None:
                        message(self, "PR7-Z", "Wrong password.", subtitle="Open archive")
                    password = PasswordDialog.get(self, path)
                    if password is None:
                        return False
                    continue
                if quiet and e.kind == "open":
                    return False
                message(self, "PR7-Z", f"Can not open the file as archive:\n{path}", subtitle="Open archive",
                        detail=e.details.strip())
                return False
        if outer is None:
            outer = FsLocation(str(Path(path).parent))
        loc = ArchiveLocation(archive=path, display_archive=display or str(Path(path)), tree=ArchiveTree(info),
                              password=password, outer=outer, archive_type=archive_type)
        return self._set_location(loc)

    def _reload_archive(self):
        loc = self.loc
        try:
            info = engine.list_archive(loc.archive, loc.password, self.exe, loc.archive_type)
        except engine.ArchiveError as e:
            message(self, "PR7-Z", str(e))
            return
        loc.tree = ArchiveTree(info)
        if not loc.tree.exists(loc.inner):
            loc.inner = ""

    def _shell_open(self, path: str):
        if os.name == "nt":
            try:
                os.startfile(path)  # noqa: S606 - opening the user's own file
                return
            except OSError as e:
                message(self, "PR7-Z", str(e))
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _archive_temp(self) -> Path:
        key = hashlib.sha1(self.loc.archive.encode()).hexdigest()[:10]
        d = self.temp_root / key
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _need_password(self, entries: list[Entry]) -> bool:
        """Ask for the password before extracting encrypted items (names visible, data encrypted)."""
        loc = self.loc
        if loc.password is not None:
            return True
        paths = loc.tree.all_under([e.path for e in entries])
        if any(loc.tree.items[p].encrypted for p in paths if p in loc.tree.items):
            pw = PasswordDialog.get(self, loc.display_archive)
            if pw is None:
                return False
            loc.password = pw
        return True

    def _extract_to_temp(self, entries: list[Entry], watch: bool = False, flat_base: bool = False) -> list[str]:
        """Extract items to PR7-Z's temp folder (full paths kept, so edits can go back in)."""
        loc = self.loc
        if not self._need_password(entries):
            return []
        root = self._archive_temp()
        if flat_base:
            root = root / f"drag-{os.urandom(3).hex()}"
        opts = ExtractOptions(overwrite="overwrite", password=loc.password or "", archive_type=loc.archive_type)
        steps = operations.extract_steps(self.exe, loc.archive, str(root), opts, [e.path for e in entries],
                                         base=loc.inner if flat_base else "")
        res = run_job(Job("Extracting", steps), self, password_hint=loc.display_archive)
        if not res.ok:
            return []
        out = []
        for e in entries:
            rel = e.path[len(loc.inner) + 1:] if flat_base and loc.inner else e.path
            p = root.joinpath(*rel.split("/"))
            if p.exists():
                out.append(str(p))
                if watch and p.is_file():
                    self.watches[str(p)] = (loc.archive, loc.password, str(root), e.path,
                                            isinstance(loc.outer, ArchiveLocation), p.stat().st_mtime)
                    self.watcher.addPath(str(p))
        return out

    def _temp_file_changed(self, path: str):
        w = self.watches.get(path)
        if not w or not os.path.exists(path):
            return
        archive, password, root, item, nested, mtime = w
        if os.path.getmtime(path) == mtime:
            return
        self.watches[path] = (*w[:5], os.path.getmtime(path))
        if path not in self.watcher.files():
            self.watcher.addPath(path)  # editors that replace the file drop the watch
        if nested:
            message(self, "PR7-Z", f"'{Path(path).name}' was modified, but it is inside an archive that is itself "
                    "inside another archive. Extract the inner archive first to update it.")
            return
        if confirm(self, "PR7-Z", f"File '{Path(path).name}' was modified.\n"
                                  f"Do you want to update it in the archive?"):
            res = run_job(Job("Updating", operations.update_from_temp_steps(self.exe, archive, root, item,
                                                                            password or "")), self)
            if res.ok and isinstance(self.loc, ArchiveLocation) and self.loc.archive == archive:
                self.refresh()

    # ================================================================ toolbar actions
    def _toolbar(self, name: str):
        {"add": self.do_add, "extract": self.do_extract, "test": self.do_test, "copy": self.do_copy,
         "move": self.do_move, "delete": self.do_delete, "info": self.do_info}[name]()

    def do_add(self):
        if isinstance(self.loc, ArchiveLocation):
            files, _ = QFileDialog.getOpenFileNames(self, "Add files to archive")
            if files:
                self.drop_in(files, False)
            return
        files = [e.path for e in self.targets() if e.kind != "drive"]
        if not files:
            message(self, "PR7-Z", "Select one or more files or folders to add.")
            return
        self.add_files(files)

    def add_files(self, files: list[str], archive: str | None = None):
        d = AddDialog(files, archive, self)
        if d.exec() != AddDialog.Accepted:
            return
        arc, opts = d.archive_path(), d.options()
        res = run_job(Job(f"Compressing {Path(arc).name}", operations.add_steps(self.exe, arc, files, opts)), self)
        if isinstance(self.loc, FsLocation):
            self.populate(Path(arc).name if res.ok else None)

    def do_extract(self, here: bool = False):
        if isinstance(self.loc, ArchiveLocation):
            loc = self.loc
            sel = self.selected()
            dest = operations.default_extract_dir(loc.display_archive if os.path.exists(loc.display_archive)
                                                  else loc.archive)
            d = ExtractDialog(loc.display_archive, dest, self, encrypted=loc.tree.info.encrypted,
                              password=loc.password or "", history=self.settings.value("extract_history") or [])
            if d.exec() != ExtractDialog.Accepted:
                return
            opts = d.options()
            opts.archive_type = loc.archive_type
            if opts.password:
                loc.password = opts.password
            self._extract_history(d.destination())
            items = [e.path for e in sel] if sel else None
            steps = operations.extract_steps(self.exe, loc.archive, d.destination(), opts, items,
                                             base=loc.inner if items else "")
            total = sum(e.size or 0 for e in sel) if sel else sum(i.size or 0 for i in loc.tree.info.items)
            run_job(Job(f"Extracting {Path(loc.display_archive).name}", steps), self, total,
                    password_hint=loc.display_archive)
            return
        archives = [e.path for e in self.targets() if e.kind != "folder" and e.kind != "drive"]
        if not archives:
            message(self, "PR7-Z", "Select one or more archives to extract.")
            return
        self.extract_archives(archives)

    def extract_archives(self, archives: list[str], dest: str | None = None, ask: bool = True):
        if ask:
            first = archives[0]
            default = operations.default_extract_dir(first) if len(archives) == 1 \
                else str(Path(first).parent / "*")
            d = ExtractDialog(first if len(archives) == 1 else f"{len(archives)} archives", default, self,
                              history=self.settings.value("extract_history") or [])
            if d.exec() != ExtractDialog.Accepted:
                return
            opts, dest = d.options(), d.destination()
            self._extract_history(dest)
        else:
            opts = ExtractOptions()
        steps = []
        for a in archives:
            out = dest.replace("*", Path(operations.default_extract_dir(a)).name) if dest else str(Path(a).parent)
            steps += operations.extract_steps(self.exe, a, out, opts)
        run_job(Job("Extracting", steps), self)
        if isinstance(self.loc, FsLocation):
            self.populate()

    def _extract_history(self, dest: str):
        h = [x for x in (self.settings.value("extract_history") or []) if x != dest]
        self.settings.setValue("extract_history", ([dest] + h)[:15])

    def do_test(self):
        if isinstance(self.loc, ArchiveLocation):
            run_job(Job(f"Testing {Path(self.loc.display_archive).name}",
                        operations.test_steps(self.exe, [self.loc.archive], self.loc.password or "",
                                              self.loc.archive_type)), self,
                    keep_open=True, password_hint=self.loc.display_archive)
            return
        archives = [e.path for e in self.targets() if e.kind not in ("folder", "drive")]
        if archives:
            run_job(Job("Testing", operations.test_steps(self.exe, archives)), self, keep_open=True)

    def do_copy(self):
        sel = self.targets()
        if not sel:
            return
        if isinstance(self.loc, ArchiveLocation):  # Copy from an archive = extract the selection
            loc = self.loc
            dest = str(Path(loc.display_archive).parent) if os.path.exists(loc.display_archive) else str(Path.home())
            d = CopyDialog("Copy", dest, f"{len(sel)} item(s) from {Path(loc.display_archive).name}", self)
            if d.exec() != CopyDialog.Accepted or not self._need_password(sel):
                return
            steps = operations.extract_steps(self.exe, loc.archive, d.dest.text(),
                                             ExtractOptions(password=loc.password or "",
                                                            archive_type=loc.archive_type), [e.path for e in sel],
                                             base=loc.inner)
            run_job(Job("Copying", steps), self, sum(e.size or 0 for e in sel))
            return
        self._fs_copy([e.path for e in sel], move=False)

    def do_move(self):
        if isinstance(self.loc, ArchiveLocation):
            return
        sel = self.targets()
        if sel:
            self._fs_copy([e.path for e in sel], move=True)

    def _fs_copy(self, paths: list[str], move: bool, dest: str | None = None):
        if dest is None:
            title = "Move" if move else "Copy"
            d = CopyDialog(title, self.settings.value("copy_dest", self.loc.path or str(Path.home())),
                           f"{len(paths)} item(s)", self)
            if d.exec() != CopyDialog.Accepted:
                return
            dest = d.dest.text().strip()
            self.settings.setValue("copy_dest", dest)
        run_job(Job("Moving" if move else "Copying", operations.fs_copy_steps(paths, dest, move)), self)
        self.refresh()

    def do_delete(self, permanent: bool = False):
        sel = self.targets()
        if not sel or any(e.kind == "drive" for e in sel):
            return
        what = f"'{sel[0].name}'" if len(sel) == 1 else f"these {len(sel)} items"
        if isinstance(self.loc, ArchiveLocation):
            if not confirm(self, "Confirm Deleting", f"Are you sure you want to delete {what} from the archive?"):
                return
            loc = self.loc
            run_job(Job("Deleting", operations.delete_steps(self.exe, loc.archive, [e.path for e in sel],
                                                            loc.password or "")), self)
            self.refresh()
            return
        verb = "permanently delete" if permanent else "move"
        tail = "" if permanent else " to the Recycle Bin"
        if not confirm(self, "Confirm Deleting", f"Are you sure you want to {verb} {what}{tail}?"):
            return
        from PySide6.QtCore import QFile
        failed = []
        for e in sel:
            try:
                if permanent:
                    shutil.rmtree(e.path) if e.is_dir else os.remove(e.path)
                elif not QFile.moveToTrash(e.path)[0]:
                    failed.append(e.name)
            except OSError as err:
                failed.append(f"{e.name}: {err}")
        if failed:
            message(self, "PR7-Z", "Some items could not be deleted.", detail="\n".join(failed))
        self.refresh()

    def do_info(self):
        loc = self.loc
        sel = self.targets()
        sections = []
        if isinstance(loc, ArchiveLocation):
            for e in sel[:1]:
                item = e.extra.get("item")
                rows = [("Path", e.path), ("Folder", "+" if e.is_dir else "-"), ("Size", fmt_size(e.size)),
                        ("Packed Size", fmt_size(e.packed))]
                if item:
                    rows += [(k, v) for k, v in item.props.items() if k not in ("Path", "Folder", "Size",
                                                                                "Packed Size") and v]
                sections.append((e.name, rows))
            sections.append((Path(loc.display_archive).name,
                             [(k, v) for k, v in loc.tree.info.props.items() if v] +
                             [("Items", str(len(loc.tree.info.items)))]))
        else:
            for e in sel[:1]:
                rows = [("Name", e.name), ("Path", e.path), ("Size", fmt_size(e.size)),
                        ("Modified", e.value("Modified")[0]), ("Created", e.value("Created")[0]),
                        ("Attributes", e.attributes)]
                sections.append((e.name, rows))
                if e.kind == "archive":
                    try:
                        info = engine.list_archive(e.path, exe=self.exe)
                        sections.append(("Archive", [(k, v) for k, v in info.props.items() if v] +
                                         [("Items", str(len(info.items)))]))
                    except engine.ArchiveError:
                        pass
        if sections:
            PropertiesDialog("Properties", sections, self).exec()

    # ================================================================ file menu
    def do_rename(self):
        e = self.focused()
        if not e or e.kind == "drive":
            return
        new = ask_text(self, "Rename", "New name", e.name)
        if not new or new == e.name:
            return
        if isinstance(self.loc, ArchiveLocation):
            loc = self.loc
            run_job(Job("Renaming", operations.rename_steps(self.exe, loc.archive, e.path, loc.item_path(new),
                                                            loc.password or "")), self)
            self.refresh()
            self._select_name(new)
            return
        try:
            os.rename(e.path, str(Path(e.path).with_name(new)))
        except OSError as err:
            message(self, "PR7-Z", str(err))
        self.populate(new)

    def do_new_folder(self):
        name = ask_text(self, "Create Folder", "Folder name", "New Folder")
        if not name:
            return
        if isinstance(self.loc, ArchiveLocation):
            loc = self.loc
            run_job(Job("Creating folder", operations.new_folder_steps(self.exe, loc.archive, loc.inner, name,
                                                                       loc.password or "")), self)
            self.refresh()
        elif self.loc.path:
            try:
                Path(self.loc.path, name).mkdir()
            except OSError as err:
                message(self, "PR7-Z", str(err))
            self.populate(name)
        self._select_name(name)

    def do_new_file(self):
        if not isinstance(self.loc, FsLocation) or not self.loc.path:
            return
        name = ask_text(self, "Create File", "File name", "New File.txt")
        if name:
            try:
                Path(self.loc.path, name).touch(exist_ok=False)
            except OSError as err:
                message(self, "PR7-Z", str(err))
            self.populate(name)

    def do_edit(self):
        e = self.focused()
        if not e or e.is_dir:
            return
        path = e.path if isinstance(self.loc, FsLocation) else (self._extract_to_temp([e], watch=True) or [None])[0]
        if not path:
            return
        editor = self.settings.value("editor", "notepad.exe" if os.name == "nt" else "")
        if editor:
            try:
                subprocess.Popen([editor, path])
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def do_hash(self, method: str):
        if isinstance(self.loc, ArchiveLocation):
            files = self._extract_to_temp(self.targets())
        else:
            files = [e.path for e in self.targets() if e.kind != "drive"]
        if not files:
            return
        job = Job("Checksum", [Step("Calculating checksum", engine.hash_args(self.exe, files, method))])
        res = run_job(job, self)
        if res.log:
            TextDialog("Checksum information", "CHECKSUM", "\n".join(_hash_lines(res.log)), self).exec()

    def do_split(self):
        e = self.focused()
        if not e or e.is_dir or not isinstance(self.loc, FsLocation):
            return
        size = ask_text(self, "Split File", "Split to volumes, bytes (e.g. 100M, 700M, 4092M)", "100M")
        if not size:
            return
        n = _parse_size(size)
        if not n:
            message(self, "PR7-Z", "Incorrect volume size.")
            return
        parts = operations.split_file(e.path, n)
        self.populate(Path(parts[0]).name)

    def do_combine(self):
        e = self.focused()
        if not e or not isinstance(self.loc, FsLocation):
            return
        try:
            out = operations.combine_files(e.path)
        except (ValueError, OSError) as err:
            message(self, "PR7-Z", str(err))
            return
        self.populate(Path(out).name)

    # ================================================================ edit menu
    def select_all(self):
        self.view.selectAll()

    def deselect_all(self):
        self.view.clearSelection()

    def invert_selection(self):
        sm = self.view.selectionModel()
        from PySide6.QtCore import QItemSelectionModel
        for r in range(self.proxy.rowCount()):
            sm.select(self.proxy.index(r, 0), QItemSelectionModel.Toggle | QItemSelectionModel.Rows)

    def select_mask(self, on: bool = True):
        mask = ask_text(self, "Select" if on else "Deselect", "Mask", "*")
        if mask:
            self._select_where(lambda e: fnmatch.fnmatch(e.name.lower(), mask.lower()), on)

    def select_type(self, on: bool = True):
        f = self.focused()
        if not f:
            return
        ext = Path(f.name).suffix.lower()
        self._select_where(lambda e: (Path(e.name).suffix.lower() == ext) and e.is_dir == f.is_dir, on)

    def _select_where(self, pred, on: bool):
        from PySide6.QtCore import QItemSelectionModel
        sm = self.view.selectionModel()
        flag = (QItemSelectionModel.Select if on else QItemSelectionModel.Deselect) | QItemSelectionModel.Rows
        for r in range(self.proxy.rowCount()):
            idx = self.proxy.index(r, 0)
            if pred(idx.data(ENTRY_ROLE)):
                sm.select(idx, flag)

    # ================================================================ drag and drop
    def paths_for_drag(self) -> list[str]:
        sel = self.targets()
        if isinstance(self.loc, FsLocation):
            return [e.path for e in sel if e.kind != "drive"]
        return self._extract_to_temp(sel, flat_base=True)

    def drop_in(self, paths: list[str], move: bool = False):
        loc = self.loc
        if isinstance(loc, ArchiveLocation):
            if isinstance(loc.outer, ArchiveLocation):
                message(self, "PR7-Z", "This archive is inside another archive and can't be changed here.")
                return
            if not confirm(self, "Copy", "Are you sure you want to copy files to archive\n"
                                         f"'{loc.display}'?"):
                return
            fmt = loc.tree.info.type.lower() if loc.tree.info.type.lower() in engine.CREATE_FORMATS else "7z"
            opts = AddOptions(format=fmt, password=loc.password or "",
                              encrypt_names=bool(loc.password) and fmt == "7z" and not loc.tree.items)
            res = run_job(Job("Adding", operations.add_steps(self.exe, loc.archive, paths, opts,
                                                             base_in_archive=loc.inner)), self)
            if res.ok or res.errors:
                self.refresh()
            return
        if not loc.path:
            return
        self._fs_copy(paths, move, dest=loc.path)

    # ================================================================ menus
    def _act(self, menu: QMenu, text: str, slot=None, shortcut=None, enabled_when=None, checkable=False) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WindowShortcut)
        if slot:
            a.triggered.connect(lambda _=False: slot())
        a.setCheckable(checkable)
        a._enabled_when = enabled_when
        menu.addAction(a)
        self._actions.append(a)
        return a

    def _build_menus(self):
        self._actions: list[QAction] = []
        bar = self.menuBar()
        fs = lambda: isinstance(self.loc, FsLocation) and bool(self.loc.path)  # noqa: E731
        arc = lambda: isinstance(self.loc, ArchiveLocation)  # noqa: E731
        has = lambda: bool(self.targets()) and self.targets()[0].kind != "drive"  # noqa: E731
        one_file = lambda: (self.focused() is not None and not self.focused().is_dir)  # noqa: E731

        m = bar.addMenu("&File")
        self._act(m, "&Open", self.open_selected, "Return", has)
        self._act(m, "Open &Inside", lambda: self.open_selected(inside=True), "Ctrl+PgDown", one_file)
        self._act(m, "Open Out&side", lambda: self.open_selected(outside=True), "Shift+Return", has)
        m.addSeparator()
        self._act(m, "&Edit", self.do_edit, "F4", one_file)
        self._act(m, "Rena&me", self.do_rename, "F2", has)
        self._act(m, "&Copy To...", self.do_copy, "F5", has)
        self._act(m, "&Move To...", self.do_move, "F6", lambda: fs() and has())
        self._act(m, "&Delete", self.do_delete, "Delete", has)
        self._act(m, "Delete Permanently", lambda: self.do_delete(permanent=True), "Shift+Delete",
                  lambda: fs() and has())
        m.addSeparator()
        self._act(m, "&Split file...", self.do_split, None, lambda: fs() and one_file())
        self._act(m, "Com&bine files...", self.do_combine, None, lambda: fs() and one_file())
        m.addSeparator()
        self._act(m, "P&roperties", self.do_info, "Alt+Return", has)
        hm = m.addMenu("CRC")
        for label, meth in HASHES:
            self._act(hm, label, lambda meth=meth: self.do_hash(meth), None, has)
        m.addSeparator()
        self._act(m, "Create Folder", self.do_new_folder, "F7", lambda: fs() or arc())
        self._act(m, "Create File", self.do_new_file, "Ctrl+N", fs)
        m.addSeparator()
        self._act(m, "E&xit", self.close, "Alt+F4")

        m = bar.addMenu("&Edit")
        self._act(m, "Select &All", self.select_all, "Ctrl+A")
        self._act(m, "Deselect All", self.deselect_all, "Ctrl+Shift+A")
        self._act(m, "&Invert Selection", self.invert_selection, "*")
        self._act(m, "Select...", lambda: self.select_mask(True), "+")
        self._act(m, "Deselect...", lambda: self.select_mask(False), "-")
        self._act(m, "Select by Type", lambda: self.select_type(True), "Alt++")
        self._act(m, "Deselect by Type", lambda: self.select_type(False), "Alt+-")

        m = bar.addMenu("&View")
        self.flat_act = self._act(m, "Flat View", self._toggle_flat, None, arc, checkable=True)
        self.hidden_act = self._act(m, "Show Hidden Files", self._toggle_hidden, None, None, checkable=True)
        self.hidden_act.setChecked(self.show_hidden)
        m.addSeparator()
        self._act(m, "Open Root Folder", self.open_root, "\\")
        self._act(m, "Up One Level", self.go_up)
        self._act(m, "Folders History...", self.show_history, "Alt+F12")
        self._act(m, "&Refresh", self.refresh, "Ctrl+R")
        self.auto_refresh = self._act(m, "Auto Refresh", None, None, None, checkable=True)
        self.auto_refresh.setChecked(self.settings.value("auto_refresh", True, type=bool))
        self.auto_refresh.toggled.connect(lambda on: self.settings.setValue("auto_refresh", on))

        self.fav_menu = bar.addMenu("F&avorites")
        self._build_favorites()

        m = bar.addMenu("&Tools")
        self._act(m, "&Options...", self.show_options)
        self._act(m, "&Benchmark", self.run_benchmark)

        m = bar.addMenu("&Help")
        self._act(m, "&Contents...", self.show_help, "F1")
        m.addSeparator()
        self._act(m, "Check for &Updates...", self.check_updates)
        self._act(m, "&About PR7-Z...", lambda: AboutDialog(self, engine_version(self.exe)).exec())

    def check_updates(self):
        from . import update_ui
        update_ui.check(self)

    def _update_actions(self):
        for a in getattr(self, "_actions", []):
            cond = getattr(a, "_enabled_when", None)
            a.setEnabled(bool(cond()) if cond else True)
        arc = isinstance(self.loc, ArchiveLocation)
        keys = self.toolbar.keys
        has = bool(self.targets()) and self.targets()[0].kind != "drive"
        keys["move"].setEnabled(not arc and has)
        keys["add"].setEnabled(arc or has)
        for k in ("copy", "delete", "info"):
            keys[k].setEnabled(has or (k == "info" and arc))
        if hasattr(self, "flat_act"):
            self.flat_act.setChecked(arc and self.loc.flat)

    def _context_menu(self, pos):
        m = QMenu(self)
        names = ["&Open", "Open &Inside", "Open Out&side", None, "&Edit", "Rena&me", "&Copy To...", "&Move To...",
                 "&Delete", None, "P&roperties"]
        by_text = {a.text(): a for a in self._actions}
        for n in names:
            if n is None:
                m.addSeparator()
            elif n in by_text:
                m.addAction(by_text[n])
        m.addSeparator()
        sub = m.addMenu("PR7-Z")
        sub.addAction("Add to archive...", self.do_add)
        sub.addAction("Extract files...", self.do_extract)
        sub.addAction("Test archive", self.do_test)
        m.exec(self.view.viewport().mapToGlobal(pos))

    def _toggle_flat(self):
        if isinstance(self.loc, ArchiveLocation):
            self.loc.flat = not self.loc.flat
            self.populate()

    def _toggle_hidden(self):
        self.show_hidden = self.hidden_act.isChecked()
        self.settings.setValue("show_hidden", self.show_hidden)
        self.populate()

    def _build_favorites(self):
        m = self.fav_menu
        m.clear()
        marks = list(self.settings.value("bookmarks") or [""] * 10)
        marks += [""] * (10 - len(marks))
        add = m.addMenu("&Add folder to Favorites as")
        for i in range(10):
            a = add.addAction(f"Bookmark {i}")
            a.setShortcut(QKeySequence(f"Alt+Shift+{i}"))
            a.triggered.connect(lambda _=False, i=i: self._set_bookmark(i))
        m.addSeparator()
        for i in range(10):
            a = m.addAction(f"{i}  {marks[i] or '-'}")
            a.setShortcut(QKeySequence(f"Alt+{i}"))
            a.setEnabled(bool(marks[i]))
            a.triggered.connect(lambda _=False, p=marks[i]: self.navigate(p))

    def _set_bookmark(self, i: int):
        marks = list(self.settings.value("bookmarks") or [""] * 10)
        marks += [""] * (10 - len(marks))
        marks[i] = self.loc.display
        self.settings.setValue("bookmarks", marks)
        self._build_favorites()

    def show_history(self):
        d = HistoryDialog(list(self.settings.value("history") or []), self)
        if d.exec() == HistoryDialog.Accepted and d.chosen():
            self.navigate(d.chosen())

    def show_options(self):
        from .options import OptionsDialog
        OptionsDialog(self).exec()

    def run_benchmark(self):
        res = run_job(Job("Benchmark", [Step("Running 7-Zip benchmark (about 30 s)", engine.benchmark_args(self.exe),
                                             ok_codes=(0, 1))]), self, keep_open=False)
        if res.log:
            TextDialog("Benchmark", "BENCHMARK", "\n".join(res.log), self).exec()

    def show_help(self):
        TextDialog("PR7-Z Help", "HELP", HELP_TEXT, self).exec()

    # ================================================================ window
    def closeEvent(self, e):
        self.settings.setValue("size", self.size())
        shutil.rmtree(self.temp_root, ignore_errors=True)
        super().closeEvent(e)


def _hash_lines(log: list[str]) -> list[str]:
    keep, on = [], False
    for ln in log:
        if ln.startswith("7-Zip") or ln.startswith("Scanning") or ln.startswith("64-bit"):
            continue
        if ln.startswith("Name") or ln.startswith("CRC32") or "------" in ln:
            on = True
        if on or ln.startswith("Size:") or "for data" in ln:
            keep.append(ln)
    return keep or log


def _parse_size(text: str) -> int | None:
    t = text.strip().split(" ")[0].upper()
    mult = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30}.get(t[-1:], 1)
    num = t[:-1] if t[-1:] in "KMG" else t
    return int(float(num) * mult) if num.replace(".", "").isdigit() else None


HELP_TEXT = """PARAGON PR7-Z - works the way 7-Zip File Manager works.

Browsing
  Enter / double-click   Open a folder or archive (archives open like folders); other files open in their app
  Backspace              Up one level            \\  Root folder
  Ctrl+PgDown            Open inside (open any file as an archive)
  Shift+Enter            Open outside (in its Windows app)
  Alt+F12                Folders history         Ctrl+R  Refresh
  Alt+1..9 / Alt+Shift+1..9   Go to / set a favorite folder

Files
  F2 Rename   F4 Edit   F5 Copy to   F6 Move to   F7 New folder   Ctrl+N New file
  Del Delete (Recycle Bin; inside archives: delete from the archive)   Shift+Del Delete permanently
  Alt+Enter Properties

Selecting
  Ctrl+A all   * invert   + select by mask   - deselect by mask   Alt++ select by type

Archives
  Add, Extract, Test on the toolbar. Drop files onto an open archive to add them to the folder you're in;
  drag items out of an archive to extract them. Files opened from an archive and edited are offered back
  into the archive when you save them.

Explorer
  Tools > Options adds PR7-Z to the Explorer right-click menu (Extract Here, Extract to "name\\",
  Add to "name.7z" / "name.zip", Test, CRC SHA) and to "Open with" for archives.

Engine: the official 7-Zip (7z.exe) bundled with PR7-Z, so archives are 100% 7-Zip compatible.
"""
