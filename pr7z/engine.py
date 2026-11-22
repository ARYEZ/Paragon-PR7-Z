"""The 7-Zip engine: finding 7z.exe, listing archives, building command lines, parsing progress.

PR7-Z does no compression itself: every archive operation runs the official 7-Zip console
program (7z.exe + 7z.dll, bundled in engine/), so formats, ratios and compatibility are exactly
7-Zip's. This module is pure Python (no Qt) so it can be tested on its own.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Switches used on every run: UTF-8 console output and list files, progress to stdout,
# errors to stdout too (so they arrive in order with the progress), and -y off: we answer prompts.
BASE_SWITCHES = ["-sccUTF-8", "-scsUTF-8", "-bsp1", "-bso1", "-bse1", "-bb1"]

# Formats 7-Zip can create (the "C" flag in `7z i`), in 7-Zip's Add dialog order.
CREATE_FORMATS = ["7z", "tar", "wim", "zip", "gzip", "bzip2", "xz"]
SINGLE_FILE_FORMATS = {"gzip", "bzip2", "xz"}  # compress one file only (7-Zip's rule)
FORMAT_EXT = {"7z": "7z", "tar": "tar", "wim": "wim", "zip": "zip", "gzip": "gz", "bzip2": "bz2", "xz": "xz"}
METHODS = {
    "7z": ["LZMA2", "LZMA", "PPMd", "BZip2"],
    "zip": ["Deflate", "Deflate64", "BZip2", "LZMA", "PPMd"],
    "gzip": ["Deflate"], "bzip2": ["BZip2"], "xz": ["LZMA2"], "tar": [], "wim": [],
}
ENCRYPTION = {"7z": ["AES-256"], "zip": ["ZipCrypto", "AES-256"]}

# Extensions PR7-Z opens as archives on double-click (7-Zip's own list, abridged to the common ones).
ARCHIVE_EXTS = {
    "7z", "zip", "rar", "r00", "tar", "gz", "tgz", "bz2", "tbz", "tbz2", "xz", "txz", "lzma", "zst", "tzst",
    "wim", "swm", "esd", "cab", "iso", "img", "dmg", "vhd", "vhdx", "vmdk", "arj", "lzh", "lha", "cpio", "rpm",
    "deb", "z", "taz", "chm", "msi", "squashfs", "xar", "pkg", "apfs", "001", "jar", "xpi", "apk", "zipx",
}


class EngineNotFound(RuntimeError):
    pass


class ArchiveError(RuntimeError):
    """kind: 'password' (missing or wrong password), 'open' (not an archive / can't open), 'error'."""

    def __init__(self, message: str, kind: str = "error", details: str = ""):
        super().__init__(message)
        self.kind = kind
        self.details = details


# --------------------------------------------------------------------------- finding 7z.exe
def _app_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller: files sit next to the exe (or in _MEIPASS)
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def find_7z() -> str:
    """The bundled engine first, then an installed 7-Zip, then PATH. PR7Z_7Z overrides all."""
    env = os.environ.get("PR7Z_7Z")
    if env:
        if Path(env).is_file():
            return env
        raise EngineNotFound(f"PR7Z_7Z points to {env}, which doesn't exist.")
    candidates = []
    if os.name == "nt":
        candidates.append(_app_dir() / "engine" / "7z.exe")
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
                     os.environ.get("ProgramFiles(x86)")):
            if base:
                candidates.append(Path(base) / "7-Zip" / "7z.exe")
    for c in candidates:
        if c.is_file():
            return str(c)
    for name in ("7zz", "7z", "7za"):
        found = shutil.which(name)
        if found:
            return found
    raise EngineNotFound("7-Zip's engine (7z.exe) wasn't found. It should be in the engine folder next to PR7-Z.")


def sfx_module(exe: str) -> Path | None:
    p = Path(exe).with_name("7z.sfx")
    return p if p.is_file() else None


