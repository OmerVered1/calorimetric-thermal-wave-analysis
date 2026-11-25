"""Build every CTWA logo and icon file from Omer's logo image.

Run from the repository root:

    python3 tools/make_icon.py                                   # desktop files
    python3 tools/make_icon.py --webapp ../angstrom-webapp-vercel  # and the webapp's

Needs Pillow and numpy (dev machine only: the outputs are committed, so the
build machines never run this). macOS is needed for the .icns (iconutil).

Source: tools/ctwa_logo_source.png (2000 x 2000, white background, Nov 2026):
two waves over "CTWA", then "Calorimetric Thermal Wave Analysis" and
"Omer Vered's Thesis @ BGU".

Two cuts of it, found from the gaps between the rows of ink:
  mark  the waves and "CTWA" only, for small places (icons, the web header)
  full  everything, for places with room (the About box, the web login page)

The white background becomes transparency (colour-to-alpha against white), so
a cut composited on white is the original pixel for pixel. Dark variants, for
the webapp's dark theme, lift every colour darker than mid-grey towards its
mirror lightness and keep its hue: the black-to-indigo "CTWA" turns
white-to-lavender, the blue and red waves only brighten.

The program icon is the mark on the white rounded tile the previous icon used
(6 % margin, 20 % corner radius, hairline border). Each size is resized from
the 2000 px source in one step, which keeps the small taskbar sizes clean.

Writes (desktop):
  assets/app_icon.ico            Windows exe, installer and shortcuts (16-256 px)
  assets/app_icon.icns           macOS app bundle
  ctwa/assets/app_icon_*.png     window and taskbar icon set by the running program
  assets/app_icon_1024.png       master, for documents and the README
  ctwa/assets/ctwa_logo_full.png the full logo, shown in Help > About
Writes (webapp, with --webapp):
  public/favicon.ico             16 / 32 / 48 px tile
  public/ctwa_logo.png           512 px tile
  public/ctwa_mark.png, public/ctwa_mark_dark.png            header
  public/ctwa_logo_full.png, public/ctwa_logo_full_dark.png  login page
"""

from __future__ import annotations

import argparse
import io
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tools" / "ctwa_logo_source.png"

TILE = (255, 255, 255, 255)
TILE_BORDER = (214, 220, 230, 255)      # #D6DCE6, as the previous icon
TILE_MARGIN = 0.06                      # of the icon size
TILE_RADIUS = 0.20
MARK_PAD = 0.06                         # inside the tile, each side

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
WINDOW_SIZES = (16, 24, 32, 48, 64, 128, 256)
WEB_ICO_SIZES = (16, 32, 48)
# macOS iconset: (file name, pixel size)
ICNS_SET = [(f"icon_{s}x{s}{suffix}.png", s * scale)
            for s in (16, 32, 128, 256, 512)
            for suffix, scale in (("", 1), ("@2x", 2))]

INK = 0.08          # alpha above which a pixel counts as part of the logo
DARK_LIFT = 1.15    # dark variant: raise max+min of each colour to at least this


# ----- the two cuts ------------------------------------------------------------

def color_to_alpha(rgb: np.ndarray) -> np.ndarray:
    """RGB in 0..1 on white -> RGBA whose composite on white is the input.

    The logo is solid colour with anti-aliased edges. Plain colour-to-alpha
    would read a pastel fill (the pink subtitle) as a saturated colour at 65 %
    opacity, which looks dark on a dark surface. So: pixels well inside the ink
    (2 px from any white) keep their colour, fully opaque; each edge pixel takes
    the colour of the nearest inside pixel, and its alpha is how far it is
    blended from that colour towards white.
    """
    from scipy import ndimage

    ink = (1.0 - rgb.min(axis=2)) > 0.02
    inside = ndimage.binary_erosion(ink, structure=np.ones((5, 5), bool))
    _, (iy, ix) = ndimage.distance_transform_edt(~inside, return_indices=True)
    color = rgb[iy, ix]                                 # nearest inside colour
    room = 1.0 - color                                  # how far that colour is from white
    gone = 1.0 - rgb                                    # how far this pixel is from white
    use = room > 0.05
    a = np.where(use, gone / np.where(use, room, 1.0), 0.0).max(axis=2)
    a = np.where(inside, 1.0, np.where(ink, np.clip(a, 0.0, 1.0), 0.0))
    color[a == 0] = 0.0
    return np.dstack([color, a])


def ink_rows(alpha: np.ndarray):
    """Runs of rows (top, bottom inclusive) that hold ink."""
    has = (alpha > INK).any(axis=1)
    runs, start = [], None
    for y, v in enumerate(has):
        if v and start is None:
            start = y
        elif not v and start is not None:
            runs.append((start, y - 1))
            start = None
    if start is not None:
        runs.append((start, len(has) - 1))
    return runs


def crop(rgba: np.ndarray, top: int, bottom: int) -> np.ndarray:
    """Rows top..bottom, trimmed to their ink columns, with a small even margin."""
    band = rgba[top:bottom + 1]
    cols = np.where((band[..., 3] > INK).any(axis=0))[0]
    pad = max(2, round((bottom - top) * 0.02))
    left, right = max(0, cols.min() - pad), min(rgba.shape[1], cols.max() + 1 + pad)
    t, b = max(0, top - pad), min(rgba.shape[0], bottom + 1 + pad)
    return rgba[t:b, left:right]


