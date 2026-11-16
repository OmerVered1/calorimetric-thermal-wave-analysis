"""Draw the CTWA program icon and write every file that uses it.

Run from the repository root:  python3 tools/make_icon.py

The design: "CTWA" in bold serif (Georgia Bold), blue letters with a thin
red-orange outline, on a white rounded tile with a hairline border. Omer chose
it from three candidates, then this outline variant over a red-orange tile
border.

Every size is drawn from vectors at that exact size rather than shrunk from one
big image, which keeps the small taskbar sizes sharp. The outputs are committed,
so the build machines never run this and never need the font; run it again only
to change the design.

Writes:
  assets/app_icon.ico        Windows exe, installer and shortcuts (16-256 px)
  assets/app_icon.icns       macOS app bundle
  ctwa/assets/app_icon_*.png window and taskbar icon set by the running program
  assets/app_icon_1024.png   master, for documents and the README
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QImage,
                           QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent

BLUE = QColor("#1F5BB0")
OUTLINE = QColor("#E4572E")    # red-orange
TILE = QColor("#FFFFFF")
TILE_BORDER = QColor("#D6DCE6")
FONT_FAMILY = "Georgia"

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
WINDOW_SIZES = (16, 24, 32, 48, 64, 128, 256)
# macOS iconset: (file name, pixel size)
ICNS_SET = [(f"icon_{s}x{s}{suffix}.png", s * scale)
            for s in (16, 32, 128, 256, 512)
            for suffix, scale in (("", 1), ("@2x", 2))]


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    margin = size * 0.06
    tile = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    shape = QPainterPath()
    shape.addRoundedRect(tile, size * 0.2, size * 0.2)
    p.fillPath(shape, TILE)
    p.setPen(QPen(TILE_BORDER, max(1.0, size / 128)))
    p.drawPath(shape)

    # Largest bold serif "CTWA" that fits the tile with a small inset.
    pad = size * 0.06
    inner = tile.adjusted(pad, pad, -pad, -pad)
    px = float(size)
    while px > 4:
        font = QFont(FONT_FAMILY)
        font.setPixelSize(max(1, int(px)))
        font.setWeight(QFont.Bold)
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance("CTWA") <= inner.width() and fm.capHeight() <= inner.height():
            break
        px -= 0.5
    width, cap = fm.horizontalAdvance("CTWA"), fm.capHeight()
    letters = QPainterPath()
    letters.addText(QPointF(inner.center().x() - width / 2, inner.center().y() + cap / 2),
                    font, "CTWA")
    p.setPen(QPen(OUTLINE, max(0.6, size * 0.006), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(BLUE)
    p.drawPath(letters)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: Path, sizes) -> None:
    """ICO with one PNG-compressed entry per size (supported since Vista)."""
    blobs = [png_bytes(draw(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, blob in zip(sizes, blobs):
        dim = 0 if s >= 256 else s          # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def write_icns(path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "app_icon.iconset"
        iconset.mkdir()
        for name, px in ICNS_SET:
            draw(px).save(str(iconset / name))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    if FONT_FAMILY not in QFontDatabase.families():
        sys.exit(f"{FONT_FAMILY} is not installed here; the icon would silently use another font.")

    write_ico(ROOT / "assets" / "app_icon.ico", ICO_SIZES)
    if sys.platform == "darwin":
        write_icns(ROOT / "assets" / "app_icon.icns")
    else:
        print("skipping app_icon.icns: iconutil is macOS-only")
    for s in WINDOW_SIZES:
        draw(s).save(str(ROOT / "ctwa" / "assets" / f"app_icon_{s}.png"))
    draw(1024).save(str(ROOT / "assets" / "app_icon_1024.png"))
    print("icon files written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
