"""PR7-Z's dialogs, matching 7-Zip's, in the Paragon look."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QProgressBar,
                               QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import __version__, engine
from .engine import ExtractOptions
from .jobs import Job, Result
from .widgets import Header


def field_label(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def fmt_size(n: int | None) -> str:
    """7-Zip's digit grouping: 88 210 452."""
    return "" if n is None else f"{n:,}".replace(",", " ")


def fmt_bytes(n: float | None) -> str:
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def fmt_time(sec: float | None) -> str:
    if sec is None:
        return ""
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


class ParagonDialog(QDialog):
    """Header + padded body + right-aligned buttons."""

    def __init__(self, title: str, subtitle: str, parent=None, width: int = 560):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.setSpacing(0)
        root.addWidget(Header(subtitle.upper()))
        body_widget = QWidget()
        self.body = QVBoxLayout(body_widget)
        self.body.setContentsMargins(20, 10, 20, 0)
        self.body.setSpacing(8)
        root.addWidget(body_widget, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setContentsMargins(20, 14, 20, 0)
        self.buttons.addStretch(1)
        root.addLayout(self.buttons)

    def add_button(self, text: str, slot=None, default: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setMinimumWidth(96)
        b.setDefault(default)
        b.setAutoDefault(default)
        if slot:
            b.clicked.connect(slot)
        self.buttons.addWidget(b)
        return b


# --------------------------------------------------------------------------- small prompts
def message(parent, title: str, text: str, subtitle: str = "", buttons=("OK",), default: int = 0,
            detail: str = "") -> int:
    """A themed message box. Returns the index of the button pressed (-1 if closed)."""
    d = ParagonDialog(title, subtitle or title, parent, 460)
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    d.body.addWidget(lab)
    if detail:
        t = QPlainTextEdit(detail)
        t.setReadOnly(True)
        t.setMaximumHeight(180)
        d.body.addWidget(t)
    chosen = {"i": -1}
    for i, b in enumerate(buttons):
        d.add_button(b, lambda _=False, i=i: (chosen.__setitem__("i", i), d.accept()), default=(i == default))
    d.exec()
    return chosen["i"]


def confirm(parent, title: str, text: str) -> bool:
    return message(parent, title, text, buttons=("Yes", "No"), default=0) == 0


def ask_text(parent, title: str, label: str, value: str = "", subtitle: str = "") -> str | None:
    d = ParagonDialog(title, subtitle or title, parent, 460)
    d.body.addWidget(field_label(label))
    e = QLineEdit(value)
    e.selectAll()
    d.body.addWidget(e)
    d.add_button("OK", d.accept, default=True)
    d.add_button("Cancel", d.reject)
    e.setFocus()
    return e.text() if d.exec() == QDialog.Accepted and e.text().strip() else None


class PasswordDialog(ParagonDialog):
    def __init__(self, parent=None, archive: str = ""):
        super().__init__("Enter password", "ENTER PASSWORD", parent, 440)
        if archive:
            note = QLabel(Path(archive).name)
            note.setProperty("role", "dim")
            self.body.addWidget(note)
        self.body.addWidget(field_label("Enter password"))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.body.addWidget(self.edit)
        show = QCheckBox("Show password")
        show.toggled.connect(lambda on: self.edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.body.addWidget(show)
        self.add_button("OK", self.accept, default=True)
        self.add_button("Cancel", self.reject)
        self.edit.setFocus()

    @staticmethod
    def get(parent=None, archive: str = "") -> str | None:
        d = PasswordDialog(parent, archive)
        return d.edit.text() if d.exec() == QDialog.Accepted else None


class OverwriteDialog(ParagonDialog):
    """7-Zip's 'Confirm File Replace'."""

    ANSWERS = [("Yes", "yes"), ("Yes to All", "always"), ("No", "no"), ("No to All", "skip_all"),
               ("Auto Rename", "rename_all"), ("Cancel", "quit")]

    def __init__(self, q: dict, parent=None):
        super().__init__("Confirm File Replace", "CONFIRM FILE REPLACE", parent, 640)
        self.answer = "quit"
        self.body.addWidget(QLabel("Destination folder already contains processed file."))
        for heading, key in (("Would you like to replace the existing file", "existing"),
                             ("with this one?", "incoming")):
            box = QGroupBox(heading.upper())
            g = QGridLayout(box)
            info = q.get(key, {})
            for r, k in enumerate(("path", "size", "modified")):
                g.addWidget(field_label(k), r, 0)
                v = QLabel(info.get(k, ""))
                v.setProperty("role", "value")
                v.setWordWrap(True)
                g.addWidget(v, r, 1)
            g.setColumnStretch(1, 1)
            self.body.addWidget(box)
        for text, key in self.ANSWERS:
            self.add_button(text, lambda _=False, k=key: self._pick(k), default=(key == "yes")).setMinimumWidth(80)

    def _pick(self, key):
        self.answer = key
        self.accept()

    @staticmethod
    def get(q: dict, parent=None) -> str:
        d = OverwriteDialog(q, parent)
        d.exec()
        return d.answer


# --------------------------------------------------------------------------- progress
class ProgressDialog(ParagonDialog):
    """7-Zip's progress window: times, sizes, speed, current file; Background / Pause / Cancel.

    Closes by itself when the job succeeds (like 7-Zip), except for tests and checks, whose
    result stays on screen. With errors it lists them."""

    def __init__(self, job: Job, parent=None, total_bytes: int | None = None, keep_open: bool = False,
                 on_finished=None):
        super().__init__(job.title, job.title.split(" ")[0].upper(), parent, 620)
        self.job, self.total = job, total_bytes
        self.keep_open, self.on_finished = keep_open, on_finished
        self.setModal(False)
        self.pct = 0.0
        stats = QGroupBox("PROGRESS")
        g = QGridLayout(stats)
        g.setHorizontalSpacing(18)
        self.vals = {}
        names = [("Elapsed time", 0, 0), ("Total size", 0, 2), ("Remaining time", 1, 0), ("Speed", 1, 2),
                 ("Files", 2, 0), ("Processed", 2, 2), ("Errors", 3, 0)]
        for name, r, c in names:
            g.addWidget(field_label(name), r, c)
            v = QLabel("")
            v.setProperty("role", "value")
            g.addWidget(v, r, c + 1)
            self.vals[name] = v
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        self.body.addWidget(stats)
        self.step = QLabel("")
        self.step.setProperty("role", "dim")
        self.body.addWidget(self.step)
        self.file = QLabel("")
        self.file.setMinimumWidth(500)
        self.file.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.body.addWidget(self.file)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.body.addWidget(self.bar)
        self.errors = QPlainTextEdit()
        self.errors.setReadOnly(True)
        self.errors.setMaximumHeight(160)
        self.errors.hide()
        self.body.addWidget(self.errors)
        self.bg = self.add_button("Background", self._background)
        self.bg.setCheckable(True)
        self.pause = self.add_button("Pause", self._pause)
        self.cancel_btn = self.add_button("Cancel", self._cancel, default=True)

        job.progress.connect(self._progress)
        job.current_file.connect(lambda f: self.file.setText(self.file.fontMetrics().elidedText(
            f, Qt.ElideMiddle, max(200, self.file.width()))))
        job.step_started.connect(self.step.setText)
        job.total_bytes.connect(self._set_total)
        job.error.connect(self._error)
        job.finished.connect(self._finished)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(250)
        self.result: Result | None = None
        self._tick()

    def _set_total(self, n: int):
        if not self.total:
            self.total = n

    def _progress(self, pct: float):
        self.pct = pct
        self.bar.setValue(int(pct * 10))
        self.setWindowTitle(f"{pct:.0f}% {self.job.title}")

    def _error(self, msg: str):
        self.errors.show()
        self.errors.appendPlainText(msg)

    def _tick(self):
        el = self.job.elapsed()
        v = self.vals
        v["Elapsed time"].setText(fmt_time(el))
        frac = self.pct / 100.0
        v["Remaining time"].setText(fmt_time(el / frac - el) if 0.01 < frac < 1 else "")
        v["Files"].setText(str(self.job.files_done))
        v["Errors"].setText(str(len(self.job.result.errors)))
        if self.total:
            done = self.total * frac
            v["Total size"].setText(fmt_bytes(self.total))
            v["Processed"].setText(fmt_bytes(done))
            v["Speed"].setText(f"{fmt_bytes(done / el)}/s" if el > 0.5 else "")

    def _background(self):
        self.job.set_background(self.bg.isChecked())

    def _pause(self):
        self.job.set_paused(not self.job.paused)
        self.pause.setText("Continue" if self.job.paused else "Pause")

    def _cancel(self):
        if self.result is not None:
            return self.accept()
        self.job.cancel()

    def _finished(self, res: Result):
        self.result = res
        self.timer.stop()
        self._tick()
        if res.ok:
            self.bar.setValue(1000)
        self.bg.hide()
        self.pause.hide()
        self.cancel_btn.setText("Close")
        if res.cancelled:
            self.step.setText("Stopped.")
        elif res.errors:
            self.step.setText(f"There {'is' if len(res.errors) == 1 else 'are'} {len(res.errors)} "
                              f"error{'s' if len(res.errors) != 1 else ''}.")
            self.step.setProperty("role", "error")
            self.step.style().polish(self.step)
        else:
            self.step.setText("Everything is Ok")
            self.step.setProperty("role", "ok")
            self.step.style().polish(self.step)
        if self.on_finished:
            self.on_finished(res)
        if res.ok and not self.keep_open:
            QTimer.singleShot(150, self.accept)

    def closeEvent(self, e):
        if self.result is None:
            self.job.cancel()
            e.ignore()
            return
        super().closeEvent(e)


def run_job(job: Job, parent=None, total_bytes: int | None = None, keep_open: bool = False,
            password_hint: str = "") -> Result:
    """Run a job with a progress window, prompts going to PR7-Z's dialogs. Blocks until it's closed."""
    dlg = ProgressDialog(job, parent, total_bytes, keep_open)
    job.ask_overwrite = lambda q: OverwriteDialog.get(q, dlg)
    job.ask_password = lambda: PasswordDialog.get(dlg, password_hint)
    job.start()
    dlg.exec()
    return job.result


# --------------------------------------------------------------------------- extract
class ExtractDialog(ParagonDialog):
    PATH_MODES = [("Full pathnames", "full"), ("No pathnames", "none"), ("Absolute pathnames", "absolute")]
    OVERWRITE = [("Ask before overwrite", "ask"), ("Overwrite without prompt", "overwrite"),
                 ("Skip existing files", "skip"), ("Auto rename", "rename"),
                 ("Auto rename existing files", "rename_existing")]

    def __init__(self, archive: str, dest: str, parent=None, encrypted: bool = False, password: str = "",
                 title: str = "Extract", history: list[str] | None = None):
        super().__init__(title, title.upper(), parent, 720)
        self.archive = archive
        top = QGroupBox("EXTRACT TO")
        tl = QHBoxLayout(top)
        self.dest = QComboBox()
        self.dest.setEditable(True)
        self.dest.addItems([dest] + [h for h in (history or []) if h != dest])
        self.dest.setCurrentText(dest)
        browse = QPushButton("...")
        browse.setFixedWidth(44)
        browse.clicked.connect(self._browse)
        tl.addWidget(self.dest, 1)
        tl.addWidget(browse)
        self.body.addWidget(top)
        cols = QHBoxLayout()
        left = QGroupBox("OPTIONS")
        g = QGridLayout(left)
        g.addWidget(field_label("Path mode"), 0, 0)
        self.path_mode = QComboBox()
        for t, _ in self.PATH_MODES:
            self.path_mode.addItem(t)
        g.addWidget(self.path_mode, 0, 1)
        g.addWidget(field_label("Overwrite mode"), 1, 0)
        self.overwrite = QComboBox()
        for t, _ in self.OVERWRITE:
            self.overwrite.addItem(t)
        g.addWidget(self.overwrite, 1, 1)
        self.elim = QCheckBox("Eliminate duplication of root folder")
        g.addWidget(self.elim, 2, 1)
        self.keep_broken = QCheckBox("Keep broken files")
        g.addWidget(self.keep_broken, 3, 1)
        g.setColumnStretch(1, 1)
        cols.addWidget(left, 3)
        right = QGroupBox("PASSWORD")
        pl = QVBoxLayout(right)
        self.pw = QLineEdit(password)
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("not encrypted" if not encrypted else "")
        pl.addWidget(self.pw)
        show = QCheckBox("Show password")
        show.toggled.connect(lambda on: self.pw.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        pl.addWidget(show)
        pl.addStretch(1)
        cols.addWidget(right, 2)
        self.body.addLayout(cols)
        self.add_button("OK", self.accept, default=True)
        self.add_button("Cancel", self.reject)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Extract to", self.dest.currentText())
        if d:
            self.dest.setCurrentText(d)

    def options(self) -> ExtractOptions:
        return ExtractOptions(path_mode=self.PATH_MODES[self.path_mode.currentIndex()][1],
                              overwrite=self.OVERWRITE[self.overwrite.currentIndex()][1],
                              password=self.pw.text(), eliminate_root=self.elim.isChecked(),
                              keep_broken=self.keep_broken.isChecked())

    def destination(self) -> str:
        return self.dest.currentText().strip()


class CopyDialog(ParagonDialog):
    """7-Zip's Copy / Move: 'Copy to:' with a path and a browse button."""

    def __init__(self, title: str, dest: str, count_text: str, parent=None):
        super().__init__(title, title.upper(), parent, 600)
        self.body.addWidget(field_label(f"{title} to"))
        row = QHBoxLayout()
        self.dest = QLineEdit(dest)
        browse = QPushButton("...")
        browse.setFixedWidth(44)
        browse.clicked.connect(self._browse)
        row.addWidget(self.dest, 1)
        row.addWidget(browse)
        self.body.addLayout(row)
        note = QLabel(count_text)
        note.setProperty("role", "dim")
        self.body.addWidget(note)
        self.add_button("OK", self.accept, default=True)
        self.add_button("Cancel", self.reject)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose folder", self.dest.text())
        if d:
            self.dest.setText(d)


class PropertiesDialog(ParagonDialog):
    def __init__(self, title: str, sections: list[tuple[str, list[tuple[str, str]]]], parent=None):
        super().__init__(title, "PROPERTIES", parent, 620)
        self.resize(640, 560)
        for heading, rows in sections:
            box = QGroupBox(heading.upper())
            v = QVBoxLayout(box)
            t = QTableWidget(len(rows), 2)
            t.horizontalHeader().hide()
            t.verticalHeader().hide()
            t.setShowGrid(False)
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.setSelectionBehavior(QAbstractItemView.SelectRows)
            for r, (k, val) in enumerate(rows):
                a = QTableWidgetItem(k)
                a.setForeground(Qt.gray)
                t.setItem(r, 0, a)
                t.setItem(r, 1, QTableWidgetItem(val))
            t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            t.horizontalHeader().setStretchLastSection(True)
            t.verticalHeader().setDefaultSectionSize(26)
            v.addWidget(t)
            self.body.addWidget(box, 1)
        self.add_button("Close", self.accept, default=True)


class TextDialog(ParagonDialog):
    def __init__(self, title: str, subtitle: str, text: str, parent=None):
        super().__init__(title, subtitle, parent, 760)
        self.resize(820, 520)
        self.text = QPlainTextEdit(text)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.body.addWidget(self.text, 1)
        self.add_button("Close", self.accept, default=True)


class HistoryDialog(ParagonDialog):
    def __init__(self, paths: list[str], parent=None):
        super().__init__("Folders History", "FOLDERS HISTORY", parent, 640)
        self.list = QListWidget()
        self.list.addItems(paths)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        if paths:
            self.list.setCurrentRow(0)
        self.body.addWidget(self.list, 1)
        self.add_button("OK", self.accept, default=True)
        self.add_button("Cancel", self.reject)

    def chosen(self) -> str | None:
        it = self.list.currentItem()
        return it.text() if it else None


class AboutDialog(ParagonDialog):
    def __init__(self, parent=None, engine_version: str = ""):
        super().__init__("About PR7-Z", "ABOUT", parent, 520)
        for text, role in ((f"Paragon PR7-Z {__version__}", "heading"),
                           ("The Paragon family's archive manager, working the way 7-Zip File Manager works.", ""),
                           (f"Compression engine: {engine_version or '7-Zip'} by Igor Pavlov (7-zip.org), "
                            "GNU LGPL + unRAR restriction. See engine/7-Zip-License.txt.", "dim"),
                           ("Fonts: Inter (SIL Open Font License 1.1).", "dim")):
            lab = QLabel(text)
            lab.setWordWrap(True)
            if role:
                lab.setProperty("role", role)
            self.body.addWidget(lab)
        self.add_button("OK", self.accept, default=True)


def engine_version(exe: str) -> str:
    import subprocess
    try:
        out = subprocess.run([exe], capture_output=True, timeout=10, stdin=subprocess.DEVNULL,
                             creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0).stdout
        line = next((ln for ln in out.decode("utf-8", "replace").splitlines() if "7-Zip" in ln), "")
        return line.split(":")[0].strip()
    except Exception:
        return ""


def timed(f):
    t = time.monotonic()
    r = f()
    return r, time.monotonic() - t
