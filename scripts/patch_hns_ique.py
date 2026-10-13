#!/usr/bin/env python3
"""Patch the 256 KiB iQue Chinese firmware so the boot health/safety screen is skipped.

This is the iQue counterpart of ndsl-hns-mod's P1 patches.  The retail (MACh/N)
patch offsets do NOT apply to the iQue (MACi) P1 - it is a different build - so
the two hooks used here were re-located in the iQue image:

    decompressed P1 offset   retail    iQue     contents
    stage1 "wait for key"    0x0A0C    0x0A48   23 48 (ldr r0,[pc,#0x8c]) -> 1A E0 (b +0x34)
    F "stage = 0"            0x1352    0x13AA   00 21 (movs r1,#0)        -> 02 21 (movs r1,#2)

The iQue warning-screen code is instruction-for-instruction identical to the
retail one, only relocated (+0x3C in the stage1 area, +0x58 around F), and the
stage variable lives at 0x02334320+0x2C instead of 0x023308E0+0x2C.  See
scripts/README-hns-ique.md.

Three modes:

  noshow    F starts the state machine at stage 2, so the warning page is never
            drawn (only the original stage-2 fade-out is left).  The 0x0A48 hook
            stays as a fallback for any other path that puts the machine back
            into stage 0/1.
  autoskip  only the 0x0A48 hook: the warning page still fades in and stays for
            the retail 90 frames (~1.5 s), then advances without user input.
  v4        the "complete removal": no warning-page data load, no warning stage,
            no 15-frame fade - F does not even read the warning screen resources.
            Three hooks (0x1394, 0x13AA, 0x08D6), two of which land *inside* LZ77
            matches, so the whole P1 stream has to be re-encoded (still with the
            same encoder that reproduces the original stream byte-for-byte).

noshow/autoskip are literal-only edits: re-encoding changes exactly the patched
literal bytes and nothing else, so there is no encoder risk at all.  v4 rewrites
the stream; the encoder is validated as a byte-exact reproduction of the iQue P1
first, and the re-encoded stream is additionally checked against the LZ77 rule
the console's loader enforces (an overlapping match must have an even
displacement).

Usage:
  patch_hns_ique.py IN.bin -o OUT.bin [--mode noshow|autoskip] [--bios biosnds7.rom]
"""
from __future__ import annotations
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ndsl-hns-mod", "tools"))
import ndsl_mod as nm  # noqa: E402

# patched in decompressed P1; (offset, expected old bytes, new bytes, description)
HOOK_AUTOSKIP = (0x0A48, bytes.fromhex("2348"), bytes.fromhex("1ae0"),
                 "stage1: wait for key/touch -> unconditional release")
HOOK_STAGE2 = (0x13AA, bytes.fromhex("0021"), bytes.fromhex("0221"),
               "F: initial stage 0 -> 2 (skip warning page)")
HOOK_NOLOAD = (0x1394, bytes.fromhex("04f0baf9"), bytes.fromhex("00e000e0"),
               "F: bl load-warning-screen -> b +0 / b +0 (never load its data)")
HOOK_NOFADE = (0x08D6, bytes.fromhex("0f29"), bytes.fromhex("0029"),
               "stage2: fade counter cmp 0xf -> cmp 0 (instant)")

# The classic Thumb NOP `c0 46` (mov r8,r8) also works here, but on the iQue P1
# the re-encoded stream then comes out 62673 bytes - one byte past the 62672-byte
# P1 slot (0x280..0xF750).  Two `b +0` instructions (00 e0 00 e0) are the same
# no-op and compress to exactly 62672, so the verified component layout does not
# have to be moved.
MODES = {
    "noshow": [HOOK_STAGE2, HOOK_AUTOSKIP],
    "autoskip": [HOOK_AUTOSKIP],
    "noload": [HOOK_NOLOAD, HOOK_STAGE2],
    "v4": [HOOK_NOLOAD, HOOK_STAGE2, HOOK_NOFADE],
}


def check_lz77_stream(stream: bytes) -> int:
    """Walk an LZ77 type-1 stream and enforce the console loader's overlap rule.

    Retail P1/P2 use overlapping matches but never with an odd displacement;
    streams that break this decode fine in software but do not boot.  Returns
    the number of overlapping matches seen.
    """
    size = struct.unpack_from("<I", stream, 0)[0] >> 8
    pos, out, overlaps = 4, 0, 0
    while out < size:
        if pos >= len(stream):
            raise SystemExit("LZ77 stream ran off the end")
        flags = stream[pos]
        pos += 1
        for bit in range(8):
            if out >= size:
                break
            if flags & (0x80 >> bit):
                b0, b1 = stream[pos], stream[pos + 1]
                pos += 2
                ln = (b0 >> 4) + 3
                disp = (((b0 & 0xF) << 8) | b1) + 1
                if disp > out:
                    raise SystemExit("LZ77 back-reference before start of output")
                if ln > disp:
                    overlaps += 1
                    if disp % 2:
                        raise SystemExit(f"overlapping match with ODD displacement "
                                         f"(len {ln}, disp {disp}) at output 0x{out:X}")
                out += ln
            else:
                out += 1
                pos += 1
    return overlaps


BIOS_CANDIDATES = (
    "材料/我的固件 FW001656B0043F/biosnds7.rom",
    "从我的日版机DSL上提取的系统/FW001656B0043F/biosnds7.rom",
    "ndsl-hns-mod/factory/biosnds7.rom",
)


