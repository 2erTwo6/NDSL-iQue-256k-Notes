#!/usr/bin/env python3
"""NDSL (DS Lite) firmware toolkit -- rebuilt & focused on safe patching.

Layout of the retail 256 KiB image (offsets read from the firmware header):
    part1 @0x00200  ARM9 boot/main code   KEY1(Blowfish) + LZ77   -> RAM 0x02320000
    part2 @0x0CA20  ARM7 boot code        KEY1 + LZ77             -> RAM 0x037FA800
    part5 @0x14F18  GUI data/gfx/text     vpk (Huffman+LZ)        -> RAM 0x023A4760
    part3 @0x248D0  ARM9 GUI code (Thumb) vpk
    part4 @0x367C0  ARM7 wifi code        vpk
    0x3FA00 wifi APs (plain)   0x3FE00/0x3FF00 user settings (plain)

Checksums -- CRC-16, poly 0x8005 reflected (table 0xA001), stored little-endian:
    0x06 = crc(decompressed part1 ++ part2, init 0xFFFF)
    0x04 = crc(decompressed part3 ++ part4, init 0xFFFF)
    0x26 = crc(decompressed part5,          init 0xFFFF)
    0x2A = crc(fw[0x2C : 0x2C+len],         init 0x0000)
    user settings 0x72 = crc(block[0:0x70],  init 0xFFFF)   (stored in both copies)

Two hard-won rules baked in below:
  * LZ77: an overlapping match (length > displacement) MUST use an even displacement.
    Retail part1/part2 have 103/85 overlapping matches and zero odd ones; streams that
    violate this decode fine with a naive decoder but fail to boot on the console.
  * Prefer the nearest match on ties; with both rules the encoder reproduces the retail
    part1 stream byte-for-byte (md5 of the repacked image is unchanged for unpatched code).

Usage:
  ndsl_mod.py info    <fw> [--bios bios7]
  ndsl_mod.py verify  <fw> [--bios bios7]
  ndsl_mod.py extract <fw> -o <dir> [--bios bios7]
  ndsl_mod.py patch   <fw> -o <out> [--bios bios7] [--spec 'part1:0x0A0C=2348>1ae0']
                      [--preset hns-autoskip|hns-autoskip-240|hns-instant|hns-fade-instant]
"""
from __future__ import annotations
import argparse, os, struct, sys

MASK = 0xFFFFFFFF


