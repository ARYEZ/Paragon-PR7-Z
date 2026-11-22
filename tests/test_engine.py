"""The engine against the real 7-Zip: listing, command lines, progress and prompt parsing."""

import subprocess
from pathlib import Path

import pytest

from pr7z import engine
from pr7z.engine import AddOptions, ExtractOptions, ProgressParser


def run(args, cwd=None, stdin=b""):
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True)


def make(exe, tree, archive, **opts):
    o = AddOptions(**opts)
    r = run(engine.add_args(exe, str(archive), [tree.name], o), cwd=tree.parent)
    assert r.returncode == 0, r.stdout.decode()
    return archive


# ---------------------------------------------------------------- listing
def test_list_zip_items_and_props(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "t.zip", format="zip")
    info = engine.list_archive(str(arc), exe=exe)
    assert info.type == "zip"
    paths = {i.path: i for i in info.items}
    assert {"src", "src/a.txt", "src/sub", "src/sub/big.bin", "src/sub/ünï cødé.txt"} <= set(paths)
    assert paths["src/sub"].is_dir and not paths["src/a.txt"].is_dir
    assert paths["src/a.txt"].size == 6
    assert paths["src/sub/big.bin"].size == 300_000
    assert paths["src/a.txt"].crc and paths["src/a.txt"].modified is not None


def test_list_7z_has_archive_props(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "t.7z", level=9)
    info = engine.list_archive(str(arc), exe=exe)
    assert info.type == "7z"
    assert "LZMA2" in info.props["Method"] and info.props.get("Solid") == "+"


def test_encrypted_names_need_password(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "e.7z", password="hunter2", encrypt_names=True)
    with pytest.raises(engine.ArchiveError) as e:
        engine.list_archive(str(arc), exe=exe)
    assert e.value.kind == "password"
    with pytest.raises(engine.ArchiveError) as e:
        engine.list_archive(str(arc), password="nope", exe=exe)
    assert e.value.kind == "password"
    info = engine.list_archive(str(arc), password="hunter2", exe=exe)
    assert info.encrypted and any(i.path == "src/a.txt" for i in info.items)


def test_encrypted_data_visible_names(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "e2.zip", format="zip", password="pw", encryption="AES-256")
    info = engine.list_archive(str(arc), exe=exe)  # names are readable without the password
    f = next(i for i in info.items if i.path == "src/a.txt")
    assert f.encrypted and "AES" in f.method


def test_not_an_archive(exe, tmp_path):
    p = tmp_path / "plain.txt"
    p.write_text("not an archive")
    with pytest.raises(engine.ArchiveError) as e:
        engine.list_archive(str(p), exe=exe)
    assert e.value.kind == "open"
    assert not engine.is_archive(str(p), exe=exe)


# ---------------------------------------------------------------- operations
def test_extract_selected_items(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "t.7z")
    out = tmp_path / "out"
    r = run(engine.extract_args(exe, str(arc), str(out), ExtractOptions(overwrite="overwrite"),
                                items=["src/sub/ünï cødé.txt"]))
    assert r.returncode == 0, r.stdout.decode()
    assert (out / "src" / "sub" / "ünï cødé.txt").read_text(encoding="utf-8") == "x\n"
    assert not (out / "src" / "a.txt").exists()


def test_extract_no_paths(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "t.7z")
    out = tmp_path / "flat"
    r = run(engine.extract_args(exe, str(arc), str(out), ExtractOptions(path_mode="none", overwrite="overwrite")))
    assert r.returncode == 0
    assert (out / "big.bin").stat().st_size == 300_000 and (out / "a.txt").exists()


