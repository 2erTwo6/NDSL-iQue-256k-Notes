#!/usr/bin/env python3
"""
Copy the iQue pre-P1 data region into an assembled 256 KiB firmware image.

The 512 KiB iQue firmware dump stores a small 0x80-byte block at
0x000200..0x00027F before P1.  dsfwtool's firmware model only exports the
0x180-byte primary header and the P1..P5 components it knows about, so that
block is filled with 0xFF during reassembly.  The iQue boot code needs the
original bytes, and starting P1 at 0x000200 instead of preserving the block
produces the known "iQue logo flashes, then the screens stay white" hang.

This script must therefore run after dsfwtool has assembled the image.  It
copies SOURCE[0x200:p1_offset] to OUTPUT[0x200:p1_offset].

Usage:
    python3 scripts/patch_pre_p1.py SOURCE_FW OUTPUT_FW [--p1-offset 0x280]
"""

from __future__ import annotations

import argparse


DEFAULT_PRE_START = 0x200
DEFAULT_P1_OFFSET = 0x280


def parse_int(text: str) -> int:
    return int(text, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="original 512 KiB iQue firmware dump")
    parser.add_argument("output", help="assembled 256 KiB firmware image")
    parser.add_argument(
        "--pre-start",
        type=parse_int,
        default=DEFAULT_PRE_START,
        help=f"start of the unmodelled pre-P1 region (default: 0x{DEFAULT_PRE_START:X})",
    )
    parser.add_argument(
        "--p1-offset",
        type=parse_int,
        default=DEFAULT_P1_OFFSET,
        help=f"physical P1 start offset to preserve up to (default: 0x{DEFAULT_P1_OFFSET:X})",
    )
    args = parser.parse_args()

    if args.pre_start < 0 or args.p1_offset <= args.pre_start:
        raise SystemExit("invalid pre-P1 region boundaries")

    source = open(args.source, "rb").read()
    output = bytearray(open(args.output, "rb").read())

    if len(source) < args.p1_offset:
        raise SystemExit(
            f"source firmware is too small for pre-P1 region "
            f"0x{args.pre_start:X}..0x{args.p1_offset:X}"
        )
    if len(output) < args.p1_offset:
        raise SystemExit(
            f"output firmware is too small for pre-P1 region "
            f"0x{args.pre_start:X}..0x{args.p1_offset:X}"
        )

    region = source[args.pre_start:args.p1_offset]
    output[args.pre_start:args.p1_offset] = region
    open(args.output, "wb").write(output)

    print(
        f"copied pre-P1 data 0x{args.pre_start:06X}..0x{args.p1_offset:06X} "
        f"({len(region)} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
