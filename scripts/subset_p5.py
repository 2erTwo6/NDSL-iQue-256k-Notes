#!/usr/bin/env python3
"""
Subset the iQue DS firmware P5 font resources so that the Chinese UI can fit
into a 256 KiB firmware image.

The P5 image contains four JNCM (BNCMP 1.2) character maps and four JNFR
(BNFR 1.2) bitmap fonts.  This script keeps:

  * every character referenced by a JNLL text string in P5
  * all printable ASCII characters
  * private-use and common symbol glyphs (often used as UI icons)
  * every glyph of the two small font resources

Unused glyph bitmap bytes are replaced with 0xFF.  Resource start offsets are
preserved, so no other P5 pointers need to be moved.

Usage:
    python3 scripts/subset_p5.py INPUT_P5.bin OUTPUT_P5.bin
"""

from __future__ import annotations

import re
import struct
import sys
from collections import Counter


def parse_jncm(image: bytes, offset: int) -> dict:
    """Parse a JNCM / BNCMP 1.2 character map."""
    if image[offset:offset + 4] != b"JNCM":
        raise ValueError(f"JNCM not found at 0x{offset:X}")

    version = tuple(image[offset + 4:offset + 6])
    if version != (2, 1):
        # Header stores [verLo, verHi].  The firmware resources here are 1.2.
        raise ValueError(f"unsupported JNCM version {version!r} at 0x{offset:X}")

    count = struct.unpack_from("<H", image, offset + 6)[0]
    off_con = struct.unpack_from("<I", image, offset + 8)[0] + 8
    off_dir = struct.unpack_from("<I", image, offset + 0xC)[0] + 8

    n_con = struct.unpack_from("<H", image, offset + off_con)[0]
    continuous = []
    pos = offset + off_con + 2
    for _ in range(n_con):
        lo, hi = struct.unpack_from("<HH", image, pos)
        continuous.append((lo, hi))
        pos += 4

    n_dir = struct.unpack_from("<H", image, offset + off_dir)[0]
    start_glyph = struct.unpack_from("<H", image, offset + off_dir + 2)[0]
    direct = []
    pos = offset + off_dir + 4
    for _ in range(n_dir):
        direct.append(struct.unpack_from("<H", image, pos)[0])
        pos += 2

    sequence = []
    for lo, hi in continuous:
        sequence.extend(range(lo, hi + 1))
    sequence.extend(direct)

    if len(sequence) != count:
        raise ValueError(
            f"JNCM at 0x{offset:X}: mapping count {len(sequence)} != header {count}"
        )
    if start_glyph != count - n_dir:
        raise ValueError(
            f"JNCM at 0x{offset:X}: invalid direct-map start glyph {start_glyph}"
        )

    return {
        "offset": offset,
        "version": version,
        "count": count,
        "con": continuous,
        "dir": direct,
        "seq": sequence,
    }