def test_round_trip_every_create_format(exe, tree, tmp_path):
    for fmt in ("7z", "zip", "tar", "wim"):
        arc = make(exe, tree, tmp_path / f"r.{engine.FORMAT_EXT[fmt]}", format=fmt)
        out = tmp_path / f"o_{fmt}"
        r = run(engine.extract_args(exe, str(arc), str(out), ExtractOptions(overwrite="overwrite")))
        assert r.returncode == 0, (fmt, r.stdout.decode())
        assert (out / "src" / "sub" / "big.bin").read_bytes() == (tree / "sub" / "big.bin").read_bytes(), fmt
    for fmt in ("gzip", "bzip2", "xz"):  # one file only
        arc = tmp_path / f"one.{engine.FORMAT_EXT[fmt]}"
        r = run(engine.add_args(exe, str(arc), ["a.txt"], AddOptions(format=fmt)), cwd=tree)
        assert r.returncode == 0, (fmt, r.stdout.decode())
        info = engine.list_archive(str(arc), exe=exe)
        assert [i.path for i in info.items] == ["one" if fmt != "gzip" else "a.txt"] or \
            [i.path for i in info.items] == ["a.txt"], (fmt, info.items)
        if fmt != "bzip2":  # bzip2 doesn't store the original size
            assert info.items[0].size == 6, fmt


def test_test_ok_and_wrong_password(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "p.7z", password="abc")
    good = run(engine.test_args(exe, str(arc), "abc"))
    assert good.returncode == 0 and b"Everything is Ok" in good.stdout
    bad = run(engine.test_args(exe, str(arc), "zzz"))
    assert bad.returncode == 2
    p = ProgressParser()
    p.feed(bad.stdout.decode())
    p.finish()
    assert p.errors and "Wrong password" in p.errors[0]


def test_delete_and_rename(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "t.7z")
    assert run(engine.delete_args(exe, str(arc), ["src/a.txt"])).returncode == 0
    assert run(engine.rename_args(exe, str(arc), "src/sub", "src/renamed")).returncode == 0
    paths = {i.path for i in engine.list_archive(str(arc), exe=exe).items}
    assert "src/a.txt" not in paths
    assert "src/renamed/big.bin" in paths and "src/sub/big.bin" not in paths


def test_update_modes(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "u.7z")
    (tree / "new.txt").write_text("new")
    # freshen: changed files only, never adds new ones
    r = run(engine.add_args(exe, str(arc), [tree.name], AddOptions(update_mode="freshen")), cwd=tree.parent)
    assert r.returncode == 0
    assert "src/new.txt" not in {i.path for i in engine.list_archive(str(arc), exe=exe).items}
    # sync: removes what's gone from disk
    (tree / "a.txt").unlink()
    r = run(engine.add_args(exe, str(arc), [tree.name], AddOptions(update_mode="sync")), cwd=tree.parent)
    assert r.returncode == 0
    paths = {i.path for i in engine.list_archive(str(arc), exe=exe).items}
    assert "src/a.txt" not in paths and "src/new.txt" in paths


def test_volumes(exe, tree, tmp_path):
    make(exe, tree, tmp_path / "v.7z", level=0, volumes="100k")
    parts = sorted(p.name for p in tmp_path.glob("v.7z.*"))
    assert parts[:3] == ["v.7z.001", "v.7z.002", "v.7z.003"]
    info = engine.list_archive(str(tmp_path / "v.7z.001"), exe=exe)
    assert any(i.path == "src/sub/big.bin" for i in info.items)


def test_hash(exe, tree):
    r = run(engine.hash_args(exe, [str(tree / "a.txt")], "SHA256"))
    assert r.returncode == 0
    import hashlib
    assert hashlib.sha256(b"hello\n").hexdigest().upper() in r.stdout.decode().upper()


