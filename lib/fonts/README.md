# Fonts

`RobotoSlab-VariableFont_wght.ttf`: Roboto Slab v2.002 (Copyright 2018 The Roboto Slab
Project Authors, https://github.com/googlefonts/robotoslab), Apache License 2.0
(`LICENSE-Apache-2.0.txt`; license string read from the font's name table, IDs 13/14).
Same file as the owner's installed copy (sha256 3de05586…4c26).

The board's name and copyright texts are KiCad TrueType text in "Roboto Slab". KiCad
stores the rendered glyph outlines (`render_cache`) in the board file, so a machine
without this exact font regenerates a different board file and draws different silk.
CI installs it from here (`.github/workflows/publish.yml`); on a new machine install it
the same way (macOS: copy to ~/Library/Fonts; Linux: ~/.local/share/fonts, then
`fc-cache -f`).