# --------------------------------------------------------------------------- listing
@dataclass
class Item:
    path: str                      # always "/"-separated
    is_dir: bool
    size: int | None = None
    packed: int | None = None
    modified: datetime | None = None
    created: datetime | None = None
    attributes: str = ""
    encrypted: bool = False
    crc: str = ""
    method: str = ""
    comment: str = ""
    props: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass
class ArchiveInfo:
    path: str
    type: str = ""
    props: dict = field(default_factory=dict)   # the archive's own properties (Type, Method, Solid, ...)
    items: list[Item] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def encrypted(self) -> bool:
        return any(i.encrypted for i in self.items) or "7zAES" in self.props.get("Method", "") \
            or "AES" in self.props.get("Method", "")


def _int(v: str) -> int | None:
    v = v.strip()
    return int(v) if v.isdigit() else None


def _date(v: str) -> datetime | None:
    v = v.strip()
    if not v:
        return None
    m = re.match(r"(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)", v)
    if not m:
        return None
    try:
        return datetime(*map(int, m.groups()))
    except ValueError:
        return None


def _blocks(text: str) -> list[dict]:
    blocks, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = {}
            continue
        if " = " in line or line.rstrip().endswith(" ="):
            k, _, v = line.partition(" =")
            cur[k.strip()] = v[1:] if v.startswith(" ") else v
    if cur:
        blocks.append(cur)
    return blocks


_TAR_ALIASES = {"tgz", "tpz", "tbz", "tbz2", "txz", "tzst", "taz"}


def _stream_name(archive_path: str) -> str:
    name = Path(archive_path.replace("\\", "/")).name or "data"
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return name + "~"
    return stem + ".tar" if ext.lower() in _TAR_ALIASES else stem


def parse_slt(text: str, archive_path: str = "") -> ArchiveInfo:
    """Parse `7z l -slt` output: archive properties after '--', items after '----------'."""
    info = ArchiveInfo(path=archive_path)
    if "\n----------" not in text and "\n--\n" not in text:
        return info
    head, sep, body = text.partition("\n----------")
    if "\n--\n" in head:
        arch = head.split("\n--\n")[-1]
        props = {}
        for b in _blocks(arch):
            props.update(b)  # nested types (e.g. tar inside gz) report several blocks; last wins
        info.props = props
        info.type = props.get("Type", "")
    for line in head.splitlines():
        if line.startswith("WARNINGS") or line.startswith("WARNING"):
            info.warnings.append(line.strip())
    for b in _blocks(body):
        if "Path" not in b:
            if not ({"Size", "Packed Size"} & set(b)):
                continue
            # Single-stream formats that store no name (bzip2, some gzip/xz): 7-Zip names the item
            # after the archive minus its extension (x.txt.bz2 -> x.txt, x.tbz -> x.tar).
            b = dict(b, Path=_stream_name(archive_path or info.props.get("Path", "")))
        path = b["Path"].replace("\\", "/")
        attrs = b.get("Attributes", "")
        folder = b.get("Folder", "")
        is_dir = folder == "+" or (folder == "" and attrs.strip().startswith("D"))
        info.items.append(Item(
            path=path, is_dir=is_dir, size=_int(b.get("Size", "")), packed=_int(b.get("Packed Size", "")),
            modified=_date(b.get("Modified", "")), created=_date(b.get("Created", "")), attributes=attrs,
            encrypted=b.get("Encrypted", "") == "+", crc=b.get("CRC", ""), method=b.get("Method", ""),
            comment=b.get("Comment", ""), props=b))
    return info


NO_PASSWORD = "⁣"  # an invisible separator: a password nobody uses, so 7z fails instead of prompting


def _run(args: list[str], cwd: str | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: no console flashes
    return subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                          creationflags=flags)


