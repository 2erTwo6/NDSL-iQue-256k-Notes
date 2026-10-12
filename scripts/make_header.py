#!/usr/bin/env python3
"""
Create a 256 KiB iQue-style primary firmware header.

Inputs:
  --target-header : exported 0x180-byte header from the target 256 KiB dump
  --ique-header   : exported 0x180-byte header from the 512 KiB iQue dump
  --output        : output header path

The output keeps the iQue identifier/console type and the iQue boot-code
encryption key, while preserving the target console's Wi-Fi calibration and
MAC-address bytes.  The flash size and user-settings pointer are adjusted to
256 KiB.
"""

from __future__ import annotations

import argparse
import struct


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-header", required=True)
    parser.add_argument("--ique-header", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    target = bytearray(open(args.target_header, "rb").read())
    ique = bytearray(open(args.ique_header, "rb").read())

    if len(ique) < 0x180 or len(target) < 0x180:
        raise SystemExit("headers must be at least 0x180 bytes")

    header = bytearray(ique[:0x180])
    # 0x2A..0x17F contains Wi-Fi calibration, RF/BB settings and MAC address.
    header[0x2A:0x180] = target[0x2A:0x180]

    # 256 KiB flash, user settings/Wi-Fi tail at the standard 256 KiB location.
    struct.pack_into("<H", header, 0x14, 0x2CB2)
    struct.pack_into("<H", header, 0x20, 0x7FC0)

    open(args.output, "wb").write(header)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
