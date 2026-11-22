"""Tools > Options: Explorer integration, file types, view and editor settings."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from . import shell
from .dialogs import ParagonDialog, field_label, message


class OptionsDialog(ParagonDialog):
    def __init__(self, window):
        super().__init__("Options", "OPTIONS", window, 620)
        self.win = window
        s = window.settings

        exp = QGroupBox("EXPLORER")
        el = QVBoxLayout(exp)
        self.menu_state = QLabel()
        self.menu_state.setProperty("role", "dim")
        el.addWidget(QLabel("Add a PR7-Z submenu to Explorer's right-click menu: Open, Extract files, Extract Here, "
                            "Extract to folder, Test, Add to archive, Add to .7z / .zip, CRC SHA."))
        el.addWidget(self.menu_state)
        row = QHBoxLayout()
        self.menu_add = QPushButton("Add to Explorer")
        self.menu_remove = QPushButton("Remove")
        self.menu_add.clicked.connect(lambda: self._do(shell.register_menu))
        self.menu_remove.clicked.connect(lambda: self._do(shell.unregister_menu))
        row.addWidget(self.menu_add)
        row.addWidget(self.menu_remove)
        row.addStretch(1)
        el.addLayout(row)
        self.body.addWidget(exp)

        types = QGroupBox("FILE TYPES")
        tl = QVBoxLayout(types)
        tl.addWidget(QLabel("List PR7-Z under \"Open with\" for archive files (.7z, .zip, .rar, .iso ...). "
                            "Windows then lets you make it the default app."))
        self.types_state = QLabel()
        self.types_state.setProperty("role", "dim")
        tl.addWidget(self.types_state)
        row = QHBoxLayout()
        self.types_add = QPushButton("Add")
        self.types_remove = QPushButton("Remove")
        self.types_add.clicked.connect(lambda: self._do(shell.register_open_with))
        self.types_remove.clicked.connect(lambda: self._do(shell.unregister_open_with))
        row.addWidget(self.types_add)
        row.addWidget(self.types_remove)
        row.addStretch(1)
        tl.addLayout(row)
        self.body.addWidget(types)

        other = QGroupBox("VIEW AND EDITOR")
        ol = QVBoxLayout(other)
        self.hidden = QCheckBox("Show hidden files")
        self.hidden.setChecked(window.show_hidden)
        ol.addWidget(self.hidden)
        ol.addWidget(field_label("Editor (F4)"))
        self.editor = QLineEdit(s.value("editor", "notepad.exe"))
        ol.addWidget(self.editor)
        self.body.addWidget(other)

        self.add_button("OK", self._ok, default=True)
        self.add_button("Cancel", self.reject)
        self._refresh()

    def _refresh(self):
        ok = shell.available()
        for b in (self.menu_add, self.menu_remove, self.types_add, self.types_remove):
            b.setEnabled(ok)
        if not ok:
            self.menu_state.setText("Available on Windows.")
            self.types_state.setText("Available on Windows.")
            return
        self.menu_state.setText("Added." if shell.menu_registered() else "Not added.")
        self.types_state.setText("Added." if shell.open_with_registered() else "Not added.")

    def _do(self, f):
        try:
            f()
        except OSError as e:
            message(self, "Options", str(e))
        self._refresh()

    def _ok(self):
        self.win.settings.setValue("editor", self.editor.text().strip())
        if self.hidden.isChecked() != self.win.show_hidden:
            self.win.hidden_act.setChecked(self.hidden.isChecked())
            self.win._toggle_hidden()
        self.accept()