def _classify(out: str) -> ArchiveError:
    low = out.lower()
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith(("ERROR", "Open ERROR"))]
    msg = lines[0] if lines else out.strip().splitlines()[-1] if out.strip() else "7-Zip failed."
    msg = re.sub(r"^(Open )?ERROR:\s*", "", msg)
    if "wrong password" in low or "encrypted archive" in low:
        return ArchiveError(msg, "password", out)
    if "cannot open the file as archive" in low or "can not open the file as archive" in low \
            or "cannot open" in low or "is not archive" in low:
        return ArchiveError(msg, "open", out)
    return ArchiveError(msg, "error", out)


def list_archive(archive: str, password: str | None = None, exe: str | None = None) -> ArchiveInfo:
    exe = exe or find_7z()
    args = [exe, "l", "-slt", "-sccUTF-8", f"-p{password if password is not None else NO_PASSWORD}", "--", archive]
    r = _run(args)
    out = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    if r.returncode not in (0, 1) or "----------" not in out:
        raise _classify(out + r.stderr.decode("utf-8", "replace"))
    return parse_slt(out, archive)


def is_archive(path: str, exe: str | None = None) -> bool:
    try:
        list_archive(path, exe=exe)
        return True
    except ArchiveError as e:
        return e.kind == "password"


# --------------------------------------------------------------------------- command lines
@dataclass
class AddOptions:
    format: str = "7z"
    level: int = 5                 # 0 store, 1 fastest, 3 fast, 5 normal, 7 maximum, 9 ultra
    method: str = ""               # "" = format default
    dictionary: str = ""           # e.g. "64m"; "" = default for the level
    word_size: str = ""            # e.g. "64"
    solid: str = ""                # "" default, "off", "on", or a size like "4g"
    threads: str = ""              # "" = all
    volumes: str = ""              # e.g. "100m" (7z's -v syntax)
    parameters: str = ""           # extra -m parameters, space separated (7-Zip's Parameters field)
    update_mode: str = "add"       # add | update | freshen | sync
    path_mode: str = "relative"    # relative | full | absolute
    sfx: bool = False
    shared: bool = False
    delete_after: bool = False
    password: str = ""
    encryption: str = "AES-256"
    encrypt_names: bool = False


# 7-Zip's update-mode switches (its GUI maps them the same way).
UPDATE_SWITCHES = {
    "add": [],
    "update": ["-up1q1r2x1y2z1w2"],
    "freshen": ["-up1q1r0x1y2z1w2"],
    "sync": ["-up1q0r2x1y2z1w2"],
}


def add_args(exe: str, archive: str, files: list[str], o: AddOptions, list_file: str | None = None) -> list[str]:
    a = [exe, "a", *BASE_SWITCHES, f"-t{o.format}", f"-mx={o.level}"]
    if o.method and o.format not in ("tar", "wim"):
        a.append(f"-m0={o.method}" if o.format == "7z" else f"-mm={o.method}")
    if o.dictionary:
        a.append(f"-md={o.dictionary}" if o.format == "7z" else f"-md={o.dictionary}")
    if o.word_size:
        a.append(f"-mfb={o.word_size}")
    if o.format == "7z" and o.solid:
        a.append(f"-ms={o.solid}")
    if o.threads and o.format not in ("tar", "wim"):
        a.append(f"-mmt={o.threads}")
    if o.volumes:
        a.append(f"-v{o.volumes}")
    for p in o.parameters.split():
        a.append(p if p.startswith("-") else f"-m{p}")
    a += UPDATE_SWITCHES.get(o.update_mode, [])
    if o.path_mode == "full":
        a.append("-spf2")
    elif o.path_mode == "absolute":
        a.append("-spf")
    if o.sfx and o.format == "7z":
        mod = sfx_module(exe)
        a.append(f"-sfx{mod}" if mod else "-sfx")
    if o.shared:
        a.append("-ssw")
    if o.delete_after:
        a.append("-sdel")
    if o.password and o.format in ENCRYPTION:
        a.append(f"-p{o.password}")
        if o.format == "zip" and o.encryption == "AES-256":
            a.append("-mem=AES256")
        if o.format == "7z" and o.encrypt_names:
            a.append("-mhe=on")
    a.append("--")
    a.append(archive)
    a += [f"@{list_file}"] if list_file else files
    return a


