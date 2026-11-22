"""7-Zip File Manager's actions, built as Job steps."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from . import engine
from .engine import AddOptions, ExtractOptions
from .jobs import Job, Step


def _size_text(n: int) -> str:
    return f"{n} bytes"


# --------------------------------------------------------------------------- extract
def extract_steps(exe: str, archive: str, out_dir: str, opts: ExtractOptions, items: list[str] | None = None,
                  base: str = "", label: str | None = None) -> list[Step]:
    """Extract `items` (archive paths) or everything. With `base` (the archive folder being viewed),
    paths are kept relative to it, as 7-Zip FM does: extracting 'Drums/kick.wav' while inside
    'Drums' gives out_dir/kick.wav."""
    label = label or f"Extracting {Path(archive).name}"
    base = base.strip("/")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    if not base or opts.path_mode != "full":
        return [Step(label, engine.extract_args(exe, archive, out_dir, opts, items))]

    stage = Path(out_dir) / f".pr7z-{uuid.uuid4().hex[:8]}"
    inner = ExtractOptions(path_mode="full", overwrite="overwrite", password=opts.password,
                           keep_broken=opts.keep_broken)
    sel = items or [base]

    def move_up(job: Job):
        try:
            src_root = stage / base
            if src_root.exists():
                _merge(src_root, Path(out_dir), opts.overwrite, job)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    return [Step(label, engine.extract_args(exe, archive, str(stage), inner, sel), weight=0.95),
            Step(label, func=move_up, weight=0.05)]


def _merge(src: Path, dst: Path, mode: str, job: Job | None, state: dict | None = None) -> None:
    """Move src's contents into dst, settling name clashes like 7-Zip (ask / overwrite / skip / rename)."""
    state = state if state is not None else {"mode": mode}
    for entry in sorted(src.iterdir()):
        target = dst / entry.name
        if entry.is_dir() and not entry.is_symlink():
            if target.is_dir():
                _merge(entry, target, mode, job, state)
                continue
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(entry), str(target))
                continue
        if target.exists():
            m = state["mode"]
            if m == "ask" and job is not None:
                st_old, st_new = target.stat(), entry.stat()
                q = {"existing": {"path": str(target), "size": _size_text(st_old.st_size),
                                  "modified": datetime.fromtimestamp(st_old.st_mtime).strftime("%Y-%m-%d %H:%M:%S")},
                     "incoming": {"path": entry.name, "size": _size_text(st_new.st_size),
                                  "modified": datetime.fromtimestamp(st_new.st_mtime).strftime("%Y-%m-%d %H:%M:%S")}}
                ans = job.ask_overwrite(q)
                if ans == "quit":
                    raise RuntimeError("Stopped by the user.")
                m = {"yes": "overwrite_once", "always": "overwrite", "no": "skip_once", "skip_all": "skip",
                     "rename_all": "rename"}.get(ans, "skip_once")
                if m in ("overwrite", "skip", "rename"):
                    state["mode"] = m
            if m in ("skip", "skip_once"):
                continue
            if m in ("rename", "ask"):
                target = _free_name(target)
            elif m == "rename_existing":
                target.rename(_free_name(target))
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(entry), str(target))


def _free_name(p: Path) -> Path:
    """7-Zip's auto-rename: name_1.ext, name_2.ext ..."""
    i = 1
    while True:
        c = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not c.exists():
            return c
        i += 1


def default_extract_dir(archive: str) -> str:
    """'Extract to "name\\"': the archive's folder plus its name without the archive extensions."""
    p = Path(archive)
    name = p.name
    for _ in range(2):  # x.tar.gz -> x ; x.7z.001 -> x
        stem, dot, ext = name.rpartition(".")
        if dot and stem and (ext.lower() in engine.ARCHIVE_EXTS or ext.isdigit() or ext.lower() == "tar"):
            name = stem
    return str(p.parent / name)


# --------------------------------------------------------------------------- add
def add_steps(exe: str, archive: str, files: list[str], opts: AddOptions, base_in_archive: str = "",
              label: str | None = None) -> list[Step]:
    """Add files/folders to `archive`. Paths are stored relative to each file's own folder (7-Zip's
    'Relative pathnames'); with base_in_archive they land inside that archive folder."""
    label = label or f"Compressing to {Path(archive).name}"
    files = [str(Path(f)) for f in files]
    base = base_in_archive.strip("/")
    if opts.path_mode != "relative" and not base:
        return [Step(label, engine.add_args(exe, archive, files, opts))]
    if not base:
        groups: dict[str, list[str]] = {}
        for f in files:
            groups.setdefault(str(Path(f).parent), []).append(Path(f).name)
        return [Step(label, engine.add_args(exe, archive, names, opts), cwd=parent, weight=len(names))
                for parent, names in groups.items()]

    stage = Path(tempfile.gettempdir()) / f"pr7z-add-{uuid.uuid4().hex[:8]}"

    def build(job: Job):
        dest = stage.joinpath(*base.split("/"))
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            _link_tree(Path(f), dest / Path(f).name)

    def cleanup(_code):
        shutil.rmtree(stage, ignore_errors=True)

    top = base.split("/")[0]
    return [Step(label, func=build, weight=0.02),
            Step(label, engine.add_args(exe, archive, [top], opts), cwd=str(stage), weight=0.98, on_done=cleanup)]