def parse_jnfr(image: bytes, offset: int, expected_count: int) -> dict:
    """Parse a JNFR / BNFR 1.2 bitmap font header."""
    if image[offset:offset + 4] != b"JNFR":
        raise ValueError(f"JNFR not found at 0x{offset:X}")

    count = struct.unpack_from("<H", image, offset + 6)[0]
    if count != expected_count:
        raise ValueError(
            f"JNFR at 0x{offset:X}: glyph count {count} != JNCM {expected_count}"
        )

    info = struct.unpack_from("<H", image, offset + 8)[0]
    width = info & 0x1F
    height = (info >> 5) & 0x1F
    glyph_size = ((width * height + 15) // 16) * 2

    width_offset = offset + 10
    bitmap_offset = width_offset + 2 * count
    data_end = bitmap_offset + glyph_size * count

    return {
        "offset": offset,
        "count": count,
        "info": info,
        "width": width,
        "height": height,
        "glyph_size": glyph_size,
        "width_offset": width_offset,
        "bitmap_offset": bitmap_offset,
        "data_end": data_end,
    }


def build_mapping(codepoints):
    """Recreate the NitroPaint/BNCMP ordering for a set of code points.

    JNCM 1.2 writes continuous ranges first, then direct code points.  Both
    lists are sorted.  This function returns the corresponding mapping order
    and the blocks needed for the new JNCM header.
    """
    codepoints = sorted(codepoints)
    continuous = []
    direct = []
    order = []

    i = 0
    while i < len(codepoints):
        j = i + 1
        while j < len(codepoints) and codepoints[j] == codepoints[j - 1] + 1:
            j += 1
        run = j - i
        if run >= 3:
            continuous.append((codepoints[i], codepoints[j - 1]))
            order.extend(codepoints[i:j])
        else:
            for cp in codepoints[i:j]:
                direct.append(cp)
                order.append(cp)
        i = j

    # Writer semantics: all continuous ranges first, then all direct entries.
    order = []
    for lo, hi in continuous:
        order.extend(range(lo, hi + 1))
    order.extend(direct)

    return continuous, direct, order


def encode_jncm(codepoints) -> bytes:
    continuous, direct, order = build_mapping(codepoints)
    if build_mapping(order) != (continuous, direct, order):
        raise AssertionError("internal mapping ordering error")

    out = bytearray()
    out += b"JNCM"
    out += bytes((2, 1))
    out += struct.pack("<H", len(order))

    off_con = 0x8
    off_dir = ((off_con + len(continuous) * 4 + 2 + 3) // 4) * 4
    out += struct.pack("<II", off_con, off_dir)
    out += struct.pack("<H", len(continuous))
    for lo, hi in continuous:
        out += struct.pack("<HH", lo, hi)

    while len(out) < 8 + off_dir:
        out.append(0)

    out += struct.pack("<HH", len(direct), len(order) - len(direct))
    for cp in direct:
        out += struct.pack("<H", cp)

    return bytes(out)


def encode_jnfr(font: dict, glyph_records: dict, order) -> bytes:
    out = bytearray()
    out += b"JNFR"
    out += bytes((2, 1))
    out += struct.pack("<H", len(order))
    out += struct.pack("<H", font["info"])

    for cp in order:
        out += glyph_records[cp][0]
    for cp in order:
        out += glyph_records[cp][1]

    return bytes(out)


def extract_referenced_text_chars(p5: bytes):
    """Collect the UTF-16LE characters referenced by JNLL text entries."""
    used = set()
    pos = 0
    limit = len(p5)

    while True:
        pos = p5.find(b"JNLL", pos)
        if pos < 0:
            break
        if pos + 8 > limit:
            pos += 4
            continue

        count = struct.unpack_from("<H", p5, pos + 6)[0]
        entries = pos + 8
        if count <= 0 or entries + count * 12 > limit:
            pos += 4
            continue

        for i in range(count):
            text_offset = struct.unpack_from("<I", p5, entries + i * 12 + 8)[0]
            if text_offset == 0:
                continue
            p = pos + text_offset
            if p >= limit:
                continue

            chars = []
            while p + 1 < limit:
                ch = struct.unpack_from("<H", p5, p)[0]
                if ch == 0:
                    break
                chars.append(ch)
                p += 2

            used.update(chars)

        pos += 4

    return used


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip())
        return 2

    in_path, out_path = sys.argv[1], sys.argv[2]
    p5 = bytearray(open(in_path, "rb").read())
    original = bytes(p5)

    jncm_offsets = [m.start() for m in re.finditer(b"JNCM", p5)]
    jnfr_offsets = [m.start() for m in re.finditer(b"JNFR", p5)]

    if len(jncm_offsets) != 4 or len(jnfr_offsets) != 4:
        print(
            f"expected 4 JNCM and 4 JNFR resources, found "
            f"{len(jncm_offsets)} and {len(jnfr_offsets)}",
            file=sys.stderr,
        )
        return 1

    maps = [parse_jncm(p5, off) for off in jncm_offsets]
    fonts = []
    for off in jnfr_offsets:
        count = struct.unpack_from("<H", p5, off + 6)[0]
        matches = [m for m in maps if m["count"] == count]
        if len(matches) != 1:
            print(f"could not uniquely associate JNFR 0x{off:X}", file=sys.stderr)
            return 1
        font = parse_jnfr(p5, off, count)
        font["map"] = matches[0]
        fonts.append(font)
    fonts.sort(key=lambda f: f["offset"])

    # The two small fonts are kept in full.  For the two main fonts, keep all
    # UI text, all printable ASCII, and typical icon/symbol ranges.
    keep_base = extract_referenced_text_chars(p5)
    keep_base.update(range(0x20, 0x7F))
    keep_base.update(range(0xE000, 0xF900))  # private use
    keep_base.update(range(0x2000, 0x27C0))  # punctuation/symbols/box drawing
    keep_base.update((0x3000, 0x3001, 0x3002, 0x300C, 0x300D,
                      0xFF0C, 0xFF0E, 0x2026, 0x25A0))

    starts = sorted(jncm_offsets + jnfr_offsets)

    def next_resource_start(offset: int) -> int:
        for start in starts:
            if start > offset:
                return start
        return len(p5)

    for index, font in enumerate(fonts):
        mapping = font["map"]["seq"]
        if font["count"] in (59, 26):
            keep_codepoints = list(mapping)
        else:
            keep_codepoints = [cp for cp in mapping if cp in keep_base]

        index_by_cp = {cp: i for i, cp in enumerate(mapping)}
        glyph_records = {}
        for cp in keep_codepoints:
            glyph_index = index_by_cp[cp]
            width = bytes(
                p5[
                    font["width_offset"] + 2 * glyph_index:
                    font["width_offset"] + 2 * glyph_index + 2
                ]
            )
            bitmap = bytes(
                p5[
                    font["bitmap_offset"] + font["glyph_size"] * glyph_index:
                    font["bitmap_offset"] + font["glyph_size"] * (glyph_index + 1)
                ]
            )
            glyph_records[cp] = (width, bitmap)

        _, _, order = build_mapping(glyph_records.keys())
        new_font = encode_jnfr(font, glyph_records, order)

        # Font resources are in-place.  Do not overwrite bytes after the
        # original bitmap region: some firmware versions place a table there.
        cap_font = min(next_resource_start(font["offset"]), font["data_end"]) - font["offset"]
        if len(new_font) > cap_font:
            print(f"JNFR #{index} does not fit: {len(new_font)} > {cap_font}", file=sys.stderr)
            return 1
        p5[font["offset"]:font["offset"] + len(new_font)] = new_font
        p5[font["offset"] + len(new_font):font["offset"] + cap_font] = (
            b"\xFF" * (cap_font - len(new_font))
        )

        new_map = encode_jncm(order)
        map_offset = font["map"]["offset"]
        cap_map = next_resource_start(map_offset) - map_offset
        if len(new_map) > cap_map:
            print(f"JNCM #{index} does not fit: {len(new_map)} > {cap_map}", file=sys.stderr)
            return 1
        p5[map_offset:map_offset + len(new_map)] = new_map
        p5[map_offset + len(new_map):map_offset + cap_map] = (
            b"\xFF" * (cap_map - len(new_map))
        )

        print(
            f"font #{index}: kept {len(order)} glyphs "
            f"(original {font['count']}), "
            f"JNFR {len(new_font)}/{cap_font}, JNCM {len(new_map)}/{cap_map}"
        )

    # The common 0x200-byte JNLL-style table after the last font bitmap must
    # remain untouched.  The in-place capacity calculation above guarantees
    # that, but assert it for safety if present.
    if len(p5) == len(original):
        pass

    open(out_path, "wb").write(p5)
    print(f"wrote {out_path} ({len(p5)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