@dataclass
class ExtractOptions:
    path_mode: str = "full"        # full | none | absolute
    overwrite: str = "ask"         # ask | overwrite | skip | rename | rename_existing
    password: str = ""
    eliminate_root: bool = False   # 7-Zip's "Eliminate duplication of root folder" (-spe)
    keep_broken: bool = False


OVERWRITE_SWITCHES = {"ask": [], "overwrite": ["-aoa"], "skip": ["-aos"], "rename": ["-aou"],
                      "rename_existing": ["-aot"]}


def extract_args(exe: str, archive: str, out_dir: str, o: ExtractOptions, items: list[str] | None = None,
                 list_file: str | None = None) -> list[str]:
    cmd = "e" if o.path_mode == "none" else "x"
    a = [exe, cmd, *BASE_SWITCHES, f"-o{out_dir}", *OVERWRITE_SWITCHES[o.overwrite]]
    if o.path_mode == "absolute":
        a.append("-spf")
    if o.eliminate_root:
        a.append("-spe")
    if o.keep_broken:
        a.append("-kb")
    if o.password:  # no -p: if the archive is encrypted 7z asks, and PR7-Z's password dialog answers
        a.append(f"-p{o.password}")
    if items or list_file:
        a.append("-spd")  # names are literal, no wildcards
    a += ["--", archive]
    a += [f"@{list_file}"] if list_file else [native(i) for i in (items or [])]
    return a


def test_args(exe: str, archive: str, password: str = "") -> list[str]:
    return [exe, "t", *BASE_SWITCHES, *([f"-p{password}"] if password else []), "--", archive]


def delete_args(exe: str, archive: str, items: list[str], password: str = "") -> list[str]:
    a = [exe, "d", *BASE_SWITCHES, "-spd"]
    if password:
        a.append(f"-p{password}")
    return a + ["--", archive, *[native(i) for i in items]]


def rename_args(exe: str, archive: str, old: str, new: str, password: str = "") -> list[str]:
    a = [exe, "rn", *BASE_SWITCHES, "-spd"]
    if password:
        a.append(f"-p{password}")
    return a + ["--", archive, native(old), native(new)]


def hash_args(exe: str, files: list[str], method: str = "*") -> list[str]:
    return [exe, "h", "-sccUTF-8", "-bsp1", "-bso1", "-bse1", f"-scrc{method}", "--", *files]


def benchmark_args(exe: str) -> list[str]:
    return [exe, "b", "-sccUTF-8", "-bso1", "-bse1"]


def native(item_path: str) -> str:
    """Archive item path ('/'-separated) as 7z wants it on this OS."""
    return item_path.replace("/", "\\") if os.name == "nt" else item_path


def write_list_file(paths: list[str], dest: Path) -> str:
    dest.write_text("\n".join(paths) + "\n", encoding="utf-8")
    return str(dest)


# --------------------------------------------------------------------------- progress
OVERWRITE_PROMPT = "(Y)es / (N)o / (A)lways / (S)kip all / A(u)to rename all / (Q)uit?"
PASSWORD_PROMPT_RE = re.compile(r"Enter password[^:\n]*:")
PROGRESS_RE = re.compile(r"^\s*(\d{1,3})%(?:\s+(\d+))?(?:\s+([-+=UTRD.])\s+(.*\S))?\s*$")
FILE_RE = re.compile(r"^([-+=UTRD.])\s+(.+\S)\s*$")
TOTAL_RE = re.compile(r"(\d+) bytes")


@dataclass
class Event:
    kind: str          # percent | file | overwrite | password | error | warning | line | total
    value: object = None
    text: str = ""