def _link_tree(src: Path, dst: Path) -> None:
    """Mirror src at dst with hard links (no copying, no extra disk use); copy if linking fails."""
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for e in src.iterdir():
            _link_tree(e, dst / e.name)
        shutil.copystat(src, dst, follow_symlinks=False)
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def new_folder_steps(exe: str, archive: str, base: str, name: str, password: str = "") -> list[Step]:
    stage = Path(tempfile.gettempdir()) / f"pr7z-dir-{uuid.uuid4().hex[:8]}"
    rel = "/".join(p for p in (base.strip("/"), name) if p)

    def build(job: Job):
        stage.joinpath(*rel.split("/")).mkdir(parents=True, exist_ok=True)

    opts = AddOptions(format=_format_of(exe, archive), password=password)
    return [Step("Creating folder", func=build, weight=0.1),
            Step("Creating folder", engine.add_args(exe, archive, [rel.split("/")[0]], opts), cwd=str(stage),
                 on_done=lambda _c: shutil.rmtree(stage, ignore_errors=True))]


def _format_of(exe: str, archive: str) -> str:
    try:
        t = engine.list_archive(archive, exe=exe).type.lower()
    except engine.ArchiveError:
        t = ""
    return t if t in engine.CREATE_FORMATS else "7z"


# --------------------------------------------------------------------------- the rest
def test_steps(exe: str, archives: list[str], password: str = "") -> list[Step]:
    return [Step(f"Testing {Path(a).name}", engine.test_args(exe, a, password)) for a in archives]


def delete_steps(exe: str, archive: str, items: list[str], password: str = "") -> list[Step]:
    return [Step(f"Deleting from {Path(archive).name}", engine.delete_args(exe, archive, items, password))]


def rename_steps(exe: str, archive: str, old: str, new: str, password: str = "") -> list[Step]:
    return [Step(f"Renaming in {Path(archive).name}", engine.rename_args(exe, archive, old, new, password))]


def update_from_temp_steps(exe: str, archive: str, temp_root: str, rel_path: str, password: str = "") -> list[Step]:
    """Put an edited file (extracted to temp_root/rel_path) back into the archive."""
    opts = AddOptions(format=_format_of(exe, archive), password=password, update_mode="add")
    return [Step(f"Updating {Path(archive).name}", engine.add_args(exe, archive, [rel_path], opts), cwd=temp_root)]


def split_file(path: str, part_size: int, out_dir: str | None = None) -> list[str]:
    """7-Zip's Split file: name.ext.001, .002, ... (the same layout 7-Zip reads back as an archive)."""
    src = Path(path)
    out = Path(out_dir or src.parent)
    parts, n = [], 0
    with src.open("rb") as f:
        while True:
            chunk = f.read(part_size)
            if not chunk and n:
                break
            n += 1
            p = out / f"{src.name}.{n:03d}"
            p.write_bytes(chunk)
            parts.append(str(p))
            if len(chunk) < part_size:
                break
    return parts


def combine_files(first_part: str, out_path: str | None = None) -> str:
    """7-Zip's Combine files: joins name.001, name.002, ... into name."""
    first = Path(first_part)
    stem, _, num = first.name.rpartition(".")
    if not num.isdigit():
        raise ValueError("Pick the first part (name.001).")
    out = Path(out_path or first.with_name(stem))
    width = len(num)
    i = int(num)
    with out.open("wb") as w:
        while True:
            p = first.with_name(f"{stem}.{i:0{width}d}")
            if not p.exists():
                break
            with p.open("rb") as r:
                shutil.copyfileobj(r, w, 1 << 20)
            i += 1
    return str(out)


def fs_copy_steps(sources: list[str], dest: str, move: bool = False) -> list[Step]:
    """7-Zip FM's Copy / Move on disk. Clashes go to the same Confirm File Replace question."""
    verb = "Moving" if move else "Copying"

    def work(job: Job):
        state = {"mode": "ask"}
        total = len(sources)
        for n, src in enumerate(sources, 1):
            s = Path(src)
            job.current_file.emit(s.name)
            target = Path(dest) / s.name
            if s.resolve() == target.resolve():
                continue
            if target.exists():
                m = state["mode"]
                if m == "ask":
                    q = {"existing": {"path": str(target)}, "incoming": {"path": str(s)}}
                    ans = job.ask_overwrite(q)
                    if ans == "quit":
                        raise RuntimeError("Stopped by the user.")
                    m = {"yes": "overwrite_once", "always": "overwrite", "no": "skip_once", "skip_all": "skip",
                         "rename_all": "rename"}.get(ans, "skip_once")
                    if m in ("overwrite", "skip", "rename"):
                        state["mode"] = m
                if m in ("skip", "skip_once"):
                    continue
                if m == "rename":
                    target = _free_name(target)
                elif target.is_dir() and not s.is_dir():
                    shutil.rmtree(target)
            Path(dest).mkdir(parents=True, exist_ok=True)
            if move:
                if s.is_dir() and target.is_dir():
                    _merge(s, target, "overwrite", None)
                    shutil.rmtree(s, ignore_errors=True)
                else:
                    shutil.move(str(s), str(target))
            elif s.is_dir():
                shutil.copytree(s, target, dirs_exist_ok=True)
            else:
                shutil.copy2(s, target)
            job.files_done = n
            job.progress.emit(100.0 * n / total)

    return [Step(f"{verb} {len(sources)} item(s)", func=work)]
