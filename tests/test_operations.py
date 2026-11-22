"""Jobs and operations end to end: QProcess + real 7-Zip, prompts answered by callbacks."""

import os
from pathlib import Path

from pr7z import engine, operations
from pr7z.engine import AddOptions, ExtractOptions
from pr7z.jobs import Job, Step


def run_job(steps, qapp, overwrite=None, password=None):
    job = Job("test", steps)
    asked = {"overwrite": [], "password": 0}

    def ow(q):
        asked["overwrite"].append(q)
        return overwrite or "quit"

    def pw():
        asked["password"] += 1
        return password

    job.ask_overwrite, job.ask_password = ow, pw
    pct = []
    job.progress.connect(pct.append)
    res = job.run_blocking()
    return res, asked, pct


def items(exe, arc, password=None):
    return {i.path for i in engine.list_archive(str(arc), password=password, exe=exe).items}


def test_add_and_extract_job(exe, tree, tmp_path, qapp):
    arc = str(tmp_path / "a.7z")
    res, _, pct = run_job(operations.add_steps(exe, arc, [str(tree)], AddOptions()), qapp)
    assert res.ok, res.errors
    assert pct and pct[-1] == 100
    assert "src/sub/big.bin" in items(exe, arc)
    out = tmp_path / "out"
    res, _, _ = run_job(operations.extract_steps(exe, arc, str(out), ExtractOptions()), qapp)
    assert res.ok and (out / "src" / "sub" / "big.bin").stat().st_size == 300_000


def test_overwrite_prompt_through_job(exe, tree, tmp_path, qapp):
    arc = str(tmp_path / "a.zip")
    run_job(operations.add_steps(exe, arc, [str(tree)], AddOptions(format="zip")), qapp)
    out = tmp_path / "out"
    run_job(operations.extract_steps(exe, arc, str(out), ExtractOptions()), qapp)
    (out / "src" / "a.txt").write_text("mine")
    res, asked, _ = run_job(operations.extract_steps(exe, arc, str(out), ExtractOptions()), qapp, overwrite="skip_all")
    assert res.ok, res.errors
    assert len(asked["overwrite"]) == 1
    assert (out / "src" / "a.txt").read_text() == "mine"           # skipped
    res, asked, _ = run_job(operations.extract_steps(exe, arc, str(out), ExtractOptions()), qapp, overwrite="always")
    assert (out / "src" / "a.txt").read_text() == "hello\n"        # replaced


def test_password_prompt_through_job(exe, tree, tmp_path, qapp):
    arc = str(tmp_path / "e.7z")
    run_job(operations.add_steps(exe, arc, [str(tree)], AddOptions(password="pw1", encrypt_names=True)), qapp)
    out = tmp_path / "out"
    # No password given up front: 7z asks, the callback answers (as with Explorer's "Extract Here").
    steps = operations.extract_steps(exe, arc, str(out), ExtractOptions())
    assert not any(a.startswith("-p") for a in steps[0].args)
    res, asked, _ = run_job(steps, qapp, password="pw1")
    assert res.ok, res.errors
    assert asked["password"] == 1 and (out / "src" / "a.txt").exists()


def test_test_asks_for_password(exe, tree, tmp_path, qapp):
    arc = str(tmp_path / "e.7z")
    run_job(operations.add_steps(exe, arc, [str(tree)], AddOptions(password="pw2")), qapp)
    res, asked, _ = run_job(operations.test_steps(exe, [arc]), qapp, password="pw2")
    assert res.ok and asked["password"] == 1
    res, asked, _ = run_job(operations.test_steps(exe, [arc]), qapp, password=None)  # cancelled at the prompt
    assert not res.ok and res.cancelled


def test_wrong_password_reports_error(exe, tree, tmp_path, qapp):
    arc = str(tmp_path / "e.7z")
    run_job(operations.add_steps(exe, arc, [str(tree)], AddOptions(password="right")), qapp)
    res, _, _ = run_job(operations.extract_steps(exe, arc, str(tmp_path / "o"), ExtractOptions(password="wrong",
                                                                                               overwrite="overwrite")),
                        qapp)
    assert not res.ok and any("Wrong password" in e for e in res.errors)


