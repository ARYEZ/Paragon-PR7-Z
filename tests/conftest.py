import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
    (src / "a.txt").write_text("hello\n", encoding="utf-8")
    (src / "sub" / "ünï cødé.txt").write_text("x\n", encoding="utf-8")
    (src / "sub" / "big.bin").write_bytes(os.urandom(300_000))
    return src


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    from pr7z import theme
    app = QApplication.instance() or QApplication([])
    theme.load_fonts()
    app.setStyleSheet(theme.stylesheet())
    yield app


def pytest_collection_modifyitems(config, items):
    if shutil.which("7zz") or shutil.which("7z") or os.environ.get("PR7Z_7Z") or os.name == "nt":
        return
