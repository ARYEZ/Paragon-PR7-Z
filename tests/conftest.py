import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(__import__("tempfile").mkdtemp(prefix="family-"), "finish")  # never the real choice

from pr7z import engine  # noqa: E402


@pytest.fixture(scope="session")
def exe():
    try:
        return engine.find_7z()
    except engine.EngineNotFound:
        pytest.skip("no 7-Zip engine here (set PR7Z_7Z to a 7z/7zz binary)")


@pytest.fixture()
def tree(tmp_path):
    """A small folder with a subfolder, a unicode name and a 300 KB incompressible file."""
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    # Exact bytes: write_text would turn \n into \r\n on Windows and change the sizes.
    (src / "a.txt").write_bytes(b"hello\n")
    (src / "sub" / "ünï cødé.txt").write_bytes(b"x\n")
    (src / "sub" / "big.bin").write_bytes(os.urandom(300_000))
    return src


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from pr7z import theme
    # Tests must never touch the real PR7-Z settings.
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    theme.load_fonts()
    app.setStyleSheet(theme.stylesheet())
    yield app


def pytest_collection_modifyitems(config, items):
    if shutil.which("7zz") or shutil.which("7z") or os.environ.get("PR7Z_7Z") or os.name == "nt":
        return