# ------------------------------------------------------------------ checksums
def crc16(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


# ------------------------------------------------------------------ KEY1
class Key1:
    """KEY1 (Blowfish) per GBATEK; key table = bios7[0x30 : 0x30+0x1048]."""

    def __init__(self, bios7: bytes):
        if len(bios7) < 0x30 + 0x1048:
            raise ValueError("ARM7 BIOS too small for the KEY1 key table")
        self.base = list(struct.unpack_from("<1042I", bios7, 0x30))

    @staticmethod
    def _bswap(v: int) -> int:
        return struct.unpack(">I", struct.pack("<I", v & MASK))[0]

    def _crypt(self, kb, p0, p4, rng):
        y, x = p0, p4                      # y = first word, x = second word
        for i in rng:
            z = kb[i] ^ x
            x = kb[0x012 + ((z >> 24) & 0xFF)]
            x = (x + kb[0x112 + ((z >> 16) & 0xFF)]) & MASK
            x ^= kb[0x212 + ((z >> 8) & 0xFF)]
            x = (x + kb[0x312 + (z & 0xFF)]) & MASK
            x ^= y
            y = z
        return x, y

    def _enc(self, kb, a, b):
        x, y = self._crypt(kb, a, b, range(0x00, 0x10))
        return x ^ kb[0x10], y ^ kb[0x11]

    def _dec(self, kb, a, b):
        x, y = self._crypt(kb, a, b, range(0x11, 0x01, -1))
        return x ^ kb[0x01], y ^ kb[0x00]

    def _apply(self, kb, kc, wm):
        kc[1], kc[2] = self._enc(kb, kc[1], kc[2])
        kc[0], kc[1] = self._enc(kb, kc[0], kc[1])
        for i in range(0x12):
            kb[i] ^= self._bswap(kc[i % wm])
        s0 = s4 = 0
        for i in range(0, 0x412, 2):
            s0, s4 = self._enc(kb, s0, s4)
            kb[i], kb[i + 1] = s4, s0

    def keybuf(self, idcode: int, level: int = 2, byte_modulo: int = 0x0C):
        kb = list(self.base)
        wm = byte_modulo // 4
        kc = [idcode & MASK, (idcode >> 1) & MASK, (idcode << 1) & MASK]
        if level >= 1:
            self._apply(kb, kc, wm)
        if level >= 2:
            self._apply(kb, kc, wm)
        kc[1] = (kc[1] << 1) & MASK
        kc[2] = (kc[2] >> 1) & MASK
        if level >= 3:
            self._apply(kb, kc, wm)
        return kb

    def _run(self, data: bytes, kb, decrypt: bool) -> bytes:
        out = bytearray()
        for i in range(0, len(data) & ~7, 8):
            a, b = struct.unpack_from("<II", data, i)
            x, y = self._dec(kb, a, b) if decrypt else self._enc(kb, a, b)
            out += struct.pack("<II", x, y)
        return bytes(out)

    def decrypt(self, data: bytes, kb) -> bytes:
        return self._run(data, kb, True)

    def encrypt(self, data: bytes, kb) -> bytes:
        return self._run(data, kb, False)


# ------------------------------------------------------------------ LZ77
def lz77_decompress(data: bytes, max_size: int = 0x100000):
    hdr = struct.unpack_from("<I", data, 0)[0]
    if ((hdr >> 4) & 0xF) != 1:
        raise ValueError(f"not a type-1 LZ77 stream: {hdr:#010x}")
    size = hdr >> 8
    if not 0 < size <= max_size:
        raise ValueError(f"implausible size {size}")
    pos, out = 4, bytearray()
    while len(out) < size:
        flags = data[pos]
        pos += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                b0, b1 = data[pos], data[pos + 1]
                pos += 2
                ln = (b0 >> 4) + 3
                disp = (((b0 & 0xF) << 8) | b1) + 1
                if disp > len(out):
                    raise ValueError("back-reference before start of output")
                src = len(out) - disp
                for k in range(ln):
                    out.append(out[src + k])
            else:
                out.append(data[pos])
                pos += 1
    return bytes(out), pos


def lz77_compress(src: bytes, max_len: int = 18, window: int = 0x1000) -> bytes:
    """Retail-compatible encoder (nearest match on ties, even disp for overlaps)."""
    out = bytearray(struct.pack("<I", (len(src) << 8) | 0x10))
    n, i, head = len(src), 0, {}
    while i < n:
        fp = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            bl = bd = 0
            if i >= 1 and i + 2 < n:
                for cand in reversed(head.get(src[i:i + 3], ())):
                    d = i - cand
                    if d > window:
                        continue
                    l, ml = 0, min(max_len, n - i)
                    while l < ml and src[cand + l] == src[i + l]:
                        l += 1
                    if l > bl and not (l > d and d % 2):
                        bl, bd = l, d
            if bl >= 3:
                flags |= 0x80 >> bit
                e = ((bl - 3) << 12) | (bd - 1)
                out.append(e >> 8)
                out.append(e & 0xFF)
                for k in range(bl):
                    p = i + k
                    if p + 2 < n:
                        head.setdefault(src[p:p + 3], []).append(p)
                i += bl
            else:
                out.append(src[i])
                if i + 2 < n:
                    head.setdefault(src[i:i + 3], []).append(i)
                i += 1
        out[fp] = flags
    return bytes(out)


# ------------------------------------------------------------------ vpk
class _BR:
    __slots__ = ("d", "p", "bit", "byte")

    def __init__(self, d, p=0):
        self.d, self.p, self.bit, self.byte = d, p, 0, 0

    def read(self, k):
        r = 0
        for _ in range(k):
            if self.bit == 0:
                self.byte = self.d[self.p]
                self.p += 1
                self.bit = 8
            self.bit -= 1
            r = (r << 1) | ((self.byte >> self.bit) & 1)
        return r


class _BW:
    __slots__ = ("b", "byte", "bit")

    def __init__(self):
        self.b, self.byte, self.bit = bytearray(), 0, 0

    def w(self, k, v):
        for i in range(k):
            self.byte = ((self.byte << 1) | ((v >> (k - 1 - i)) & 1)) & 0xFF
            self.bit += 1
            if self.bit == 8:
                self.b.append(self.byte)
                self.byte, self.bit = 0, 0

    def pad4(self):
        if self.bit:
            self.b.append((self.byte << (8 - self.bit)) & 0xFF)
            self.byte, self.bit = 0, 0
        while len(self.b) % 4:
            self.b.append(0)


class _N:
    __slots__ = ("l", "r", "v")

    def __init__(self, l=None, r=None, v=None):
        self.l, self.r, self.v = l, r, v

    @property
    def leaf(self):
        return self.l is None and self.r is None


def _read_tree(bs, bitlen):
    if bs.read(1):
        return _N(_read_tree(bs, bitlen), _read_tree(bs, bitlen))
    return _N(v=bs.read(bitlen))


def vpk_decompress(src: bytes, off: int = 0) -> bytes:
    size = (src[off + 5] << 16) | (src[off + 6] << 8) | src[off + 7]
    off1 = struct.unpack_from(">I", src, off + 8)[0]
    bs0, root0 = _BR(src, off + 12), None
    root0 = _read_tree(bs0, 9)
    bs1 = _BR(src, off + off1)
    root1 = _read_tree(bs1, 11)
    out = bytearray()
    while len(out) < size:
        n = root0
        while not n.leaf:
            n = n.r if bs0.read(1) else n.l
        if n.v < 0x100:
            out.append(n.v)
        else:
            m = root1
            while not m.leaf:
                m = m.r if bs1.read(1) else m.l
            p = len(out) - m.v - 1
            for _ in range(n.v - 0x100 + 3):
                out.append(out[p])
                p += 1
    return bytes(out)


def _tree_codes(node, depth=0, path=0, out=None):
    if out is None:
        out = {}
    if node.leaf:
        out[node.v] = (depth, path)
    else:
        _tree_codes(node.l, depth + 1, path << 1, out)
        _tree_codes(node.r, depth + 1, (path << 1) | 1, out)
    return out


def _tree_save(node, bw, bitlen):
    if node.leaf:
        bw.w(1, 0)
        bw.w(bitlen, node.v)
        return
    bw.w(1, 1)
    _tree_save(node.l, bw, bitlen)
    _tree_save(node.r, bw, bitlen)


def _huff(freq):
    import heapq
    heap = [(w, i, _N(v=i)) for i, w in enumerate(freq) if w]
    if not heap:
        raise ValueError("empty frequency table")
    heapq.heapify(heap)
    if len(heap) == 1:
        return heap[0][2]
    seq = 0
    while len(heap) > 1:
        w1, _, n1 = heapq.heappop(heap)
        w2, _, n2 = heapq.heappop(heap)
        seq += 1
        heapq.heappush(heap, (w1 + w2, len(freq) + seq, _N(n1, n2)))
    return heap[0][2]


def vpk_compress(src: bytes, window: int = 0x800, max_len: int = 0x102) -> bytes:
    """vpk encoder. NOTE: ~6% worse than the retail compressor, so GUI edits should
    stay size-neutral or parts must be relocated (offsets + checksums)."""
    n, i, head, toks = len(src), 0, {}, []
    while i < n:
        bl = bd = 0
        if i >= 1 and i + 2 < n:
            for cand in reversed(head.get(src[i:i + 3], ())):
                d = i - cand
                if d > window:
                    continue
                l, ml = 0, min(max_len, n - i)
                while l < ml and src[cand + l] == src[i + l]:
                    l += 1
                if l > bl:
                    bl, bd = l, d
        if bl >= 3:
            toks.append(("m", bd, bl))
            for k in range(bl):
                p = i + k
                if p + 2 < n:
                    head.setdefault(src[p:p + 3], []).append(p)
            i += bl
        else:
            toks.append(("l", src[i]))
            if i + 2 < n:
                head.setdefault(src[i:i + 3], []).append(i)
            i += 1
    f0, f1 = [0] * 0x200, [0] * 0x800
    for t in toks:
        if t[0] == "l":
            f0[t[1]] += 1
        else:
            f1[t[1] - 1] += 1
            f0[t[2] - 3 + 0x100] += 1
    t0, t1 = _huff(f0), _huff(f1)
    c0, c1 = _tree_codes(t0), _tree_codes(t1)
    b0, b1 = _BW(), _BW()
    _tree_save(t0, b0, 9)
    _tree_save(t1, b1, 11)
    for t in toks:
        if t[0] == "l":
            d, p = c0[t[1]]
            b0.w(d, p)
        else:
            d, p = c1[t[1] - 1]
            b1.w(d, p)
            d, p = c0[t[2] - 3 + 0x100]
            b0.w(d, p)
    b0.pad4()
    b1.pad4()
    total = 12 + len(b0.b) + len(b1.b)
    head = bytearray(12)
    head[0:3] = (total * 4).to_bytes(4, "little")[0:3]
    head[3] = head[4] = 0x80
    head[5:8] = len(src).to_bytes(4, "big")[1:4]
    head[8:12] = (12 + len(b0.b)).to_bytes(4, "big")
    return bytes(head) + bytes(b0.b) + bytes(b1.b)


# ------------------------------------------------------------------ firmware
class Firmware:
    def __init__(self, data: bytes, bios7: bytes | None = None):
        self.data = bytearray(data)
        self.bios7 = bios7
        self.boot, self.gui, self.comp = {}, {}, {}
        self.parse()

    @classmethod
    def load(cls, path, bios=None):
        return cls(open(path, "rb").read(), open(bios, "rb").read() if bios else None)

    def u16(self, o):
        return struct.unpack_from("<H", self.data, o)[0]

    def set_u16(self, o, v):
        struct.pack_into("<H", self.data, o, v & 0xFFFF)

    @property
    def idcode(self):
        return struct.unpack_from("<I", self.data, 0x08)[0]

    @property
    def ident(self):
        return bytes(self.data[0x08:0x0C])

    def parse(self):
        sh = self.shift = self.u16(0x14)
        self.s = [(sh >> (3 * i)) & 7 for i in range(4)]
        self.chip_kb = ((sh >> 12) & 0xF) * 128
        self.off = {
            "part1": self.u16(0x0C) << (2 + self.s[0]),
            "part2": self.u16(0x10) << (2 + self.s[2]),
            "part3": self.u16(0x00) * 8,
            "part4": self.u16(0x02) * 8,
            "part5": self.u16(0x16) * 8,
        }
        self.ram = {
            "part1": 0x2800000 - (self.u16(0x0E) << (2 + self.s[1])),
            "part2": 0x3810000 - (self.u16(0x12) << (2 + self.s[3])),
        }
        self.us_off = self.u16(0x20) * 8

    def order(self):
        return sorted(("part1", "part2", "part5", "part3", "part4"), key=lambda n: self.off[n])

    def slot(self, name):
        o = self.off[name]
        nxt = [self.off[n] for n in self.order() if self.off[n] > o]
        return (nxt[0] if nxt else 0x3FA00) - o

    # -- decode
    def decode_boot(self):
        if self.bios7 is None:
            raise RuntimeError("need biosnds7.rom for KEY1")
        k = Key1(self.bios7)
        kb = k.keybuf(self.idcode, 2, 0x0C)
        for name in ("part1", "part2"):
            o = self.off[name]
            plain = k.decrypt(bytes(self.data[o:o + 0x20000]), kb)
            raw, used = lz77_decompress(plain)
            self.boot[name] = raw
            self.comp[name] = used
        return self.boot

    def decode_gui(self):
        for name in ("part3", "part4", "part5"):
            o = self.off[name]
            self.gui[name] = vpk_decompress(bytes(self.data), o)
            self.comp[name] = (self.data[o] | self.data[o + 1] << 8 | self.data[o + 2] << 16) // 4
        return self.gui

    # -- repack
    def repack_boot(self, boot):
        k = Key1(self.bios7)
        kb = k.keybuf(self.idcode, 2, 0x0C)
        for name in ("part1", "part2"):
            if name not in boot:
                continue
            comp = lz77_compress(boot[name])
            enc = k.encrypt(comp + b"\x00" * (-len(comp) % 8), kb)
            o, lim = self.off[name], self.slot(name)
            if len(enc) > lim:
                raise SystemExit(f"{name} grew to {len(enc)} > slot {lim}: relocation needed")
            self.data[o:o + len(enc)] = enc
            self.data[o + len(enc):o + lim] = b"\xff" * (lim - len(enc))
            self.comp[name] = len(comp)

    def repack_gui(self, gui):
        for name in ("part3", "part4", "part5"):
            if name not in gui:
                continue
            blob = vpk_compress(gui[name])
            o, lim = self.off[name], self.slot(name)
            if len(blob) > lim:
                raise SystemExit(f"{name} grew to {len(blob)} > slot {lim}: relocation needed")
            self.data[o:o + len(blob)] = blob
            self.data[o + len(blob):o + lim] = b"\xff" * (lim - len(blob))
            self.comp[name] = len(blob)

    # -- checksums
    def crcs(self):
        if not self.boot:
            self.decode_boot()
        if not self.gui:
            self.decode_gui()
        wl = self.u16(0x2C)
        us = bytes(self.data[self.us_off:self.us_off + 0x100])
        return [
            ("boot code  0x06", self.u16(0x06), crc16(self.boot["part1"] + self.boot["part2"], 0xFFFF)),
            ("GUI code   0x04", self.u16(0x04), crc16(self.gui["part3"] + self.gui["part4"], 0xFFFF)),
            ("GUI data   0x26", self.u16(0x26), crc16(self.gui["part5"], 0xFFFF)),
            ("wifi calib 0x2A", self.u16(0x2A), crc16(bytes(self.data[0x2C:0x2C + wl]), 0x0000)),
            ("user settings  ", struct.unpack_from("<H", us, 0x72)[0], crc16(us[:0x70], 0xFFFF)),
        ]

    def fix_crcs(self):
        if not self.boot:
            self.decode_boot()
        if not self.gui:
            self.decode_gui()
        wl = self.u16(0x2C)
        self.set_u16(0x06, crc16(self.boot["part1"] + self.boot["part2"], 0xFFFF))
        self.set_u16(0x04, crc16(self.gui["part3"] + self.gui["part4"], 0xFFFF))
        self.set_u16(0x26, crc16(self.gui["part5"], 0xFFFF))
        self.set_u16(0x2A, crc16(bytes(self.data[0x2C:0x2C + wl]), 0x0000))
        for base in (self.us_off, self.us_off + 0x100):
            blk = bytearray(self.data[base:base + 0x100])
            struct.pack_into("<H", blk, 0x72, crc16(bytes(blk[:0x70]), 0xFFFF))
            self.data[base:base + 0x100] = blk

    def save(self, path):
        open(path, "wb").write(bytes(self.data))


# ------------------------------------------------------------------ presets
PRESETS = {
    # keep the retail 90-frame (approx 1.5 s) minimum stay + full fade animations,
    # but replace the "wait for a key/touch" check with "continue automatically"
    "hns-autoskip": "part1:0x0A0C=2348>1ae0",
    # same, with the minimum stay raised to 240 frames (approx 4 s)
    "hns-autoskip-240": "part1:0x0A0C=2348>1ae0,part1:0x0A08=5a28>f028",
    # skip the gap entirely (fade-in runs, then immediately proceeds) -- feels abrupt
    "hns-instant": "part1:0x0A0A=3add>1be0",
    # jump the stage chain straight to stage 2 and make its fade instant (abrupt visuals)
    "hns-fade-instant": "part1:0x0A0C=2348>1ae0,part1:0x1352=0021>0221,part1:0x089A=0f29>0029",
}


def parse_spec(spec):
    out = {}
    for item in spec.replace(" ", "").split(","):
        if not item:
            continue
        loc, _, val = item.partition("=")
        part, _, off = loc.partition(":")
        old, _, new = val.partition(">")
        out.setdefault(part, []).append((int(off, 16), bytes.fromhex(old) if old else None, bytes.fromhex(new)))
    return out


# ------------------------------------------------------------------ CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["info", "verify", "extract", "patch"])
    ap.add_argument("fw")
    ap.add_argument("--bios", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "factory", "biosnds7.rom"))
    ap.add_argument("-o", "--out")
    ap.add_argument("--spec", default="")
    ap.add_argument("--preset", choices=sorted(PRESETS))
    a = ap.parse_args()
    spec = a.spec or (PRESETS[a.preset] if a.preset else "")

    fw = Firmware.load(a.fw, a.bios if os.path.exists(a.bios) else None)

    if a.cmd == "info":
        print(f"identifier  {fw.ident!r}  idcode {fw.idcode:#010x}")
        print(f"console     0x{fw.data[0x1D]:02X}   build {fw.data[0x18:0x1D].hex()}   shift 0x{fw.shift:04X} (chip {fw.chip_kb} KiB)")
        print(f"settings    @0x{fw.us_off:05X}")
        if fw.bios7:
            fw.decode_boot()
        for n in fw.order():
            ram = f" ram 0x{fw.ram[n]:08X}" if n in fw.ram else ""
            print(f"  {n}  off 0x{fw.off[n]:05X}  slot {fw.slot(n):6d}  comp {fw.comp.get(n, 0):6d}  decomp {len(fw.boot.get(n) or fw.gui.get(n) or b''):6d}{ram}")
        for name, stored, comp in fw.crcs():
            print(f"  crc {name}: stored 0x{stored:04X}  computed 0x{comp:04X}  {'OK' if stored == comp else 'MISMATCH'}")
        return 0

    if a.cmd == "verify":
        bad = 0
        for name, stored, comp in fw.crcs():
            ok = stored == comp
            bad += not ok
            print(f"[{'OK ' if ok else 'BAD'}] {name}  stored 0x{stored:04X}  computed 0x{comp:04X}")
        print("all checks passed" if not bad else f"{bad} check(s) FAILED")
        return 1 if bad else 0

    if a.cmd == "extract":
        out = a.out or "extracted"
        os.makedirs(out, exist_ok=True)
        fw.decode_boot()
        fw.decode_gui()
        for n, b in list(fw.boot.items()) + list(fw.gui.items()):
            open(os.path.join(out, n + ".bin"), "wb").write(b)
            print(f"  {out}/{n}.bin  {len(b)}")
        open(os.path.join(out, "header.bin"), "wb").write(bytes(fw.data[:0x200]))
        open(os.path.join(out, "user_settings.bin"), "wb").write(bytes(fw.data[fw.us_off:fw.us_off + 0x100]))
        return 0

    # patch
    if not spec:
        raise SystemExit("patch needs --spec or --preset")
    if not a.out:
        raise SystemExit("patch needs -o")
    patches = parse_spec(spec)
    fw.decode_boot()
    if any(p in patches for p in ("part3", "part4", "part5")):
        fw.decode_gui()
    for part, items in patches.items():
        img = bytearray(fw.boot[part] if part in fw.boot else fw.gui[part])
        for off, old, new in items:
            if old is not None and img[off:off + len(old)] != old:
                raise SystemExit(f"{part}+0x{off:X}: expected {old.hex()}, found {img[off:off+len(old)].hex()}")
            print(f"  {part}+0x{off:X}: {img[off:off+len(new)].hex()} -> {new.hex()}")
            img[off:off + len(new)] = new
        (fw.boot if part in fw.boot else fw.gui)[part] = bytes(img)
    fw.repack_boot({k: v for k, v in fw.boot.items() if k in patches})
    if any(p in patches for p in ("part3", "part4", "part5")):
        fw.repack_gui({k: v for k, v in fw.gui.items() if k in patches})
    fw.parse()
    fw.boot, fw.gui = {}, {}
    fw.decode_boot()
    fw.decode_gui()
    fw.fix_crcs()
    fw.save(a.out)
    print(f"\nwrote {a.out}")
    v = Firmware.load(a.out, a.bios)
    bad = 0
    for name, stored, comp in v.crcs():
        ok = stored == comp
        bad += not ok
        print(f"  [{'OK ' if ok else 'BAD'}] {name}  stored 0x{stored:04X}  computed 0x{comp:04X}")
    ref = Firmware.load(a.fw, a.bios)
    diff = [i for i in range(len(ref.data)) if ref.data[i] != v.data[i]]
    if diff:
        print(f"  changed bytes: {len(diff)}  range 0x{min(diff):X}..0x{max(diff):X}")
    print("  self-check:", "PASS" if not bad else "FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
