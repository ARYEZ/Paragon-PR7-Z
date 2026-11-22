"""What the file list shows: the computer's drives, a folder on disk, or a folder inside an archive."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import engine
from .engine import ArchiveInfo

FS_COLUMNS = ["Name", "Size", "Modified", "Created", "Attributes"]
ARCHIVE_COLUMNS = ["Name", "Size", "Packed Size", "Modified", "Attributes", "Encrypted", "CRC", "Method"]
DRIVE_COLUMNS = ["Name", "Total Size", "Free Space", "Type", "Label"]
NUMERIC = {"Size", "Packed Size", "Total Size", "Free Space"}


@dataclass
class Entry:
    name: str
    kind: str                       # folder | file | archive | drive
    path: str                       # disk path, or the item's path inside the archive
    size: int | None = None
    packed: int | None = None
    modified: datetime | None = None
    created: datetime | None = None
    attributes: str = ""
    encrypted: bool | None = None
    crc: str = ""
    method: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def is_dir(self) -> bool:
        return self.kind in ("folder", "drive")

    def value(self, column: str):
        """(text, sort key) for a column."""
        from .dialogs import fmt_size
        if column == "Name":
            return self.name, self.name.casefold()
        if column in ("Size", "Total Size"):
            return fmt_size(self.size), self.size if self.size is not None else -1
        if column in ("Packed Size", "Free Space"):
            return fmt_size(self.packed), self.packed if self.packed is not None else -1
        if column in ("Modified", "Created"):
            d = self.modified if column == "Modified" else self.created
            return (d.strftime("%Y-%m-%d %H:%M") if d else ""), (d.timestamp() if d else 0.0)
        if column == "Attributes":
            return self.attributes, self.attributes
        if column == "Encrypted":
            t = "" if self.encrypted is None else ("+" if self.encrypted else "-")
            return t, t
        if column in ("CRC", "Method", "Type", "Label"):
            v = {"CRC": self.crc, "Method": self.method}.get(column, self.extra.get(column, ""))
            return v, str(v).casefold()
        return "", ""


def kind_for_file(name: str) -> str:
    return "archive" if name.rsplit(".", 1)[-1].lower() in engine.ARCHIVE_EXTS and "." in name else "file"


# --------------------------------------------------------------------------- disk
def _win_attrs(st) -> str:
    a = getattr(st, "st_file_attributes", None)
    if a is None:
        return ("D" if stat.S_ISDIR(st.st_mode) else "A") + ("" if st.st_mode & stat.S_IWUSR else "R")
    letters = [("R", stat.FILE_ATTRIBUTE_READONLY), ("H", stat.FILE_ATTRIBUTE_HIDDEN),
               ("S", stat.FILE_ATTRIBUTE_SYSTEM), ("D", stat.FILE_ATTRIBUTE_DIRECTORY),
               ("A", stat.FILE_ATTRIBUTE_ARCHIVE)]
    return "".join(ch for ch, bit in letters if a & bit)


def _created(st) -> datetime | None:
    t = getattr(st, "st_birthtime", None)
    if t is None and os.name == "nt":
        t = st.st_ctime
    return datetime.fromtimestamp(t) if t else None


def list_folder(path: str, show_hidden: bool = True) -> list[Entry]:
    out = []
    with os.scandir(path) as it:
        for e in it:
            try:
                st = e.stat(follow_symlinks=True)
            except OSError:
                continue
            is_dir = stat.S_ISDIR(st.st_mode)
            attrs = _win_attrs(st)
            if not show_hidden and ("H" in attrs or e.name.startswith(".") and os.name != "nt"):
                continue
            out.append(Entry(name=e.name, kind="folder" if is_dir else kind_for_file(e.name), path=e.path,
                             size=None if is_dir else st.st_size, modified=datetime.fromtimestamp(st.st_mtime),
                             created=_created(st), attributes=attrs))
    return out


def list_drives() -> list[Entry]:
    from PySide6.QtCore import QStorageInfo
    out = []
    for v in QStorageInfo.mountedVolumes():
        if not v.isValid() or not v.isReady():
            continue
        root = v.rootPath()
        if os.name != "nt" and root not in ("/",) and not root.startswith(("/media", "/mnt", "/home")):
            continue
        name = root.rstrip("/\\") + ("\\" if os.name == "nt" else "")
        out.append(Entry(name=name or "/", kind="drive", path=root, size=v.bytesTotal(), packed=v.bytesAvailable(),
                         extra={"Type": bytes(v.fileSystemType()).decode(errors="replace"), "Label": v.displayName()}))
    return out


# --------------------------------------------------------------------------- archives
class ArchiveTree:
    """An archive's flat item list as folders. Folders that only appear in paths are filled in,
    and folder sizes are the totals of what they hold, as 7-Zip FM shows them."""

    def __init__(self, info: ArchiveInfo):
        self.info = info
        self.children: dict[str, dict[str, Entry]] = {"": {}}
        self.items: dict[str, engine.Item] = {}
        for it in info.items:
            path = it.path.strip("/")
            if not path:
                continue
            self.items[path] = it
            parts = path.split("/")
            for i in range(1, len(parts)):
                parent, name = "/".join(parts[:i - 1]), parts[i - 1]
                d = "/".join(parts[:i])
                self.children.setdefault(parent, {})
                if name not in self.children[parent]:
                    self.children[parent][name] = Entry(name=name, kind="folder", path=d, attributes="D")
                self.children.setdefault(d, {})
            parent = "/".join(parts[:-1])
            kids = self.children.setdefault(parent, {})
            e = Entry(name=parts[-1], kind="folder" if it.is_dir else kind_for_file(parts[-1]), path=path,
                      size=None if it.is_dir else it.size, packed=None if it.is_dir else it.packed,
                      modified=it.modified, created=it.created, attributes=_short_attrs(it.attributes, it.is_dir),
                      encrypted=it.encrypted, crc=it.crc, method=it.method, extra={"item": it})
            if it.is_dir:
                self.children.setdefault(path, {})
                if parts[-1] in kids:  # an explicit folder entry: keep its dates
                    old = kids[parts[-1]]
                    old.modified, old.created, old.attributes = e.modified, e.created, e.attributes
                    old.extra = e.extra
                    continue
            kids[parts[-1]] = e
        self._totals("")

    def _totals(self, folder: str) -> tuple[int, int]:
        size = packed = 0
        for e in self.children.get(folder, {}).values():
            if e.kind == "folder":
                s, p = self._totals(e.path)
                e.size, e.packed = s, p
            s, p = e.size or 0, e.packed or 0
            size += s
            packed += p
        return size, packed

    def list(self, folder: str) -> list[Entry]:
        return list(self.children.get(folder.strip("/"), {}).values())

    def flat(self, folder: str = "") -> list[Entry]:
        """7-Zip's Flat View: every file under folder, named by its path from there."""
        base = folder.strip("/")
        files, stack = [], [base]
        while stack:
            for e in self.list(stack.pop()):
                (stack.append(e.path) if e.kind == "folder" else files.append(e))
        return [Entry(**{**e.__dict__, "name": e.path[len(base) + 1:] if base else e.path}) for e in files]

    def exists(self, folder: str) -> bool:
        return folder.strip("/") in self.children

    def all_under(self, paths: list[str]) -> list[str]:
        """Every item path at or below the given ones (what an operation on a folder touches)."""
        out = []
        for p in paths:
            p = p.strip("/")
            out += [k for k in self.items if k == p or k.startswith(p + "/")]
        return sorted(set(out))


