"""Draw PR7-Z's icon: the "7Z" mark on a piano-black key with a neon edge.

    python tools/make_icon.py        writes pr7z/icons/app.ico (16-256 px) and app.png

Same letter construction as the PR7 plugins' Logo.cpp (and widgets.py): 1-unit letters,
0.24 stems, 0.2 bars, 0.3 slant, two speed cuts; the 7 in the family gradient, the Z pearl.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRegion, \
    QTransform

from pr7z import theme
from pr7z.widgets import CUTS, SLANT, _poly

OUT = Path(__file__).resolve().parents[1] / "pr7z" / "icons"


def letters():
    seven, zed = QPainterPath(), QPainterPath()
    _poly(seven, [(0, 0), (.8, 0), (.8, .2), (.44, 1), (.18, 1), (.5, .2), (0, .2)], 0)
    _poly(zed, [(0, 0), (.8, 0), (.8, .2), (.3, .8), (.8, .8), (.8, 1), (0, 1), (0, .8), (.5, .2), (0, .2)], .9)
    lean = QTransform(1, 0, -SLANT, 1, SLANT, 0)
    return lean.map(seven), lean.map(zed)


def draw(n: int) -> QImage:
    img = QImage(n, n, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(0, 0, n, n).adjusted(n * .04, n * .04, -n * .04, -n * .04)
    rad = n * .2
    # neon edge, then the black key face inside it
    p.setPen(Qt.NoPen)
    p.setBrush(theme.family_gradient(r.left(), 0, r.right(), 0, theme.NEON * 1.25))
    p.drawRoundedRect(r, rad, rad)
    face = r.adjusted(n * .05, n * .05, -n * .05, -n * .05)
    g = QLinearGradient(face.topLeft(), face.bottomLeft())
    g.setColorAt(0, QColor("#1C1B20"))
    g.setColorAt(1, QColor("#060607"))
    p.setBrush(g)
    p.drawRoundedRect(face, rad * .75, rad * .75)
    if n >= 32:  # gloss over the top
        p.setBrush(QColor(255, 255, 255, 22))
        p.save()
        p.setClipRect(QRectF(face.left(), face.top(), face.width(), face.height() * .5))
        p.drawRoundedRect(face, rad * .75, rad * .75)
        p.restore()
    # the mark: 1.76 letter heights wide with the lean
    h = face.height() * .46
    w = (1.7 + SLANT) * h
    x0, y0 = face.center().x() - w / 2, face.center().y() - h / 2
    place = QTransform().translate(x0, y0).scale(h, h)
    seven, zed = letters()
    seven, zed = place.map(seven), place.map(zed)
    if n >= 48:
        for ring in (3, 2, 1):
            c = QColor(theme.GLOW)
            c.setAlphaF(.1 * (4 - ring))
            p.setPen(QPen(c, h * .07 * ring, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(seven)
    if n >= 32:
        clip = QRegion(face.toAlignedRect())
        for top, bottom in CUTS:
            clip -= QRegion(QRectF(face.left(), y0 + h * top, face.width(), h * (bottom - top)).toAlignedRect())
        p.setClipRegion(clip)
    p.setPen(Qt.NoPen)
    p.fillPath(seven, theme.family_gradient(x0, 0, x0 + w * .55, 0))
    p.fillPath(zed, QColor(theme.TEXT))
    p.end()
    return img


def main():
    QGuiApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    files = []
    for s in sizes:
        f = OUT / f"_icon{s}.png"
        draw(s).save(str(f))
        files.append(f)
    draw(256).save(str(OUT / "app.png"))
    from PIL import Image
    big = Image.open(files[-1])
    big.save(OUT / "app.ico", sizes=[(s, s) for s in sizes],
             append_images=[Image.open(f) for f in files[:-1]])
    for f in files:
        f.unlink()
    print("wrote", OUT / "app.ico")


if __name__ == "__main__":
    main()