# ---------------------------------------------------------------- command-line mapping
def test_add_switches():
    a = engine.add_args("7z", "x.7z", ["f"], AddOptions(level=9, method="LZMA2", dictionary="64m", word_size="64",
                                                       solid="off", threads="4", volumes="10m",
                                                       parameters="qs=on -mtc=on", update_mode="update",
                                                       path_mode="full", shared=True, delete_after=True,
                                                       password="p w", encrypt_names=True))
    for s in ("-t7z", "-mx=9", "-m0=LZMA2", "-md=64m", "-mfb=64", "-ms=off", "-mmt=4", "-v10m", "-mqs=on",
              "-mtc=on", "-up1q1r2x1y2z1w2", "-spf2", "-ssw", "-sdel", "-pp w", "-mhe=on"):
        assert s in a, s
    assert a[-3:] == ["--", "x.7z", "f"]
    z = engine.add_args("7z", "x.zip", ["f"], AddOptions(format="zip", method="Deflate", password="k"))
    assert "-mm=Deflate" in z and "-mem=AES256" in z and "-mhe=on" not in z


def test_extract_switches():
    a = engine.extract_args("7z", "x.7z", "out", ExtractOptions(path_mode="none", overwrite="rename",
                                                               eliminate_root=True), items=["a/b"])
    assert a[1] == "e" and "-oout" in a and "-aou" in a and "-spe" in a and "-spd" in a
    assert a[-1] in ("a/b", "a\\b")


# ---------------------------------------------------------------- progress parsing (real 7z output)
def test_progress_events(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "t.7z")
    r = run(engine.extract_args(exe, str(arc), str(tmp_path / "o"), ExtractOptions(overwrite="overwrite")))
    p = ProgressParser()
    events = p.feed(r.stdout.decode()) + p.finish()
    pct = [e.value for e in events if e.kind == "percent"]
    files = [e.value for e in events if e.kind == "file"]
    assert pct and max(pct) == 100
    assert any(f.endswith("big.bin") for f in files)
    assert not p.errors


def test_overwrite_prompt_parsed_and_answered(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "t.7z")
    out = tmp_path / "o"
    run(engine.extract_args(exe, str(arc), str(out), ExtractOptions(overwrite="overwrite")))
    # Second extraction asks; answer "skip all" through stdin as the app does.
    r = run(engine.extract_args(exe, str(arc), str(out), ExtractOptions()), stdin=b"s\n")
    assert r.returncode == 0
    p = ProgressParser()
    events = p.feed(r.stdout.decode()) + p.finish()
    q = [e for e in events if e.kind == "overwrite"]
    assert len(q) == 1
    assert q[0].value["existing"]["path"].replace("\\", "/").endswith("src/a.txt")
    assert q[0].value["incoming"]["size"].startswith("6 bytes")


def test_prompt_split_across_chunks():
    """Prompts arrive in pieces from a pipe; the parser waits for the whole question."""
    text = ("  0%\b\b\b\b    \b\b\b\b\nWould you like to replace the existing file:\n  Path:     out/a.txt\n"
            "  Size:     6 bytes (1 KiB)\nwith the file from archive:\n  Path:     a.txt\n  Size:     6 bytes\n"
            "? (Y)es / (N)o / (A)lways / (S)kip all / A(u)to rename all / (Q)uit? ")
    p = ProgressParser()
    events = []
    for i in range(0, len(text), 7):
        events += p.feed(text[i:i + 7])
    kinds = [e.kind for e in events]
    assert kinds.count("overwrite") == 1
    q = next(e for e in events if e.kind == "overwrite").value
    assert q["existing"]["path"] == "out/a.txt" and q["incoming"]["path"] == "a.txt"


def test_password_prompt_answered(exe, tree, tmp_path):
    arc = make(exe, tree, tmp_path / "e.7z", password="hunter2", encrypt_names=True)
    args = [a for a in engine.extract_args(exe, str(arc), str(tmp_path / "o"), ExtractOptions())
            if not a.startswith("-p")]  # no -p at all: 7z asks
    r = run(args, stdin=b"hunter2\n")
    assert r.returncode == 0
    p = ProgressParser()
    events = p.feed(r.stdout.decode()) + p.finish()
    assert [e.kind for e in events].count("password") == 1
    assert (tmp_path / "o" / "src" / "a.txt").exists()