def _short_attrs(a: str, is_dir: bool) -> str:
    """'D drwxr-xr-x' / ' -rw-r--r--' / 'A' -> the Windows letters 7-Zip shows first."""
    win = a.split(" ")[0].strip() if a else ""
    return win or ("D" if is_dir else "")


# --------------------------------------------------------------------------- locations
@dataclass
class FsLocation:
    path: str  # "" = the computer (drives)

    def entries(self, show_hidden=True) -> list[Entry]:
        return list_drives() if not self.path else list_folder(self.path, show_hidden)

    @property
    def columns(self) -> list[str]:
        return DRIVE_COLUMNS if not self.path else FS_COLUMNS

    @property
    def display(self) -> str:
        if not self.path:
            return "Computer" if os.name == "nt" else "/"
        p = str(Path(self.path))
        return p if p.endswith(os.sep) else p + os.sep

    def parent(self):
        if not self.path:
            return None
        p = Path(self.path)
        if p.parent == p:  # a drive root
            return FsLocation("") if os.name == "nt" else None
        return FsLocation(str(p.parent))


@dataclass
class ArchiveLocation:
    archive: str                 # the file 7z reads (a temp copy for archives inside archives)
    display_archive: str         # what the address bar shows for the archive itself
    tree: ArchiveTree
    inner: str = ""
    password: str | None = None
    outer: object = None         # the location the archive was opened from
    flat: bool = False
    archive_type: str = ""       # 7-Zip's -t type when opened with "Open archive >" (else by extension)

    def entries(self, show_hidden=True) -> list[Entry]:
        return self.tree.flat(self.inner) if self.flat else self.tree.list(self.inner)

    @property
    def columns(self) -> list[str]:
        return ARCHIVE_COLUMNS

    @property
    def display(self) -> str:
        sep = "\\" if os.name == "nt" else "/"
        inner = self.inner.replace("/", sep)
        return self.display_archive + sep + (inner + sep if inner else "")

    def at(self, inner: str) -> "ArchiveLocation":
        return ArchiveLocation(self.archive, self.display_archive, self.tree, inner.strip("/"), self.password,
                               self.outer, False, self.archive_type)

    def parent(self):
        if self.inner:
            return self.at(self.inner.rsplit("/", 1)[0] if "/" in self.inner else "")
        return self.outer

    def item_path(self, name: str) -> str:
        return f"{self.inner}/{name}" if self.inner else name


def split_archive_path(text: str) -> tuple[str, str] | None:
    """'D:\\Music\\x.7z\\Drums' -> ('D:\\Music\\x.7z', 'Drums'), if a file along the path exists."""
    p = Path(text.strip().strip('"'))
    parts = []
    while True:
        if p.is_file():
            return str(p), "/".join(reversed(parts))
        if p.parent == p or not str(p):
            return None
        parts.append(p.name)
        p = p.parent
