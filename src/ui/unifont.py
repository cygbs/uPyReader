# -*- coding: utf-8 -*-
# unifont.py
# UFB1 位图字库的设备端读取 + 渲染(配合 tools/build_font.py 生成的 .bin)
#
# 设计要点:
#   * 每个字形固定 16x16 = 32 字节(MONO_HLSB),ASCII 左对齐、advance=8;
#     定长 => 直接 framebuf.blit,零分支、零解析。
#   * CJK 区(默认 0x4E00-0x9FFF)连续存放,索引 = cp - cjk_first,O(1)。
#   * 其余字符走 misc dict,启动时一次性建表。
#   * 整个字库读进内存(约 726 KB),之后查字/绘制无文件 IO。
#
# 用法:
#   import framebuf
#   from ui.unifont import Unifont
#
#   font = Unifont("/fonts/unifont16.bin")
#   buf = bytearray(400 * 300 // 8)
#   fb = framebuf.FrameBuffer(buf, 400, 300, framebuf.MONO_HLSB)
#   fb.fill(0)                                  # 画布: 1=墨(黑), 0=底(白)
#   font.draw(fb, "春眠不觉晓", 16, 24)          # 默认 ink=1
#   font.draw(fb, "反白", 16, 60, ink=0)          # ink=0 = 在深底上画浅字

import struct

try:
    import framebuf
except ImportError:                      # 仅设备上需要
    framebuf = None

MAGIC = b"UFB1"
GLYPH_BYTES = 32
CELL_W = 16

# 东亚宽度经验表(缺字时决定步进, 避免中英混排错位)
_WIDE_RANGES = (
    (0x1100, 0x115F), (0x2E80, 0x303E), (0x3041, 0x33FF),
    (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xA000, 0xA4CF),
    (0xAC00, 0xD7A3), (0xF900, 0xFAFF), (0xFE30, 0xFE6F),
    (0xFF00, 0xFF60), (0xFFE0, 0xFFE6),
)


def _is_wide_cp(cp):
    for lo, hi in _WIDE_RANGES:
        if lo <= cp <= hi:
            return True
    return False


class Unifont:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        if self.data[:4] != MAGIC:
            raise ValueError("不是 UFB1 字库: %s" % path)

        (magic, ver, flags, self.cell_h, self.baseline,
         self.half_adv, self.full_adv, self.line_gap, _res,
         self.cjk_first, self.cjk_count, self.cjk_off,
         misc_count, misc_off) = struct.unpack_from("<4s8B5I", self.data, 0)

        self.version = ver
        self.panel = bool(flags & 0x01)      # 1 = 字库已反相(1=白底)
        self.font_ink = 0 if self.panel else 1
        self.line_height = self.cell_h + self.line_gap

        # misc 表 -> dict
        self.misc = {}
        unpack_from = struct.unpack_from
        data = self.data
        for i in range(misc_count):
            cp, off, adv = unpack_from("<III", data, misc_off + i * 12)
            self.misc[cp] = (off, adv)

        self._mv = memoryview(data)
        self._cell = bytearray(GLYPH_BYTES)
        self._gfb = None
        self._missing = self._make_missing()

    # ---------------------------------------------------------------- 查询
    def _make_box(self, x, w):
        """生成一个空心方框字形(位值与字库语义保持一致)。"""
        c = bytearray(GLYPH_BYTES)
        fb = framebuf.FrameBuffer(c, CELL_W, self.cell_h, framebuf.MONO_HLSB)
        fb.rect(x, 3, w, self.cell_h - 6, 1)
        if self.panel:                   # panel 字库: 墨点应为 0
            for i in range(GLYPH_BYTES):
                c[i] ^= 0xFF
        return bytes(c)

    def _make_missing(self):
        """缺字占位: 宽度跟随 advance, 避免相邻缺字方框重叠。"""
        self._miss_half = self._make_box(0, CELL_W // 2)
        self._miss_full = self._make_box(1, CELL_W - 2)

    def lookup(self, cp):
        """返回 (bitmap_offset 或 None, advance)。"""
        lo = self.cjk_first
        if lo <= cp < lo + self.cjk_count:
            return self.cjk_off + (cp - lo) * GLYPH_BYTES, self.full_adv
        e = self.misc.get(cp)
        if e is not None:
            return e
        return None, (self.full_adv if _is_wide_cp(cp) else self.half_adv)

    def advance(self, cp):
        if isinstance(cp, str):
            cp = ord(cp)
        return self.lookup(cp)[1]

    def text_width(self, s):
        w = 0
        for ch in s:
            w += self.lookup(ord(ch))[1]
        return w

    # ---------------------------------------------------------------- 绘制
    def _blit_glyph(self, fb, cp, x, y, ink):
        """把一个字形画到 fb 的 (x, y), 返回 advance。"""
        if self._gfb is None:
            self._gfb = framebuf.FrameBuffer(
                self._cell, CELL_W, self.cell_h, framebuf.MONO_HLSB)
        off, adv = self.lookup(cp)
        if off is None:
            raw = self._miss_full if adv == self.full_adv else self._miss_half
        else:
            raw = self._mv[off:off + GLYPH_BYTES]
        if self.font_ink != ink:
            cell = self._cell
            for i in range(GLYPH_BYTES):
                cell[i] = raw[i] ^ 0xFF
        else:
            self._cell[:] = raw
        fb.blit(self._gfb, x, y, 1 - ink)    # 跳过背景位, 只写文字像素
        return adv

    def draw(self, fb, s, x, y, ink=1):
        """画一行字符串。ink: 文字像素在画布上的位值(默认 1)。
        返回结束后的 x 坐标。"""
        blit = self._blit_glyph
        cx = x
        for ch in s:
            cx += blit(fb, ord(ch), cx, y, ink)
        return cx

    def draw_wrapped(self, fb, s, x, y, max_x, ink=1, line_gap=None):
        """带折行的整段绘制(按字符宽度换行, 不做禁则处理)。
        max_x 为右边界(x 坐标, 不含)。返回下一行的 y。"""
        lh = self.cell_h + (self.line_gap if line_gap is None else line_gap)
        blit = self._blit_glyph
        cx = x
        for ch in s:
            if ch == "\n":
                cx = x
                y += lh
                continue
            cp = ord(ch)
            adv = self.lookup(cp)[1]
            if cx + adv > max_x:
                cx = x
                y += lh
            cx += blit(fb, cp, cx, y, ink)
        return y + lh
