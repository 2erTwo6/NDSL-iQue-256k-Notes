#!/usr/bin/env bash
#
# Variant build: 256 KiB iQue Chinese firmware, but with the ARM7 boot code (P2)
# taken from the target console's own 256 KiB dump.
#
# Why:
#   The SPI firmware flash is owned by the ARM7 side of the firmware, and every
#   one of the firmware's SPI register accesses (0x040001C0 / 0x040001C2) lives
#   in P2 ("arm7_boot_code").  P1, P3 and P4 contain none.
#
#   On a real iQue DS (512 KiB flash, ST M25PE40) the user-settings block sits at
#   0x7FE00 and the entire last 64 KiB sector (0x70000..0x80000) is blank, because
#   P5 ends at 0x30768 + 0x29A34 = 0x5A19C.  The iQue firmware can therefore erase
#   that whole sector whenever it saves settings.
#
#   On this 256 KiB port the settings block must live at 0x3FE00, i.e. inside the
#   last 64 KiB sector (0x30000..0x40000) - and that sector holds *all* of P5
#   (0x30768..0x3F983).  The iQue build was never written for the DS Lite's flash
#   chip (ST M35PE20), and the erase opcodes the two ST families share do not mean
#   the same thing: on the M25PE40 "erases a small subsector" is "erase 64 KiB" on
#   the M35PE20.  Saving the settings therefore wipes the Chinese font/text data
#   and the console stops right after power-on (white screens).
#
#   Emulators do not model that erase semantics, which is why this image boots
#   perfectly in melonDS but not on hardware.
#
#   Swapping in the target console's own P2 gives the flash the driver it was
#   written for, while the ARM9 side (P1 = Chinese UI boot, P5 = Chinese
#   font/text data) stays iQue.
#
# Required tools:
#   dsfwtool  (https://github.com/Wokann/dsfwtool)
#
# The script deliberately requires the user to supply their own firmware dumps.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${BUILD_DIR:-$ROOT/build}"
DIST="${DIST_DIR:-$ROOT/dist}"

DSFWTOOL="${DSFWTOOL:-dsfwtool}"
IQ_FW="${IQ_FW:-$ROOT/网友分享的神游DSL固件/idsl-fw.bin}"
TARGET_FW="${TARGET_FW:-$ROOT/从我的日版机DSL上提取的系统/FW001656B0043F/firmware.bin}"
OUTPUT="${OUTPUT:-$DIST/idsl-256k-chs-p2jp.bin}"

if ! command -v "$DSFWTOOL" >/dev/null 2>&1; then
    echo "dsfwtool not found; build it from https://github.com/Wokann/dsfwtool" >&2
    echo "or set DSFWTOOL=/path/to/dsfwtool" >&2
    exit 1
fi

for f in "$IQ_FW" "$TARGET_FW"; do
    [[ -f "$f" ]] || { echo "missing input: $f" >&2; exit 1; }
done

mkdir -p "$BUILD" "$DIST"

# The inputs consumed below are produced by scripts/build_firmware.sh; build them
# if they are not there yet.
if [[ ! -f "$BUILD/header_iq_256k.bin" || ! -f "$BUILD/target_p2.enc" ]]; then
    echo "intermediate files missing, running scripts/build_firmware.sh first"
    DSFWTOOL="$DSFWTOOL" IQ_FW="$IQ_FW" TARGET_FW="$TARGET_FW" \
        "$ROOT/scripts/build_firmware.sh"
fi

echo "[1/4] decrypt the target console's P2 (MACh key)"
# -decrypt without -uncomp keeps the component compressed: no re-compression is
# involved, so the stream stays byte-identical to what the console shipped with.
"$DSFWTOOL" -p2 -decrypt "$BUILD/target_p2.enc" \
    -h "$BUILD/target_header.bin" \
    -o "$BUILD/target_p2.comp"

echo "[2/4] re-encrypt it with the iQue MACi key"
# The boot code decrypts P1/P2 with a key selected by fw_identifier, so the
# target's P2 stream must be re-encrypted under MACi to match this header.
"$DSFWTOOL" -p2 -encrypt "$BUILD/target_p2.comp" \
    -h "$BUILD/header_iq_256k.bin" \
    -o "$BUILD/target_p2.maci.enc"

echo "[3/4] assemble (iQue P1 + target P2 + iQue P3/P4/P5)"
"$DSFWTOOL" -c "$OUTPUT" \
    -h "$BUILD/header_iq_256k.bin" \
    -p1 --offset 0x000280 "$BUILD/ique_p1.enc" \
    -p2 --offset 0x00F750 "$BUILD/target_p2.maci.enc" \
    -p3 -comp --offset 0x017CB0 "$BUILD/ique_p3.bin" \
    -p4 -comp --offset 0x0277C0 "$BUILD/ique_p4.bin" \
    -p5 -comp --offset 0x030768 "$BUILD/ique_p5_subset.bin" \
    -b "$TARGET_FW" \
    -s 256K

echo "[4/4] restore iQue pre-P1 data"
python3 "$ROOT/scripts/patch_pre_p1.py" "$IQ_FW" "$OUTPUT" --p1-offset 0x280

echo
echo "Built: $OUTPUT"
"$DSFWTOOL" -i "$OUTPUT"
sha256sum "$OUTPUT"
