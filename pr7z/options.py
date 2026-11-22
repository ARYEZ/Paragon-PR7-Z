"""Tools > Options: the Explorer menu (7-Zip's "7-Zip" tab), file types, view and editor settings."""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from . import shell
from .dialogs import ParagonDialog, field_label, message


class OptionsDialog(ParagonDialog):
    def __init__(self, window):
        super().__init__("Options", "OPTIONS", window, 680)
        self.win = window
        s = window.settings
        ok = shell.available()
        state = shell.read_settings()

        menu = QGroupBox("EXPLORER CONTEXT MENU")
        ml = QVBoxLayout(menu)
        self.integrate = QCheckBox("Integrate PR7-Z to shell context menu")
        self.integrate.setChecked(bool(shell.menu_registered()))
        self.cascaded = QCheckBox("Cascaded context menu")
        self.cascaded.setChecked(state["cascaded"])
        ml.addWidget(self.integrate)
        ml.addWidget(self.cascaded)
        self.kind = QLabel()
        self.kind.setProperty("role", "dim")
        self.kind.setWordWrap(True)
        ml.addWidget(self.kind)
        ml.addWidget(field_label("Context menu items"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self.items: list[QCheckBox] = []
        half = (len(shell.MENU_ITEMS) + 1) // 2
        for i, name in enumerate(shell.MENU_ITEMS):
            c = QCheckBox(name)
            c.setChecked(bool(state["items"] >> i & 1))
            self.items.append(c)
            grid.addWidget(c, i % half, i // half)
        ml.addLayout(grid)
        self.integrate.toggled.connect(self._enable)
        self.body.addWidget(menu)

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
        if not ok:
            for w in [self.integrate, self.cascaded, self.types_add, self.types_remove, *self.items]:
                w.setEnabled(False)
        self._refresh()
        self._enable(self.integrate.isChecked())

    def _enable(self, on: bool):
        has_dll = shell.shell_dll() is not None
        for w in [self.cascaded, *self.items]:
            w.setEnabled(on and shell.available() and has_dll)

    def _refresh(self):
        if not shell.available():
            self.kind.setText("Available on Windows.")
            self.types_state.setText("Available on Windows.")
            return
        kind = shell.menu_registered()
        if shell.shell_dll() is None:
            self.kind.setText("The menu extension (PR7ZShell.dll) isn't in this copy of PR7-Z, so a basic menu with "
                              "fixed names is used. The release build includes it.")
        else:
            self.kind.setText({"extension": "On. Changes apply on the next right-click.",
                               "basic": "The basic menu is on; OK switches it to the full menu.",
                               "": "Off."}[kind])
        self.types_state.setText("Added." if shell.open_with_registered() else "Not added.")

    def _do(self, f):
        try:
            f()
        except OSError as e:
            message(self, "Options", str(e))
        self._refresh()

    def items_mask(self) -> int:
        return sum(1 << i for i, c in enumerate(self.items) if c.isChecked())

    def _ok(self):
        if shell.available():
            try:
                if self.integrate.isChecked():
                    shell.write_settings(self.cascaded.isChecked(), self.items_mask())
                    shell.register_menu()
                elif shell.menu_registered():
                    shell.unregister_menu()
            except OSError as e:
                message(self, "Options", str(e))
                return
        self.win.settings.setValue("editor", self.editor.text().strip())
        if self.hidden.isChecked() != self.win.show_hidden:
            self.win.hidden_act.setChecked(self.hidden.isChecked())
            self.win._toggle_hidden()
        self.accept()