def test_extract_from_subfolder_is_relative(exe, tree, tmp_path, qapp):
    """Inside 'src/sub', extracting big.bin gives out/big.bin (7-Zip FM behaviour)."""
    arc = str(tmp_path / "a.7z")
    run_job(operations.add_steps(exe, arc, [str(tree)], AddOptions()), qapp)
    out = tmp_path / "out"
    res, _, _ = run_job(operations.extract_steps(exe, arc, str(out), ExtractOptions(), items=["src/sub/big.bin"],
                                                 base="src/sub"), qapp)
    assert res.ok, res.errors
    assert sorted(os.listdir(out)) == ["big.bin"]          # no staging folder left behind
    # again: the clash is asked about during the move, and auto-rename gives big_1.bin
    res, asked, _ = run_job(operations.extract_steps(exe, arc, str(out), ExtractOptions(), items=["src/sub/big.bin"],
                                                     base="src/sub"), qapp, overwrite="rename_all")
    assert res.ok and len(asked["overwrite"]) == 1
    assert sorted(os.listdir(out)) == ["big.bin", "big_1.bin"]


def test_add_into_archive_subfolder(exe, tree, tmp_path, qapp):
    arc = str(tmp_path / "a.7z")
    run_job(operations.add_steps(exe, arc, [str(tree)], AddOptions()), qapp)
    extra = tmp_path / "extra.txt"
    extra.write_text("e")
    res, _, _ = run_job(operations.add_steps(exe, arc, [str(extra)], AddOptions(), base_in_archive="src/sub"), qapp)
    assert res.ok, res.errors
    got = items(exe, arc)
    assert "src/sub/extra.txt" in got and "src/sub/big.bin" in got and "extra.txt" not in got


def test_new_folder_in_archive(exe, tree, tmp_path, qapp):
    arc = str(tmp_path / "a.7z")
    run_job(operations.add_steps(exe, arc, [str(tree)], AddOptions()), qapp)
    res, _, _ = run_job(operations.new_folder_steps(exe, arc, "src", "New Folder"), qapp)
    assert res.ok, res.errors
    assert "src/New Folder" in items(exe, arc)


def test_add_from_two_folders(exe, tmp_path, qapp):
    (tmp_path / "x").mkdir()
    (tmp_path / "y" / "deep").mkdir(parents=True)
    (tmp_path / "x" / "one.txt").write_text("1")
    (tmp_path / "y" / "deep" / "two.txt").write_text("2")
    arc = str(tmp_path / "m.zip")
    res, _, _ = run_job(operations.add_steps(exe, arc, [str(tmp_path / "x" / "one.txt"),
                                                        str(tmp_path / "y" / "deep")], AddOptions(format="zip")), qapp)
    assert res.ok
    assert {"one.txt", "deep/two.txt"} <= items(exe, arc)


def test_cancel(exe, tmp_path, qapp):
    big = tmp_path / "big.bin"
    big.write_bytes(os.urandom(40_000_000))
    job = Job("cancel", operations.add_steps(exe, str(tmp_path / "c.7z"), [str(big)], AddOptions(level=9)))
    from PySide6.QtCore import QTimer
    QTimer.singleShot(300, job.cancel)
    res = job.run_blocking()
    assert res.cancelled and not res.ok


def test_python_step_error_stops_job(qapp):
    def boom(job):
        raise RuntimeError("disk full")
    ran = []
    res = Job("x", [Step("a", func=boom), Step("b", func=lambda j: ran.append(1))]).run_blocking()
    assert res.errors == ["disk full"] and not ran


def test_default_extract_dir():
    assert operations.default_extract_dir(str(Path("/m/ELSEWORLD_Stems.7z"))) == str(Path("/m/ELSEWORLD_Stems"))
    assert operations.default_extract_dir(str(Path("/m/x.tar.gz"))) == str(Path("/m/x"))
    assert operations.default_extract_dir(str(Path("/m/x.7z.001"))) == str(Path("/m/x"))


def test_split_and_combine(tmp_path):
    f = tmp_path / "data.bin"
    payload = os.urandom(250_000)
    f.write_bytes(payload)
    parts = operations.split_file(str(f), 100_000)
    assert [Path(p).name for p in parts] == ["data.bin.001", "data.bin.002", "data.bin.003"]
    f.unlink()
    out = operations.combine_files(parts[0])
    assert Path(out).read_bytes() == payload
