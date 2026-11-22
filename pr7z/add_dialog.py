"""The "Add to Archive" dialog: 7-Zip's fields and rules, as Paragon dock panels."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from . import engine
from .dialogs import ParagonDialog, field_label, message
from .engine import AddOptions

LEVELS = [("0 - Store", 0), ("1 - Fastest", 1), ("3 - Fast", 3), ("5 - Normal", 5), ("7 - Maximum", 7),
          ("9 - Ultra", 9)]
AUTO = "Auto"
LZMA_DICTS = ["64 KB", "256 KB", "1 MB", "2 MB", "4 MB", "8 MB", "16 MB", "32 MB", "64 MB", "128 MB", "256 MB",
              "512 MB", "1024 MB", "1536 MB"]
PPMD_DICTS = ["1 MB", "2 MB", "4 MB", "8 MB", "16 MB", "32 MB", "64 MB", "128 MB", "256 MB", "512 MB", "1024 MB"]
WORDS = {"LZMA2": ["8", "12", "16", "24", "32", "48", "64", "96", "128", "192", "256", "273"],
         "LZMA": ["8", "12", "16", "24", "32", "48", "64", "96", "128", "192", "256", "273"],
         "PPMd": ["2", "3", "4", "5", "6", "7", "8", "10", "12", "14", "16", "20", "24", "28", "32"],
         "Deflate": ["8", "12", "16", "24", "32", "48", "64", "96", "128", "192", "256", "258"],
         "Deflate64": ["8", "12", "16", "24", "32", "48", "64", "96", "128", "192", "256", "257"]}
SOLID = [AUTO, "Non-solid", "1 MB", "2 MB", "4 MB", "8 MB", "16 MB", "32 MB", "64 MB", "128 MB", "256 MB",
         "512 MB", "1 GB", "2 GB", "4 GB", "8 GB", "16 GB", "32 GB", "64 GB", "Solid"]
UPDATE_MODES = [("Add and replace files", "add"), ("Update and add files", "update"),
                ("Freshen existing files", "freshen"), ("Synchronize files", "sync")]
PATH_MODES = [("Relative pathnames", "relative"), ("Full pathnames", "full"), ("Absolute pathnames", "absolute")]
VOLUMES = ["", "10M", "100M", "1000M", "650M - CD", "700M - CD", "4092M - FAT", "4480M - DVD", "8128M - DVD DL",
           "23040M - BD"]


def size_switch(text: str) -> str:
    """'64 MB' -> '64m', '1 GB' -> '1g', '256 KB' -> '256k' (7z's size syntax)."""
    num, _, unit = text.partition(" ")
    return num + {"KB": "k", "MB": "m", "GB": "g"}.get(unit, "")


def default_archive_name(files: list[str], fmt: str = "7z") -> str:
    """7-Zip's suggestion: one item -> its name; several -> the folder they're in."""
    ext = engine.FORMAT_EXT[fmt]
    if len(files) == 1:
        p = Path(files[0])
        base = p.name if p.is_dir() else (p.stem if fmt not in engine.SINGLE_FILE_FORMATS else p.name)
        return str(p.parent / f"{base}.{ext}")
    parent = Path(files[0]).parent
    return str(parent / f"{parent.name or 'Archive'}.{ext}")


class AddDialog(ParagonDialog):
    def __init__(self, files: list[str], archive: str | None = None, parent=None, fixed_archive: bool = False):
        super().__init__("Add to Archive", "ADD TO ARCHIVE", parent, 900)
        self.files = files
        self.fixed_archive = fixed_archive

        arch = QGroupBox("ARCHIVE")
        al = QHBoxLayout(arch)
        self.archive = QComboBox()
        self.archive.setEditable(True)
        self.archive.setCurrentText(archive or default_archive_name(files))
        self.archive.setEnabled(not fixed_archive)
        browse = QPushButton("...")
        browse.setFixedWidth(44)
        browse.clicked.connect(self._browse)
        browse.setEnabled(not fixed_archive)
        al.addWidget(self.archive, 1)
        al.addWidget(browse)
        self.body.addWidget(arch)

        cols = QHBoxLayout()
        cols.setSpacing(12)
        comp = QGroupBox("COMPRESSION")
        g = QGridLayout(comp)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(7)
        self.format = QComboBox()
        self.format.addItems(engine.CREATE_FORMATS)
        self.level = QComboBox()
        self.method = QComboBox()
        self.dict = QComboBox()
        self.word = QComboBox()
        self.solid = QComboBox()
        self.solid.addItems(SOLID)
        self.threads = QComboBox()
        self.threads.addItems([AUTO] + [str(i) for i in range(1, (os.cpu_count() or 8) * 2 + 1)])
        self.memory = QLabel("")
        self.memory.setProperty("role", "dim")
        self.volumes = QComboBox()
        self.volumes.setEditable(True)
        self.volumes.addItems(VOLUMES)
        self.params = QLineEdit()
        self.params.setPlaceholderText("e.g. qs=on tc=on")
        rows = [("Archive format", self.format), ("Compression level", self.level),
                ("Compression method", self.method), ("Dictionary size", self.dict), ("Word size", self.word),
                ("Solid block size", self.solid), ("CPU threads", self.threads), ("Memory usage", self.memory),
                ("Split to volumes, bytes", self.volumes), ("Parameters", self.params)]
        for r, (label, w) in enumerate(rows):
            g.addWidget(field_label(label), r, 0)
            g.addWidget(w, r, 1)
        g.setColumnStretch(1, 1)
        g.setRowStretch(len(rows), 1)
        cols.addWidget(comp, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        upd = QGroupBox("UPDATE")
        ug = QGridLayout(upd)
        ug.setVerticalSpacing(7)
        self.update_mode = QComboBox()
        self.update_mode.addItems([t for t, _ in UPDATE_MODES])
        self.path_mode = QComboBox()
        self.path_mode.addItems([t for t, _ in PATH_MODES])
        ug.addWidget(field_label("Update mode"), 0, 0)
        ug.addWidget(self.update_mode, 0, 1)
        ug.addWidget(field_label("Path mode"), 1, 0)
        ug.addWidget(self.path_mode, 1, 1)
        ug.setColumnStretch(1, 1)
        right.addWidget(upd)
        opts = QGroupBox("OPTIONS")
        ol = QVBoxLayout(opts)
        ol.setSpacing(6)
        self.sfx = QCheckBox("Create SFX archive")
        self.shared = QCheckBox("Compress shared files")
        self.delete_after = QCheckBox("Delete files after compression")
        for c in (self.sfx, self.shared, self.delete_after):
            ol.addWidget(c)
        if os.name != "nt":
            self.shared.setEnabled(False)
        right.addWidget(opts)
        enc = QGroupBox("ENCRYPTION")
        eg = QGridLayout(enc)
        eg.setVerticalSpacing(7)
        self.pw1, self.pw2 = QLineEdit(), QLineEdit()
        for pw in (self.pw1, self.pw2):
            pw.setEchoMode(QLineEdit.Password)
        self.show_pw = QCheckBox("Show password")
        self.show_pw.toggled.connect(self._show_pw)
        self.enc_method = QComboBox()
        self.enc_names = QCheckBox("Encrypt file names")
        eg.addWidget(field_label("Enter password"), 0, 0)
        eg.addWidget(self.pw1, 0, 1)
        self.pw2_label = field_label("Reenter password")
        eg.addWidget(self.pw2_label, 1, 0)
        eg.addWidget(self.pw2, 1, 1)
        eg.addWidget(self.show_pw, 2, 1)
        eg.addWidget(field_label("Encryption method"), 3, 0)
        eg.addWidget(self.enc_method, 3, 1)
        eg.addWidget(self.enc_names, 4, 1)
        eg.setColumnStretch(1, 1)
        right.addWidget(enc)
        right.addStretch(1)
        cols.addLayout(right, 1)
        self.body.addLayout(cols, 1)
        self.add_button("OK", self._ok, default=True)
        self.add_button("Cancel", self.reject)

        self.format.currentTextChanged.connect(self._format_changed)
        self.level.currentIndexChanged.connect(self._level_changed)
        self.method.currentTextChanged.connect(self._method_changed)
        self.dict.currentTextChanged.connect(self._memory)
        self.threads.currentTextChanged.connect(self._memory)
        self.sfx.toggled.connect(self._sync_extension)
        ext = Path(self.archive.currentText()).suffix.lower().lstrip(".")
        start = next((f for f, e in engine.FORMAT_EXT.items() if e == ext), "7z")
        if fixed_archive and archive:
            try:
                t = engine.list_archive(archive).type.lower()
                start = t if t in engine.CREATE_FORMATS else start
            except Exception:
                pass
            self.format.setEnabled(False)
        self.format.blockSignals(True)
        self.format.setCurrentText(start)
        self.format.blockSignals(False)
        self._format_changed(start)

    # ------------------------------------------------------------ rules
    def _format_changed(self, fmt: str):
        store_only = fmt in ("tar", "wim")
        self.level.blockSignals(True)
        self.level.clear()
        for t, _ in (LEVELS[:1] if store_only else LEVELS):
            self.level.addItem(t)
        self.level.setCurrentIndex(0 if store_only else 3)
        self.level.blockSignals(False)
        self.method.blockSignals(True)
        self.method.clear()
        self.method.addItems(engine.METHODS.get(fmt, []))
        self.method.blockSignals(False)
        self.solid.setEnabled(fmt == "7z")
        self.threads.setEnabled(not store_only)
        self.sfx.setEnabled(fmt == "7z")
        if fmt != "7z":
            self.sfx.setChecked(False)
        encs = engine.ENCRYPTION.get(fmt, [])
        self.enc_method.clear()
        self.enc_method.addItems(encs)
        for w in (self.pw1, self.pw2, self.show_pw, self.enc_method):
            w.setEnabled(bool(encs))
        if fmt == "zip":
            self.enc_method.setCurrentText("AES-256")
        self.enc_names.setEnabled(fmt == "7z")
        if fmt != "7z":
            self.enc_names.setChecked(False)
        self._method_changed(self.method.currentText())
        self._sync_extension()

    def _level_changed(self, _i=0):
        compressing = self._level() != 0 and self._fmt() not in ("tar", "wim")
        self.method.setEnabled(compressing and bool(engine.METHODS.get(self._fmt())))
        self.dict.setEnabled(compressing and self.dict.count() > 1)
        self.word.setEnabled(compressing and self.word.count() > 1)
        self.solid.setEnabled(compressing and self._fmt() == "7z")
        self._memory()

    def _method_changed(self, method: str):
        self.dict.blockSignals(True)
        self.dict.clear()
        self.word.clear()
        if method in ("LZMA", "LZMA2"):
            self.dict.addItems([AUTO] + LZMA_DICTS)
        elif method == "PPMd":
            self.dict.addItems([AUTO] + PPMD_DICTS)
        elif method == "BZip2":
            self.dict.addItems(["900 KB"])
        elif method in ("Deflate", "Deflate64"):
            self.dict.addItems(["32 KB" if method == "Deflate" else "64 KB"])
        if method in WORDS:
            self.word.addItems([AUTO] + WORDS[method])
        self.dict.blockSignals(False)
        self._level_changed()

    def _memory(self, *_):
        d = self.dict.currentText()
        method = self.method.currentText()
        if not self.dict.isEnabled() or not d or d == AUTO:
            self.memory.setText("Chosen by 7-Zip for the level" if self._level() else "None (store)")
            return
        mb = float(size_switch(d)[:-1]) / (1024 if d.endswith("KB") else 1)
        threads = int(self.threads.currentText()) if self.threads.currentText().isdigit() else (os.cpu_count() or 4)
        if method in ("LZMA", "LZMA2"):
            comp = mb * 11.5 + (max(1, threads) // 2) * 32 if method == "LZMA2" else mb * 11.5
            dec = mb + 2
        else:
            comp, dec = mb * 1.1 + 2, mb + 2
        self.memory.setText(f"Compressing  ~{comp:,.0f} MB      Decompressing  ~{dec:,.0f} MB".replace(",", " "))

    def _sync_extension(self, *_):
        if self.fixed_archive:
            return
        p = Path(self.archive.currentText())
        want = "exe" if self.sfx.isChecked() else engine.FORMAT_EXT[self._fmt()]
        known = set(engine.FORMAT_EXT.values()) | {"exe"}
        stem = p.name[: -len(p.suffix)] if p.suffix.lower().lstrip(".") in known else p.name
        if self._fmt() in engine.SINGLE_FILE_FORMATS and len(self.files) == 1:
            stem = Path(self.files[0]).name
        elif len(self.files) == 1 and stem == Path(self.files[0]).name and not Path(self.files[0]).is_dir():
            stem = Path(self.files[0]).stem  # back from gzip etc.: x.txt -> x
        self.archive.setCurrentText(str(p.with_name(f"{stem}.{want}")))

    def _show_pw(self, on: bool):
        self.pw1.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self.pw2.setVisible(not on)
        self.pw2_label.setVisible(not on)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Browse", self.archive.currentText())
        if path:
            self.archive.setCurrentText(path)

    def _fmt(self) -> str:
        return self.format.currentText()

    def _level(self) -> int:
        t = self.level.currentText()
        return int(t.split(" ")[0]) if t else 5

    def _ok(self):
        if not self.show_pw.isChecked() and self.pw1.text() != self.pw2.text():
            message(self, "Add to Archive", "Passwords do not match.")
            return
        if self._fmt() in engine.SINGLE_FILE_FORMATS and (len(self.files) != 1 or Path(self.files[0]).is_dir()):
            message(self, "Add to Archive", f"{self._fmt()} can compress only one file. Use 7z, zip or tar "
                    "to put several files or a folder together.")
            return
        if not self.archive.currentText().strip():
            return
        self.accept()

    # ------------------------------------------------------------ result
    def archive_path(self) -> str:
        return self.archive.currentText().strip()

    def options(self) -> AddOptions:
        solid = self.solid.currentText()
        solid_sw = {AUTO: "", "Non-solid": "off", "Solid": "on"}.get(solid, size_switch(solid))
        dict_txt = self.dict.currentText()
        word_txt = self.word.currentText()
        vol = self.volumes.currentText().split(" ")[0].strip().lower()
        return AddOptions(
            format=self._fmt(), level=self._level(),
            method=self.method.currentText() if self.method.isEnabled() else "",
            dictionary=size_switch(dict_txt) if self.dict.isEnabled() and dict_txt not in ("", AUTO) else "",
            word_size=word_txt if self.word.isEnabled() and word_txt not in ("", AUTO) else "",
            solid=solid_sw if self.solid.isEnabled() else "",
            threads=self.threads.currentText() if self.threads.isEnabled() and self.threads.currentText() != AUTO
            else "",
            volumes=vol, parameters=self.params.text(),
            update_mode=UPDATE_MODES[self.update_mode.currentIndex()][1],
            path_mode=PATH_MODES[self.path_mode.currentIndex()][1],
            sfx=self.sfx.isChecked(), shared=self.shared.isChecked(), delete_after=self.delete_after.isChecked(),
            password=self.pw1.text() if self.pw1.isEnabled() else "",
            encryption=self.enc_method.currentText() or "AES-256", encrypt_names=self.enc_names.isChecked())
