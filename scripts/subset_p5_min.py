#!/usr/bin/env python3
"""Minimal-delta P5 subset: keep every structure byte-identical.

`subset_p5.py` rebuilds the JNCM character maps and the JNFR fonts with only the
kept glyphs, which changes the mapping tables (the code point lists live at
e.g. P5+0x2A1C / P5+0x2C68) and the glyph order.  P1 reads those structures
during the very first boot stage (display init + warning screen), so this
variant leaves them alone:

  * JNCM character maps: untouched, byte for byte
  * JNFR headers, glyph counts, width tables, bitmap offsets: untouched
  * every glyph keeps its allocated bytes, so the total P5 image stays exactly
    the same length and no other P5 pointer has to move
  * only the width entry and bitmap bytes of glyphs the UI never uses are
    zeroed, which is what shrinks the compressed stream

Usage:
    python3 scripts/subset_p5_min.py INPUT_P5.bin OUTPUT_P5.bin [--wipe-dat1]
"""

from __future__ import annotations

import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import subset_p5 as sp  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wipe_dat1 = "--wipe-dat1" in sys.argv
    if len(args) != 2:
        print(__doc__.strip())
        return 2

    in_path, out_path = args
    p5 = bytearray(open(in_path, "rb").read())
    original = bytes(p5)

    jncm_offsets = [m.start() for m in re.finditer(b"JNCM", p5)]
    jnfr_offsets = [m.start() for m in re.finditer(b"JNFR", p5)]
    if len(jncm_offsets) != 4 or len(jnfr_offsets) != 4:
        print(f"expected 4 JNCM and 4 JNFR, found {len(jncm_offsets)}/{len(jnfr_offsets)}",
              file=sys.stderr)
        return 1

    maps = [sp.parse_jncm(p5, off) for off in jncm_offsets]
    fonts = []
    for off in jnfr_offsets:
        count = struct.unpack_from("<H", p5, off + 6)[0]
        matches = [m for m in maps if m["count"] == count]
        if len(matches) != 1:
            print(f"cannot associate JNFR 0x{off:X}", file=sys.stderr)
            return 1
        font = sp.parse_jnfr(p5, off, count)
        font["map"] = matches[0]
        fonts.append(font)
    fonts.sort(key=lambda f: f["offset"])

    main_fonts = [f for f in fonts if f["count"] not in (59, 26)]
    big_count = max(f["count"] for f in main_fonts)
    small_count = min(f["count"] for f in main_fonts)
    small_seq = next(f["map"]["seq"] for f in main_fonts if f["count"] == small_count)

    # Same keep-sets as subset_p5.py: Chinese + English DAT1 UI strings in the
    # large font, the original 9x9 repertoire in the small font, plus the
    # runtime digits and the '@' fallback.
    big = set()
    for block_index in (0, 1):
        big |= sp.extract_dat1_text_chars(p5, block_index=block_index)
    small = set(small_seq)
    big |= small
    big.add(0x8BFB)  # legacy JNLL menu string
    big |= set(range(0x30, 0x3A)) | {0x40}
    small |= set(range(0x30, 0x3A)) | {0x40}

    if wipe_dat1:
        blocks, freed = sp.clear_other_language_dat1_blocks(p5, keep={0, 1})
        print(f"cleared {blocks} non-Chinese/English DAT1 payloads ({freed} bytes)")

    total_blanked = 0
    for index, font in enumerate(fonts):
        seq = font["map"]["seq"]
        if font["count"] in (59, 26):
            keep = set(seq)
        elif font["count"] == big_count:
            keep = big
        else:
            keep = small

        width_offset = font["width_offset"]
        glyph_size = font["glyph_size"]
        bitmap_offset = font["bitmap_offset"]
        blanked = 0
        for i, cp in enumerate(seq):
            if cp in keep:
                continue
            p5[width_offset + 2 * i:width_offset + 2 * i + 2] = b"\x00\x00"
            p5[bitmap_offset + glyph_size * i:bitmap_offset + glyph_size * (i + 1)] = (
                b"\x00" * glyph_size
            )
            blanked += 1
            total_blanked += glyph_size + 2
        print(
            f"JNFR #{index} @0x{font['offset']:05X}: count={font['count']} "
            f"glyph_size={glyph_size} blanked={blanked} kept={font['count'] - blanked}"
        )

    print(f"total bytes zeroed: {total_blanked}")

    def changed(lo: int, hi: int) -> int:
        return sum(1 for i in range(lo, hi) if p5[i] != original[i])

    probes = (
        (0x00000, 0x02000, "P5 头部 0x0000-0x2000"),
        (0x02A1C, 0x02B00, "P5+0x2A1C"),
        (0x02C68, 0x02D00, "P5+0x2C68"),
        (0x27660, 0x2BC62, "旧工具改过的 0x27660-0x2BC62"),
    )
    for lo, hi, name in probes:
        print(f"  changed {name}: {changed(lo, hi)} bytes")

    open(out_path, "wb").write(p5)
    print(f"wrote {out_path} ({len(p5)} bytes, length unchanged={len(p5) == len(original)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
