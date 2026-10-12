#!/usr/bin/env bash
#
# Build the 256 KiB iQue Chinese firmware that actually boots on DS Lite hardware.
#
# This is scripts/build_firmware.sh with one crucial change: the P5 component is
# compressed with the encoder from ndsl-hns-mod/tools/ndsl_mod.py instead of
# dsfwtool's.
#
# Why that matters
# ----------------
# dsfwtool's vpk (P345) encoder is byte-exact on Nintendo's *original* P3/P4
# streams, but on P5 - the one component this project actually modifies - its
# output is accepted by software decoders (melonDS, ndsl_mod.py) and rejected by
# the real console's decoder.  The symptom is a pure white screen with the
# backlights on and no logo; the same image boots fine in melonDS.  Encoding the
# identical decompressed P5 with ndsl_mod.py's encoder (60036 bytes instead of
# dsfwtool's 61979) boots on hardware.
#
# So: never re-encode P3/P4/P5 with dsfwtool.  Either pass Nintendo's original
# stream through untouched, or encode it with ndsl_mod.vpk_compress().
#
# Required tools:
#   dsfwtool  (https://github.com/Wokann/dsfwtool)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${BUILD_DIR:-$ROOT/build}"
DIST="${DIST_DIR:-$ROOT/dist}"

DSFWTOOL="${DSFWTOOL:-dsfwtool}"
IQ_FW="${IQ_FW:-$ROOT/网友分享的神游DSL固件/idsl-fw.bin}"
TARGET_FW="${TARGET_FW:-$ROOT/从我的日版机DSL上提取的系统/FW001656B0043F/firmware.bin}"
MODTOOL="${MODTOOL:-$ROOT/ndsl-hns-mod/tools/ndsl_mod.py}"
OUTPUT="${OUTPUT:-$DIST/idsl-256k-chs-userp5.bin}"

command -v "$DSFWTOOL" >/dev/null 2>&1 || {
    echo "dsfwtool not found; build it from https://github.com/Wokann/dsfwtool" >&2
    echo "or set DSFWTOOL=/path/to/dsfwtool" >&2
    exit 1
}
for f in "$IQ_FW" "$TARGET_FW" "$MODTOOL"; do
    [[ -f "$f" ]] || { echo "missing input: $f" >&2; exit 1; }
done

mkdir -p "$BUILD" "$DIST"

echo "[1/6] unpack iQue firmware components"
"$DSFWTOOL" -x "$IQ_FW" \
    -h "$BUILD/ique_header.bin" \
    -p1 "$BUILD/ique_p1.enc" \
    -p2 "$BUILD/ique_p2.enc" \
    -p3 -uncomp "$BUILD/ique_p3.bin" \
    -p4 -uncomp "$BUILD/ique_p4.bin" \
    -p5 -uncomp "$BUILD/ique_p5.bin"

echo "[2/6] unpack target firmware header"
"$DSFWTOOL" -x "$TARGET_FW" \
    -h "$BUILD/target_header.bin" \
    -p1 "$BUILD/target_p1.enc" \
    -p2 "$BUILD/target_p2.enc" \
    -p3 -uncomp "$BUILD/target_p3.bin" \
    -p4 -uncomp "$BUILD/target_p4.bin" \
    -p5 -uncomp "$BUILD/target_p5.bin"

echo "[3/6] create 256 KiB iQue header"
python3 "$ROOT/scripts/make_header.py" \
    --target-header "$BUILD/target_header.bin" \
    --ique-header "$BUILD/ique_header.bin" \
    --output "$BUILD/header_iq_256k.bin"

echo "[4/6] subset P5 fonts"
python3 "$ROOT/scripts/subset_p5.py" \
    "$BUILD/ique_p5.bin" \
    "$BUILD/ique_p5_subset.bin"

echo "[5/6] compress P5 with the ndsl_mod.py encoder"
# Not dsfwtool: see the note at the top of this file.
python3 - "$MODTOOL" "$BUILD/ique_p5_subset.bin" "$BUILD/ique_p5_subset.userp5.comp" <<'PY'
import sys, os
modtool, src_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.dirname(os.path.abspath(modtool)))
import ndsl_mod as nm

src = open(src_path, "rb").read()
data = nm.vpk_compress(src)
if nm.vpk_decompress(data) != src:
    raise SystemExit("vpk_compress round-trip check failed")
open(out_path, "wb").write(data)
print(f"  P5 {len(src)} -> {len(data)} bytes (round-trip OK)")
PY

echo "[6/6] assemble and restore the iQue pre-P1 data"
"$DSFWTOOL" -c "$OUTPUT" \
    -h "$BUILD/header_iq_256k.bin" \
    -p1 --offset 0x000280 "$BUILD/ique_p1.enc" \
    -p2 --offset 0x00F750 "$BUILD/ique_p2.enc" \
    -p3 -comp --offset 0x017CB0 "$BUILD/ique_p3.bin" \
    -p4 -comp --offset 0x0277C0 "$BUILD/ique_p4.bin" \
    -p5 --offset 0x030768 "$BUILD/ique_p5_subset.userp5.comp" \
    -b "$TARGET_FW" \
    -s 256K
python3 "$ROOT/scripts/patch_pre_p1.py" "$IQ_FW" "$OUTPUT" --p1-offset 0x280

echo
echo "Built: $OUTPUT"
"$DSFWTOOL" -i "$OUTPUT"
sha256sum "$OUTPUT"