def cuts():
    rgb = np.asarray(Image.open(SOURCE).convert("RGB"), dtype=np.float64) / 255.0
    rgba = color_to_alpha(rgb)
    runs = ink_rows(rgba[..., 3])
    if len(runs) < 3:
        sys.exit(f"expected waves, letters and text lines in {SOURCE.name}; found {len(runs)} rows of ink")
    # "CTWA" is the tallest run; the mark is it and everything above it.
    letters = max(range(len(runs)), key=lambda i: runs[i][1] - runs[i][0])
    mark = crop(rgba, runs[0][0], runs[letters][1])
    full = crop(rgba, runs[0][0], runs[-1][1])
    return mark, full


def dark(rgba: np.ndarray) -> np.ndarray:
    """Same hue, lifted so it reads on a dark surface."""
    rgb = rgba[..., :3]
    lift = np.clip(DARK_LIFT - (rgb.max(axis=2) + rgb.min(axis=2)), 0.0, None)[..., None]
    return np.dstack([np.clip(rgb + lift, 0.0, 1.0), rgba[..., 3]])


def to_image(rgba: np.ndarray) -> Image.Image:
    return Image.fromarray(np.round(rgba * 255).astype(np.uint8))     # (h, w, 4) -> RGBA


def resized(img: Image.Image, width: int, height: int) -> Image.Image:
    """Lanczos on premultiplied alpha, so edges don't pick up a dark fringe."""
    return img.convert("RGBa").resize((width, height), Image.LANCZOS).convert("RGBA")


def to_width(img: Image.Image, width: int) -> Image.Image:
    return resized(img, width, max(1, round(img.height * width / img.width)))


def to_height(img: Image.Image, height: int) -> Image.Image:
    return resized(img, max(1, round(img.width * height / img.height)), height)


# ----- the program icon --------------------------------------------------------

def tile(size: int) -> Image.Image:
    """The white rounded tile, drawn at 4x and reduced for smooth edges."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    m = s * TILE_MARGIN
    ImageDraw.Draw(img).rounded_rectangle(
        (m, m, s - m, s - m), radius=s * TILE_RADIUS, fill=TILE,
        outline=TILE_BORDER, width=max(4, round(s / 128)))
    return img.resize((size, size), Image.LANCZOS)


def icon(mark: Image.Image, size: int) -> Image.Image:
    img = tile(size)
    inner = size * (1 - 2 * TILE_MARGIN - 2 * MARK_PAD)
    scale = min(inner / mark.width, inner / mark.height)
    w, h = max(1, round(mark.width * scale)), max(1, round(mark.height * scale))
    img.alpha_composite(resized(mark, w, h), ((size - w) // 2, (size - h) // 2))
    return img


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def write_ico(path: Path, images) -> None:
    """ICO with one PNG-compressed entry per size (supported since Vista)."""
    blobs = [png_bytes(img) for img in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for img, blob in zip(images, blobs):
        dim = 0 if img.width >= 256 else img.width      # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def write_icns(path: Path, mark: Image.Image) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "app_icon.iconset"
        iconset.mkdir()
        for name, px in ICNS_SET:
            icon(mark, px).save(iconset / name)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)


# ----- outputs -----------------------------------------------------------------

def write_desktop(mark: Image.Image, full: Image.Image) -> None:
    write_ico(ROOT / "assets" / "app_icon.ico", [icon(mark, s) for s in ICO_SIZES])
    if sys.platform == "darwin":
        write_icns(ROOT / "assets" / "app_icon.icns", mark)
    else:
        print("skipping app_icon.icns: iconutil is macOS-only")
    for s in WINDOW_SIZES:
        icon(mark, s).save(ROOT / "ctwa" / "assets" / f"app_icon_{s}.png")
    icon(mark, 1024).save(ROOT / "assets" / "app_icon_1024.png")
    # Shown 300 px wide in Help > About; twice that for high-DPI screens.
    to_width(full, 600).save(ROOT / "ctwa" / "assets" / "ctwa_logo_full.png", optimize=True)
    print("desktop logo files written")


def write_webapp(public: Path, mark: Image.Image, full: Image.Image,
                 mark_dark: Image.Image, full_dark: Image.Image) -> None:
    write_ico(public / "favicon.ico", [icon(mark, s) for s in WEB_ICO_SIZES])
    icon(mark, 512).save(public / "ctwa_logo.png", optimize=True)
    # Header: 40 CSS px tall; login: 288 CSS px wide. Four times that for sharp
    # high-DPI rendering (next/image serves smaller copies to smaller screens).
    to_height(mark, 160).save(public / "ctwa_mark.png", optimize=True)
    to_height(mark_dark, 160).save(public / "ctwa_mark_dark.png", optimize=True)
    to_width(full, 1152).save(public / "ctwa_logo_full.png", optimize=True)
    to_width(full_dark, 1152).save(public / "ctwa_logo_full_dark.png", optimize=True)
    print(f"webapp logo files written to {public}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--webapp", type=Path, help="webapp repository root (writes its public/ files)")
    args = ap.parse_args()

    mark_px, full_px = cuts()
    mark, full = to_image(mark_px), to_image(full_px)
    write_desktop(mark, full)
    if args.webapp:
        public = args.webapp / "public"
        if not public.is_dir():
            sys.exit(f"{public} is not a directory")
        write_webapp(public, mark, full, to_image(dark(mark_px)), to_image(dark(full_px)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
