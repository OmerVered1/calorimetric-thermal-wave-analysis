"""Build the program's bundled fonts from Google Sans.

    python tools/build_fonts.py path/to/GoogleSans[GRAD,opsz,wght].ttf

Google Sans ships only as a variable font. Qt picks weights reliably from
ordinary static files on every platform, so this cuts one file per weight the
program uses, and a second set whose default digits are Google Sans's own
tabular (fixed-width) figures, for readouts and tables where numbers must not
shift sideways as they change. Qt can't switch the tnum feature on from a
stylesheet, so the tabular set has it baked into the character map.

The files are also subset to the scripts this program shows (Latin, Greek,
Hebrew and the usual symbols), which takes them from ~5 MB each to a fraction.

Instancing and subsetting make these Modified Versions under the OFL. Google's
trademark notice for Google Sans asks that modified versions not carry the
Google Sans name, so they are named CTWA Sans. The glyphs are Google Sans's,
unchanged; see ctwa/assets/fonts/README.md.

Source: https://github.com/google/fonts/tree/main/ofl/googlesans
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

FAMILY = "CTWA Sans"
TABULAR_FAMILY = "CTWA Sans Tabular"
WEIGHTS = {"Regular": 400, "Medium": 500, "SemiBold": 600, "Bold": 700}
# Pin the other axes at their defaults.
FIXED_AXES = {"opsz": 18, "GRAD": 0}

UNICODES = [
    *range(0x0020, 0x0250),   # Basic Latin to Latin Extended-B
    *range(0x0300, 0x0370),   # combining marks
    *range(0x0370, 0x0400),   # Greek (Ω, μ)
    *range(0x0590, 0x0600),   # Hebrew
    *range(0x1E00, 0x1F00),   # Latin Extended Additional
    *range(0x2000, 0x2400),   # punctuation, super/subscripts, currency,
                              # letterlike, number forms, arrows, math, technical
    *range(0x2500, 0x2600),   # box drawing, blocks, geometric shapes (●)
    *range(0x2700, 0x27C0),   # dingbats
    *range(0xFB00, 0xFB50),   # ligatures, Hebrew presentation forms
]

OUT = Path(__file__).resolve().parents[1] / "ctwa" / "assets" / "fonts"


def _instance(vf_path: Path, wght: int) -> TTFont:
    font = TTFont(vf_path)
    font = instantiateVariableFont(font, {"wght": wght, **FIXED_AXES})
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.glyph_names = True
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=UNICODES)
    sub.subset(font)
    return font


def _tnum_mapping(font: TTFont) -> dict:
    gsub = font["GSUB"].table
    mapping = {}
    for record in gsub.FeatureList.FeatureRecord:
        if record.FeatureTag != "tnum":
            continue
        for index in record.Feature.LookupListIndex:
            for st in gsub.LookupList.Lookup[index].SubTable:
                st = getattr(st, "ExtSubTable", st)
                mapping.update(getattr(st, "mapping", {}) or {})
    return mapping


def _make_tabular(font: TTFont) -> None:
    """Point the character map at the tabular figures.

    The hyphen-minus also gets the tabular minus sign: Python writes negative
    numbers with a hyphen, which has no tabular form, so a readout would jump
    sideways each time a value crossed zero.
    """
    mapping = _tnum_mapping(font)
    if not mapping:
        raise SystemExit("no tnum substitutions found; is this Google Sans?")
    minus = font.getBestCmap().get(0x2212)
    for table in font["cmap"].tables:
        for cp, glyph in list(table.cmap.items()):
            if glyph in mapping:
                table.cmap[cp] = mapping[glyph]
        if minus and 0x2D in table.cmap:
            table.cmap[0x2D] = mapping.get(minus, minus)


def _rename(font: TTFont, family: str, style: str, wght: int) -> None:
    name = font["name"]
    for nid in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
        name.removeNames(nameID=nid)
    ribbi = style in ("Regular", "Bold")
    ps = f"{family.replace(' ', '')}-{style}"
    version = font["head"].fontRevision
    records = {
        1: family if ribbi else f"{family} {style}",
        2: style if ribbi else "Regular",
        3: f"{version:.3f};{ps}",
        4: f"{family} {style}",
        6: ps,
        16: family,
        17: style,
    }
    for nid, text in records.items():
        name.setName(text, nid, 3, 1, 0x409)
        name.setName(text, nid, 1, 0, 0)
    name.setName("Static, subset build of Google Sans (OFL-1.1) for the Calorimetric "
                 "Thermal Wave Analysis Program. Glyphs unchanged.", 10, 3, 1, 0x409)

    os2 = font["OS/2"]
    os2.usWeightClass = wght
    os2.fsSelection &= ~((1 << 0) | (1 << 5) | (1 << 6))
    os2.fsSelection |= (1 << 5) if style == "Bold" else (1 << 6) if style == "Regular" else 0
    font["head"].macStyle = 1 if style == "Bold" else 0


def build(vf_path: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for style, wght in WEIGHTS.items():
        base = _instance(vf_path, wght)
        buf = io.BytesIO()
        base.save(buf)
        for family, tabular in ((FAMILY, False), (TABULAR_FAMILY, True)):
            buf.seek(0)
            font = TTFont(buf)
            if tabular:
                _make_tabular(font)
            _rename(font, family, style, wght)
            out = OUT / f"{family.replace(' ', '')}-{style}.ttf"
            font.save(out)
            print(f"{out.name:32s} {out.stat().st_size // 1024:5d} KB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(Path(sys.argv[1]))
