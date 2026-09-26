#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_font.py — 把 GNU Unifont 的 .hex 位图字库打包成设备用的紧凑二进制

为什么要 PC 侧预处理:
  Unifont 本身就是 1-bit 位图(ASCII 8x16、CJK 16x16),hex 里一个 bit 就是
  一个亮/暗像素。所以不需要任何字体光栅化,直接解析打包,像素零误差。
  设备上只做"查表 + framebuf.blit",不做 hex 解析、更不碰 TTF。

输出格式 UFB1(小端):
  --- Header 32 字节 ---
   0  char[4]  magic = b'UFB1'
   4  u8       version = 1
   5  u8       flags   bit0: 1=已反相(panel 语义, 1=白底)
   6  u8       cell_h   = 16
   7  u8       baseline = 14            (从顶部数,基线所在行)
   8  u8       half_adv = 8             (ASCII/半角步进)
   9  u8       full_adv = 16            (CJK/全角步进)
   10 u8       line_gap = 2             (建议行间距)
   11 u8       reserved = 0
   12 u32      cjk_first                (CJK 连续区首码点, 默认 0x4E00)
   16 u32      cjk_count
   20 u32      cjk_off                  (CJK 位图区文件偏移)
   24 u32      misc_count
   28 u32      misc_off                 (misc 索引表文件偏移)
  --- 数据段 ---
   misc 索引表: misc_count × 12 字节, 按码点升序
                u32 codepoint, u32 glyph_off, u32 advance
   CJK 位图区:  cjk_count × 32 字节, 索引 = cp - cjk_first
   misc 位图区: misc_count × 32 字节

  每个字形 = 16x16 单元, 32 字节, MONO_HLSB:
    每行 2 字节(MSB=最左像素), 共 16 行; 8 宽字形左对齐、右半为零。
    默认 natural 语义(1=墨/黑); 加 --panel 则整体取反(1=白底)。

用法:
  # 自动下载官方 hex 并生成(默认 natural 语义)
  python3 tools/build_font.py -o assets/fonts/unifont16.bin --preview /tmp/preview.bmp

  # 用本地 hex, 生成 panel 语义(配合"1=白底"的 framebuf 画布, 送显免取反)
  python3 tools/build_font.py unifont_all-18.0.01.hex.gz -o fonts.bin --panel

  # 只收常用字符, 体积更小
  python3 tools/build_font.py --charset mystrings.txt -o small.bin

授权: GNU Unifont 自 13.0.04 起双许可 = SIL OFL 1.1 + GPL-2.0+ (字体嵌入例外)。
      本项目按 SIL OFL 1.1 使用, 请随产品附带 OFL 许可与出处。
      https://unifoundry.com/unifont/  /  https://ftp.gnu.org/gnu/unifont/
