# Bundled fonts

Every piece of text in the program is set in **Google Sans**, bundled here so
it looks the same on every lab PC whatever fonts are installed.

| Files | Family | Used for |
|---|---|---|
| `CTWASans-*.ttf` | CTWA Sans | all interface text |
| `CTWASansTabular-*.ttf` | CTWA Sans Tabular | readouts, tables, figures: the same font with fixed-width digits, so numbers don't shift sideways as they change |

Weights: Regular (400), Medium (500), SemiBold (600), Bold (700).

## Where they come from

Built by `tools/build_fonts.py` from Google Sans
(`GoogleSans[GRAD,opsz,wght].ttf`,
https://github.com/google/fonts/tree/main/ofl/googlesans), released by Google
under the SIL Open Font License 1.1 (`OFL.txt`).

The build takes one static instance per weight from the variable font (Qt picks
weights reliably from static files on every platform), subsets to Latin,
Greek, Hebrew and common symbols, and for the Tabular set points the digits
and the minus sign at Google Sans's own tabular glyphs. No outline is changed.

## Why the name is different

Instancing and subsetting make these Modified Versions under the OFL. Google's
trademark notice (`TRADEMARKS.md`) asks that modified versions not carry the
"Google Sans" name, so the files are named CTWA Sans. They are Google Sans
glyph for glyph; the program has no affiliation with Google.