class ProgressParser:
    """Turns 7z's stdout (progress redrawn with backspaces, prompts, errors) into events.

    Feed raw text chunks as they arrive; events come out in order. Prompts are recognised as
    soon as their question text arrives (7z waits on stdin without printing a newline).
    """

    def __init__(self):
        self.buf = ""
        self.pending: list[str] = []   # lines of an overwrite question being collected
        self.in_question = False
        self.errors: list[str] = []
        self.total: int | None = None

    def feed(self, chunk: str) -> list[Event]:
        # Windows 7z ends lines with \r\n and also redraws progress with a bare \r: both separate tokens.
        self.buf += chunk.replace("\r\n", "\n")
        events: list[Event] = []
        while True:
            # Prompts: complete when their question text is in the buffer, even without a newline.
            if OVERWRITE_PROMPT in self.buf:
                head, _, rest = self.buf.partition(OVERWRITE_PROMPT)
                for tok in self._tokens(head):
                    self._handle(tok, events)
                q = self._question()
                self.buf = rest.lstrip(" ")
                events.append(Event("overwrite", q, "\n".join(self.pending)))
                self.pending, self.in_question = [], False
                continue
            m = PASSWORD_PROMPT_RE.search(self.buf)
            if m:
                for tok in self._tokens(self.buf[:m.start()]):
                    self._handle(tok, events)
                self.buf = self.buf[m.end():]
                events.append(Event("password"))
                continue
            # Otherwise handle what's complete: tokens end at \n or at a backspace run.
            cut = max(self.buf.rfind("\n"), self.buf.rfind("\b"), self.buf.rfind("\r"))
            if cut < 0:
                break
            done, self.buf = self.buf[:cut + 1], self.buf[cut + 1:]
            for tok in self._tokens(done):
                self._handle(tok, events)
            break
        return events

    def finish(self) -> list[Event]:
        events: list[Event] = []
        for tok in self._tokens(self.buf + "\n"):
            self._handle(tok, events)
        self.buf = ""
        return events

    @staticmethod
    def _tokens(text: str) -> list[str]:
        out = []
        for part in re.split(r"[\b\r\n]+", text):
            if part.strip():
                out.append(part.rstrip())
        return out

    def _question(self) -> dict:
        """Parse the collected 'Would you like to replace' block: existing and incoming file."""
        q = {"existing": {}, "incoming": {}}
        target = None
        for ln in self.pending:
            s = ln.strip()
            if s.startswith("Would you like to replace"):
                target = "existing"
            elif s.startswith("with the file from archive"):
                target = "incoming"
            elif target and ":" in s:
                k, _, v = s.partition(":")
                q[target][k.strip().lower()] = v.strip()
        return q

    def _handle(self, tok: str, events: list[Event]) -> None:
        s = tok.strip()
        if s.startswith("Would you like to replace"):
            self.in_question = True
        if self.in_question:
            self.pending.append(s)
            return
        m = PROGRESS_RE.match(tok)
        if m:
            events.append(Event("percent", int(m.group(1))))
            if m.group(4):
                events.append(Event("file", m.group(4), m.group(3)))
            return
        m = FILE_RE.match(s)
        if m and not s.startswith("--"):
            events.append(Event("file", m.group(2), m.group(1)))
            return
        if s.startswith("ERROR") or s.startswith("Open ERROR"):
            msg = re.sub(r"^(Open )?ERROR:\s*", "", s)
            self.errors.append(msg)
            events.append(Event("error", msg))
            return
        if s.startswith("WARNING"):
            events.append(Event("warning", s))
            return
        if s.startswith("Add new data to archive:") or s.startswith("Size:"):
            t = TOTAL_RE.search(s) or re.search(r"(\d+)\s*$", s)
            if t:
                self.total = int(t.group(1))
                events.append(Event("total", self.total))
        events.append(Event("line", s, s))


# Answers to the overwrite question, keyed as PR7-Z's dialog returns them.
OVERWRITE_ANSWERS = {"yes": "y", "no": "n", "always": "a", "skip_all": "s", "rename_all": "u", "quit": "q"}

EXIT_MEANING = {0: "Everything is Ok", 1: "Warning (non-fatal errors)", 2: "Fatal error",
                7: "Command line error", 8: "Not enough memory", 255: "Stopped"}