"""

import argparse
import gzip
import os
import struct
import sys

UNIFONT_VERSION = "18.0.01"
UNIFONT_URL = (
    "https://ftp.gnu.org/gnu/unifont/unifont-%s/unifont_all-%s.hex.gz"
    % (UNIFONT_VERSION, UNIFONT_VERSION)
)

MAGIC = b"UFB1"
VERSION = 1
CELL_H = 16
BASELINE = 14
HALF_ADV = 8
FULL_ADV = 16
LINE_GAP = 2
GLYPH_BYTES = 32            # 16x16, 2 bytes/row
CJK_FIRST = 0x4E00
CJK_LAST = 0x9FFF

# 默认收录范围(全部落在 BMP 内)。CJK 大字块单独连续存放。
DEFAULT_RANGES = [
    (0x0020, 0x007E),   # ASCII 可打印
    (0x00A0, 0x00FF),   # Latin-1 补充
    (0x2010, 0x2027),   # 连字符/破折号/引号等
    (0x2030, 0x205E),   # 千分号/省略号/单双引号
    (0x20A0, 0x20BF),   # 货币符号
    (0x2190, 0x21FF),   # 箭头
    (0x2200, 0x22FF),   # 数学运算符
    (0x2500, 0x257F),   # 制表符
    (0x25A0, 0x25FF),   # 几何图形
    (0x2600, 0x26FF),   # 杂项符号
    (0x3000, 0x303F),   # CJK 标点
    (0x3040, 0x30FF),   # 平假名 / 片假名
    (0x4E00, 0x9FFF),   # CJK 统一表意文字(核心)
    (0xFF00, 0xFFEF),   # 全角字符
]


# --------------------------------------------------------------------------- #
# Unifont hex 解析
# --------------------------------------------------------------------------- #
def _open_text(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="ascii", errors="replace")
    return open(path, "r", encoding="ascii", errors="replace")


def parse_unifont_hex(path, wanted):
    """流式解析 unifont .hex, 返回 (glyphs, wide, n_lines)。

    glyphs: {codepoint: 32 字节 natural 位图}
    wide:   16 像素宽(全角)的码点集合 —— 由 hex 数据长度 64 判定, 不靠内容猜测

    hex 行格式:  '<码点十六进制>:<位图十六进制>'
      位图 32 位十六进制 = 16 字节 = 8 像素宽 (ASCII/半角)
      位图 64 位十六进制 = 32 字节 = 16 像素宽 (CJK/全角)
    统一转成 16x16 的 32 字节单元, 8 宽字形左对齐。
    """
    glyphs = {}
    wide = set()
    n_lines = 0
    with _open_text(path) as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            code_s, hex_s = line.split(":", 1)
            try:
                cp = int(code_s, 16)
            except ValueError:
                continue
            if wanted is not None and cp not in wanted:
                continue
            if cp > 0xFFFF:                      # 只收 BMP
                continue
            try:
                raw = bytes.fromhex(hex_s)
            except ValueError:
                continue
            n_lines += 1
            if len(raw) == 16:                   # 8x16
                cell = bytearray(GLYPH_BYTES)
                for r in range(CELL_H):
                    cell[r * 2] = raw[r]         # 左半, 右半保持 0
                glyphs[cp] = bytes(cell)
            elif len(raw) == 32:                 # 16x16
                glyphs[cp] = raw
                wide.add(cp)
            else:
                continue
    return glyphs, wide, n_lines


def invert_glyph(g):
    return bytes(b ^ 0xFF for b in g)


# --------------------------------------------------------------------------- #
# 打包
# --------------------------------------------------------------------------- #
def build(glyphs, wide, invert=False, line_gap=LINE_GAP):
    # --- CJK 连续区 ---
    cjk_count = CJK_LAST - CJK_FIRST + 1
    blank = (b"\x00" * GLYPH_BYTES)
    cjk_blank = invert_glyph(blank) if invert else blank
    cjk = bytearray(cjk_count * GLYPH_BYTES)
    cjk_hits = 0
    for i in range(cjk_count):
        g = glyphs.get(CJK_FIRST + i)
        if g is not None:
            cjk_hits += 1
            if invert:
                g = invert_glyph(g)
            cjk[i * GLYPH_BYTES:(i + 1) * GLYPH_BYTES] = g
        else:
            cjk[i * GLYPH_BYTES:(i + 1) * GLYPH_BYTES] = cjk_blank

    # --- 其余字符 → misc 表 ---
    misc_cps = sorted(cp for cp in glyphs if not (CJK_FIRST <= cp <= CJK_LAST))
    misc_table = bytearray()
    misc_bmps = bytearray()
    misc_off = 32
    cjk_off = misc_off + len(misc_cps) * 12
    misc_bmp_off = cjk_off + cjk_count * GLYPH_BYTES
    for i, cp in enumerate(misc_cps):
        g = glyphs[cp]
        g_off = misc_bmp_off + i * GLYPH_BYTES
        adv = FULL_ADV if cp in wide else HALF_ADV
        misc_table += struct.pack("<III", cp, g_off, adv)
        misc_bmps += (invert_glyph(g) if invert else g)

    flags = 0x01 if invert else 0x00
    header = struct.pack(
        "<4s8B5I",
        MAGIC, VERSION, flags, CELL_H, BASELINE, HALF_ADV, FULL_ADV, line_gap, 0,
        CJK_FIRST, cjk_count, cjk_off, len(misc_cps), misc_off,
    )
    assert len(header) == 32, len(header)
    blob = header + misc_table + cjk + misc_bmps
    stats = {
        "misc": len(misc_cps),
        "cjk": cjk_hits,
        "cjk_slots": cjk_count,
        "bytes": len(blob),
    }
    return blob, stats


# --------------------------------------------------------------------------- #
# 预览(从生成的文件读回, 顺带验证格式/偏移)
# --------------------------------------------------------------------------- #
def parse_blob(blob):
    (magic, ver, flags, cell_h, baseline, half_adv, full_adv, line_gap, _res,
     cjk_first, cjk_count, cjk_off, misc_count, misc_off) = struct.unpack_from("<4s8B5I", blob, 0)
    assert magic == MAGIC, "bad magic"
    misc = {}
    for i in range(misc_count):
        cp, off, adv = struct.unpack_from("<III", blob, misc_off + i * 12)
        misc[cp] = (off, adv)
    return {
        "flags": flags, "cell_h": cell_h, "baseline": baseline,
        "half_adv": half_adv, "full_adv": full_adv, "line_gap": line_gap,
        "cjk_first": cjk_first, "cjk_count": cjk_count, "cjk_off": cjk_off,
        "misc": misc,
    }


def glyph_of(meta, blob, cp):
    if meta["cjk_first"] <= cp < meta["cjk_first"] + meta["cjk_count"]:
        return meta["cjk_off"] + (cp - meta["cjk_first"]) * GLYPH_BYTES, meta["full_adv"]
    e = meta["misc"].get(cp)
    return e if e else (None, meta["half_adv"])


def write_bmp(path, w, h, gray):
    """gray: bytearray(w*h), 0=黑 255=白。写 24 位 BMP。"""
    row_pad = (4 - (w * 3) % 4) % 4
    row_size = w * 3 + row_pad
    pix_size = row_size * h
    file_size = 54 + pix_size
    header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, pix_size, 2835, 2835, 0, 0)
    body = bytearray()
    for y in range(h - 1, -1, -1):               # BMP 自底向上
        for x in range(w):
            v = gray[y * w + x]
            body += bytes((v, v, v))
        body += b"\x00" * row_pad
    with open(path, "wb") as f:
        f.write(header + info + body)


def preview(blob, out_path, lines, width=400, gap=4):
    meta = parse_blob(blob)
    cjk_w = meta["cjk_count"]
    fg, bg = (255, 0) if meta["flags"] & 0x01 else (0, 255)
    canvas_h = (CELL_H + gap) * len(lines) + gap
    canvas = bytearray([bg]) * (width * canvas_h)

    def put(px, py):
        if 0 <= px < width and 0 <= py < canvas_h:
            canvas[py * width + px] = fg

    for li, text in enumerate(lines):
        x = 4
        y = gap + li * (CELL_H + gap)
        for ch in text:
            off, adv = glyph_of(meta, blob, ord(ch))
            if off is None:
                x += adv
                continue
            cell = blob[off:off + GLYPH_BYTES]
            for r in range(CELL_H):
                b0 = cell[r * 2]
                b1 = cell[r * 2 + 1]
                for c in range(8):
                    if (b0 >> (7 - c)) & 1:
                        put(x + c, y + r)
                    if (b1 >> (7 - c)) & 1:
                        put(x + 8 + c, y + r)
            x += adv
    write_bmp(out_path, width, canvas_h, canvas)
    return out_path, canvas_h


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def download(url, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    dest = os.path.join(cache_dir, os.path.basename(url))
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print("使用缓存: %s" % dest)
        return dest
    print("下载: %s" % url)
    import urllib.request
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        total = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    os.replace(tmp, dest)
    print("  完成, %.2f MB" % (total / 1048576.0))
    return dest


def parse_ranges(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo = int(a, 0)
        hi = int(b, 0) if b else lo
        out.append((lo, hi))
    return out


def wanted_from_ranges(ranges):
    s = set()
    for lo, hi in ranges:
        s.update(range(lo, hi + 1))
    return s


def main():
    ap = argparse.ArgumentParser(
        description="把 GNU Unifont .hex 打包成设备用二进制字库(UFB1)")
    ap.add_argument("hexfile", nargs="?",
                    help="unifont .hex 或 .hex.gz;省略则自动下载官方版本")
    ap.add_argument("-o", "--output", default="assets/fonts/unifont16.bin",
                    help="输出 .bin 路径")
    ap.add_argument("--panel", action="store_true",
                    help="输出反相(panel 语义 1=白底);默认 natural(1=墨)")
    ap.add_argument("--ranges", default=None,
                    help='自定义码点范围, 如 "0x20-0x7e,0x4e00-0x9fff"')
    ap.add_argument("--charset", default=None,
                    help="只收录该文本文件里出现的字符(UTF-8)")
    ap.add_argument("--line-gap", type=int, default=LINE_GAP)
    ap.add_argument("--preview", default=None,
                    help="额外渲染一张 BMP 预览(从生成文件读回, 验证格式)")
    ap.add_argument("--url", default=UNIFONT_URL)
    ap.add_argument("--cache-dir", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".cache"))
    args = ap.parse_args()

    # --- 决定要收哪些码点 ---
    if args.charset:
        with open(args.charset, encoding="utf-8") as f:
            wanted = set(ord(c) for c in f.read() if c not in "\r\n")
        print("字符集: %s -> %d 个字符" % (args.charset, len(wanted)))
    elif args.ranges:
        wanted = wanted_from_ranges(parse_ranges(args.ranges))
        print("码点范围: %s -> %d 个码点" % (args.ranges, len(wanted)))
    else:
        wanted = wanted_from_ranges(DEFAULT_RANGES)
        print("默认范围: %d 个码点" % len(wanted))

    # --- 取 hex 源 ---
    hexfile = args.hexfile or download(args.url, args.cache_dir)
    print("解析: %s" % hexfile)
    glyphs, wide, n = parse_unifont_hex(hexfile, wanted)
    print("  命中字形: %d 个 (扫描匹配行 %d)" % (len(glyphs), n))
    if not glyphs:
        print("错误: 没有解析到任何字形", file=sys.stderr)
        return 1

    blob, stats = build(glyphs, wide, invert=args.panel, line_gap=args.line_gap)

    out = args.output
    d = os.path.dirname(out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out, "wb") as f:
        f.write(blob)

    print("")
    print("输出 : %s" % out)
    print("语义 : %s" % ("panel (1=白底)" if args.panel else "natural (1=墨)"))
    print("misc : %d 字" % stats["misc"])
    print("CJK  : %d / %d 槽位 (0x%04X-0x%04X)"
          % (stats["cjk"], stats["cjk_slots"], CJK_FIRST, CJK_LAST))
    print("体积 : %d 字节 (%.1f KB)" % (stats["bytes"], stats["bytes"] / 1024.0))

    if args.preview:
        lines = [
            "Unifont 16x16 bitmap @ ESP32 e-ink",
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "abcdefghijklmnopqrstuvwxyz 0123456789",
            "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
            "中文测试：春眠不觉晓，处处闻啼鸟。",
            "夜来风雨声，花落知多少。",
            "标点：，。！？；：、“”‘’《》〈〉【】（）——……",
            "全角：ＡＢＣａｂｃ１２３＋－＝／",
            "制表：┌──┬──┐ ├──┼──┤ └──┴──┘",
            "箭头：← ↑ → ↓ ↔ ⇒ ⇔ 数学：≤ ≥ ≠ ∞",
        ]
        path, h = preview(blob, args.preview, lines)
        print("预览 : %s (%dx%d)" % (path, 400, h))

    print("")
    print("授权 : GNU Unifont 双许可 = SIL OFL 1.1 / GPL-2.0+ (字体嵌入例外)。")
    print("       本项目按 OFL 1.1 使用, 分发时请附带 OFL 许可与出处。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
