#!/usr/bin/env bash
#
# Build a 256 KiB DS Lite firmware by porting the iQue DS Chinese UI from a
# 512 KiB iQue firmware dump and subsetting its P5 fonts.
#
# Required tools:
#   dsfwtool  (https://github.com/Wokann/dsfwtool)
#
# The script deliberately requires the user to supply their own firmware
# dumps.  Do not redistribute official firmware images or dumps containing
# a console's private Wi-Fi/MAC/user settings.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${BUILD_DIR:-$ROOT/build}"
DIST="${DIST_DIR:-$ROOT/dist}"

DSFWTOOL="${DSFWTOOL:-dsfwtool}"
IQ_FW="${IQ_FW:-$ROOT/网友分享的神游DSL固件/idsl-fw.bin}"
TARGET_FW="${TARGET_FW:-$ROOT/从我的日版机DSL上提取的系统/FW001656B0043F/firmware.bin}"
OUTPUT="${OUTPUT:-$DIST/idsl-256k-chs.bin}"

if ! command -v "$DSFWTOOL" >/dev/null 2>&1; then
    echo "dsfwtool not found; build it from https://github.com/Wokann/dsfwtool" >&2
    echo "or set DSFWTOOL=/path/to/dsfwtool" >&2
    exit 1
fi

if [[ ! -f "$IQ_FW" ]]; then
    echo "iQue 512 KiB firmware not found: $IQ_FW" >&2
    echo "set IQ_FW=/path/to/idsl-fw.bin" >&2
    exit 1
fi

if [[ ! -f "$TARGET_FW" ]]; then
    echo "target 256 KiB firmware dump not found: $TARGET_FW" >&2
    echo "set TARGET_FW=/path/to/firmware.bin" >&2
    exit 1
fi

mkdir -p "$BUILD" "$DIST"

echo "[1/5] unpack iQue firmware components"
"$DSFWTOOL" -x "$IQ_FW" \
    -h "$BUILD/ique_header.bin" \
    -p1 "$BUILD/ique_p1.enc" \
    -p2 "$BUILD/ique_p2.enc" \
    -p3 -uncomp "$BUILD/ique_p3.bin" \
    -p4 -uncomp "$BUILD/ique_p4.bin" \
    -p5 -uncomp "$BUILD/ique_p5.bin"

echo "[2/5] unpack target firmware header"
"$DSFWTOOL" -x "$TARGET_FW" \
    -h "$BUILD/target_header.bin" \
    -p1 "$BUILD/target_p1.enc" \
    -p2 "$BUILD/target_p2.enc" \
    -p3 -uncomp "$BUILD/target_p3.bin" \
    -p4 -uncomp "$BUILD/target_p4.bin" \
    -p5 -uncomp "$BUILD/target_p5.bin"

echo "[3/5] create 256 KiB iQue header"
python3 "$ROOT/scripts/make_header.py" \
    --target-header "$BUILD/target_header.bin" \
    --ique-header "$BUILD/ique_header.bin" \
    --output "$BUILD/header_iq_256k.bin"

echo "[4/5] subset P5 fonts"
python3 "$ROOT/scripts/subset_p5.py" \
    "$BUILD/ique_p5.bin" \
    "$BUILD/ique_p5_subset.bin"

echo "[5/5] assemble firmware"
# Fixed offsets are chosen so that the larger iQue P1/P2 and the subset P5
# all fit in 256 KiB.  The final component layout is checked by dsfwtool.
"$DSFWTOOL" -c "$OUTPUT" \
    -h "$BUILD/header_iq_256k.bin" \
    -p1 --offset 0x000200 "$BUILD/ique_p1.enc" \
    -p2 --offset 0x00F6D0 "$BUILD/ique_p2.enc" \
    -p3 -comp --offset 0x017C30 "$BUILD/ique_p3.bin" \
    -p4 -comp --offset 0x027740 "$BUILD/ique_p4.bin" \
    -p5 -comp --offset 0x0306E8 "$BUILD/ique_p5_subset.bin" \
    -b "$TARGET_FW" \
    -s 256K

echo
echo "Built: $OUTPUT"
sha256sum "$OUTPUT"
