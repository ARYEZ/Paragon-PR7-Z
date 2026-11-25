"""Screenshots of the real app (offscreen): python tools/screenshots.py OUT_DIR [aurora]

Builds a sample folder and archive with the real engine, then captures the main window inside
the archive, the Extract dialog, Confirm File Replace and a running progress window.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_cfg = Path(tempfile.gettempdir()) / "pr7z_offscreen.json"
_cfg.write_text(json.dumps({"screens": [{"name": "s", "x": 0, "y": 0, "width": 2560, "height": 3200,
                                          "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))
os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={_cfg}")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QItemSelectionModel, QSettings, QTimer  # noqa: E402

_family = Path(tempfile.mkdtemp()) / "finish"  # the family's finish, kept out of the real one too
_family.write_text(sys.argv[2] if len(sys.argv) > 2 else "obsidian")
os.environ["PARAGON_FAMILY_FILE"] = str(_family)
QSettings.setDefaultFormat(QSettings.IniFormat)  # keep the screenshot run out of the real settings
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())

from pr7z import engine, operations  # noqa: E402
from pr7z.app import make_app  # noqa: E402
from pr7z.dialogs import ExtractDialog, OverwriteDialog, ProgressDialog  # noqa: E402
from pr7z.engine import AddOptions  # noqa: E402
from pr7z.jobs import Job  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = make_app([])
exe = engine.find_7z()

root = Path(tempfile.mkdtemp()) / "Music"
src = root / "ELSEWORLD"
for folder, files in {"Drums": ["kick_01.wav", "snare_02.wav", "toms.wav"], "Guitars": ["rhythm_L.wav", "rhythm_R.wav"],
                      "Vocals": ["lead.wav", "doubles.wav"]}.items():
    (src / folder).mkdir(parents=True)
    for i, f in enumerate(files):
        (src / folder / f).write_bytes(os.urandom(200_000 + 90_000 * i))
(src / "ELSEWORLD_master_24bit.wav").write_bytes(os.urandom(880_000))
(src / "lyrics.txt").write_text("Through the portal, into the ruins...\n" * 40)
(src / "notes_for_mix.md").write_text("- tighten the low end\n" * 30)
arc = root / "ELSEWORLD_Stems.7z"
Job("", operations.add_steps(exe, str(arc), [str(src)], AddOptions(level=7, password="elseworld", encrypt_names=False))
    ).run_blocking()

from pr7z.main_window import MainWindow  # noqa: E402
w = MainWindow(str(root))
w.resize(1280, 760)
w.show()
w.open_archive(str(arc))
w._select_name("ELSEWORLD")
w.open_selected()
w._select_name("ELSEWORLD_master_24bit.wav")
w.view.selectionModel().select(w.view.currentIndex(), QItemSelectionModel.Select | QItemSelectionModel.Rows)
app.processEvents()
w.grab().save(str(out / "main_window.png"))

d = ExtractDialog(str(arc), operations.default_extract_dir(str(arc)), encrypted=True, password="elseworld")
d.show()
app.processEvents()
d.grab().save(str(out / "extract_dialog.png"))
d.close()

o = OverwriteDialog({"existing": {"path": str(root / "ELSEWORLD" / "lyrics.txt"), "size": "1 520 bytes",
                                  "modified": "2026-11-19 22:41:07"},
                     "incoming": {"path": "ELSEWORLD\\lyrics.txt", "size": "1 520 bytes",
                                  "modified": "2026-11-22 07:30:12"}})
o.show()
app.processEvents()
o.grab().save(str(out / "confirm_replace.png"))
o.close()

big = root / "big.bin"
big.write_bytes(os.urandom(120_000_000))
job = Job("Compressing ELSEWORLD_Stems.7z", operations.add_steps(exe, str(root / "big.7z"), [str(big)],
                                                                   AddOptions(level=9)))
p = ProgressDialog(job, total_bytes=big.stat().st_size, keep_open=True)
p.show()
job.start()
QTimer.singleShot(2500, lambda: (p.grab().save(str(out / "progress.png")), job.cancel()))
job.finished.connect(lambda _: QTimer.singleShot(200, app.quit))
app.exec()
print("ok", out)