def find_bios(explicit: str | None) -> str:
    if explicit:
        return explicit
    root = os.path.normpath(os.path.join(HERE, ".."))
    for cand in BIOS_CANDIDATES:
        path = os.path.join(root, cand)
        if os.path.exists(path):
            return path
    return os.path.join(root, BIOS_CANDIDATES[0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fw", help="input 256 KiB iQue image (e.g. dist/idsl-256k-chs-userp5.bin)")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--mode", choices=sorted(MODES), default="noshow")
    ap.add_argument("--bios", help="biosnds7.rom for the KEY1 key table "
                                   "(default: first of " + ", ".join(BIOS_CANDIDATES) + ")")
    a = ap.parse_args()
    a.bios = find_bios(a.bios)

    if not os.path.exists(a.bios):
        raise SystemExit(f"need biosnds7.rom for KEY1 (looked at {a.bios}); pass --bios")
    bios = open(a.bios, "rb").read()
    fw = nm.Firmware.load(a.fw, a.bios)
    if fw.ident != b"MACi":
        raise SystemExit(f"this patcher is for the iQue image (identifier MACi), got {fw.ident!r}")
    if len(fw.data) != 262144:
        raise SystemExit(f"expected a 256 KiB image, got {len(fw.data)} bytes")

    off = fw.off["part1"]
    key = nm.Key1(bios)
    kb = key.keybuf(fw.idcode, 2, 0x0C)
    on_image = bytes(fw.data[off:off + fw.slot("part1")])
    plain = key.decrypt(on_image, kb)
    boot, used = nm.lz77_decompress(plain)
    print(f"P1 @0x{off:05X}: effective stream {used} bytes, decompressed {len(boot)} bytes")

    # The whole point of the "zero encoder risk" claim: the encoder must be an
    # exact reproduction of Nintendo/iQue's stream before we patch anything.
    if nm.lz77_compress(boot) != plain[:used]:
        raise SystemExit("lz77_compress() does not reproduce the iQue P1 stream byte-for-byte; "
                         "refusing to re-encode (an in-place stream patch would be needed)")
    print("encoder check: lz77_compress() reproduces the original iQue P1 stream byte-for-byte  OK")

    img = bytearray(boot)
    for o, old, new, desc in MODES[a.mode]:
        found = img[o:o + len(old)]
        if found != old:
            raise SystemExit(f"P1+0x{o:04X}: expected {old.hex()}, found {found.hex()}")
        img[o:o + len(new)] = new
        print(f"  P1+0x{o:04X}: {old.hex()} -> {new.hex()}   {desc}")

    new_stream = nm.lz77_compress(bytes(img))
    if nm.lz77_decompress(new_stream)[0] != bytes(img):
        raise SystemExit("round-trip check failed")
    slot = fw.slot("part1")
    if len(new_stream) > slot:
        raise SystemExit(f"re-encoded stream {len(new_stream)} does not fit slot {slot}")
    diff = [i for i in range(min(len(new_stream), used)) if new_stream[i] != plain[i]]
    print(f"re-encoded stream: {len(new_stream)} bytes (was {used}), "
          f"{len(diff)} byte(s) differ from the original stream")
    print(f"  original stream overlap check: {check_lz77_stream(plain[:used])} overlapping match(es), all even  OK")
    print(f"  new stream overlap check:      {check_lz77_stream(new_stream)} overlapping match(es), all even  OK")

    # In-place style write-back: KEY1 is ECB, so only the 8-byte cipher blocks
    # whose plaintext actually changed are re-encrypted.  For noshow/autoskip
    # that is 1-2 blocks (the literal edits); for v4 it is most of the stream.
    new_plain = new_stream + plain[len(new_stream):]
    assert len(new_plain) == len(plain)
    enc = bytearray(on_image)
    blocks = sorted({i // 8 for i in range(len(plain)) if new_plain[i] != plain[i]})
    for b in blocks:
        enc[8 * b:8 * b + 8] = key.encrypt(bytes(new_plain[8 * b:8 * b + 8]), kb)
    fw.data[off:off + len(enc)] = enc
    print(f"re-encrypted {len(blocks)}/{len(plain) // 8} cipher block(s)")

    # header + component CRCs (0x06 covers the *decompressed* P1 ++ P2)
    fw.boot, fw.gui = {}, {}
    fw.decode_boot()
    fw.decode_gui()
    fw.fix_crcs()
    fw.save(a.out)

    v = nm.Firmware.load(a.out, a.bios)
    bad = 0
    for name, stored, comp in v.crcs():
        ok = stored == comp
        bad += not ok
        print(f"  [{'OK ' if ok else 'BAD'}] {name}  stored 0x{stored:04X}  computed 0x{comp:04X}")
    ref = nm.Firmware.load(a.fw, a.bios)
    d = [i for i in range(len(ref.data)) if ref.data[i] != v.data[i]]
    print(f"changed bytes vs input: {len(d)}  range 0x{min(d):X}..0x{max(d):X}" if d else "no change")
    pb = v.boot["part1"]
    for o, old, new, _ in MODES[a.mode]:
        assert pb[o:o + len(new)] == new, (hex(o), pb[o:o + len(new)].hex())
    print(f"wrote {a.out}  mode={a.mode}  self-check: {'PASS' if not bad else 'FAIL'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
