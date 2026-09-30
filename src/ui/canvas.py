# -*- coding: utf-8 -*-
# canvas.py
# 通用 UI 小工具: 画布 + 文本对齐 + 竖向列表菜单
#
# 画布语义: 1 = 墨(黑), 0 = 底(白); 字库默认也是 natural(1=墨)。
# 送显时统一整帧取反为大整数 XOR(C 层), 比逐字节 Python 循环快得多。
# 局刷 LUT 见 driver/epdlut.py。

import time
import framebuf


class Canvas:
    def __init__(self, epd, font):
        self.epd = epd
        self.font = font
        self.width = epd.width
        self.height = epd.height
        self.buf = bytearray(epd.row_bytes * epd.height)
        self.fb = framebuf.FrameBuffer(
            self.buf, epd.width, epd.height, framebuf.MONO_HLSB)
        self._mask = int.from_bytes(b"\xff" * len(self.buf), "big")
        self._fast = True
        self._prev_panel = None           # 面板当前显示帧(局刷差分基线)

    def to_panel(self):
        """自然语义 -> 面板语义(1=白)。"""
        if self._fast:
            try:
                return (int.from_bytes(self.buf, "big") ^ self._mask).to_bytes(
                    len(self.buf), "big")
            except Exception:
                self._fast = False
        return bytes(b ^ 0xFF for b in self.buf)

    def show(self):
        """整帧全刷, 返回耗时(ms)。用于首屏/清残影。"""
        t0 = time.ticks_ms()
        panel = self.to_panel()
        self.epd.display(panel)
        self._prev_panel = panel          # 记住当前显示帧, 供后续局刷做差分基线
        return time.ticks_diff(time.ticks_ms(), t0)

    def show_lut(self, lut):
        """用自定义 LUT 局刷送显(不闪), 返回耗时(ms)。
        lut 见 driver/epdlut.py。"""
        t0 = time.ticks_ms()
        panel = self.to_panel()
        self.epd.display_lut(panel, lut, self._prev_panel)
        self._prev_panel = panel
        return time.ticks_diff(time.ticks_ms(), t0)


# --------------------------------------------------------------------------- #
# 文本
# --------------------------------------------------------------------------- #
def text_center(c, s, y, ink=1):
    x = (c.width - c.font.text_width(s)) // 2
    return c.font.draw(c.fb, s, x, y, ink)


def text_right(c, s, x_right, y, ink=1):
    return c.font.draw(c.fb, s, x_right - c.font.text_width(s), y, ink)


def title_bar(c, text, right_text=None):
    """黑底白字标题栏(顺带就是反白测试), 返回内容区起始 y。"""
    fb = c.fb
    lh = c.font.line_height
    fb.fill_rect(0, 0, c.width, lh, 1)
    c.font.draw(fb, text, 8, 1, ink=0)
    if right_text:
        text_right(c, right_text, c.width - 8, 1, ink=0)
    return lh + 6


# --------------------------------------------------------------------------- #
# 竖向列表菜单
# --------------------------------------------------------------------------- #
def dashed_hline(fb, x, y, w, dash=4, gap=4, color=1):
    """虚线: 比实线像素更少, 而且送显后局刷时变化区域更小。"""
    end = x + w
    while x < end:
        n = dash if x + dash <= end else end - x
        fb.hline(x, y, n, color)
        x += dash + gap


def list_rows(c, top, row_h, bottom=None):
    """按屏幕高度算出一屏能显示几行列表(至少 1 行)。"""
    if bottom is None:
        bottom = c.height - c.font.line_height - 12
    n = (bottom - top) // row_h
    return n if n > 0 else 1


def draw_list(c, items, index, top, row_h, hints=None,
              marker="\u25b6", left=6, indent=44, right_pad=16,
              rows=None, first=0, scrollbar=False, solid=()):
    """通用竖向列表: 选中项用方框框住并带 marker, 右侧 hint 右对齐, 行间分隔线。

    items: 字符串序列
    hints: 与 items 等长的右侧说明(可为 None)
    rows / first: 只画 [first, first+rows) 这些行(滚动窗口); rows=None 表示全部
    scrollbar: 内容多于一屏时在右侧画滚动条
    solid: 需要画“实线”分隔符的行号集合(默认虚线)
    """
    fb = c.fb
    font = c.font
    n = len(items)
    if rows is None or rows > n:
        rows = n
    if rows < 1:
        return
    if first > n - rows:
        first = n - rows
    if first < 0:
        first = 0
    bar = 9 if (scrollbar and n > rows) else 0      # 给滚动条留出的右边距
    ty = (row_h - 6 - font.cell_h) // 2             # 行内垂直居中
    sep_w = c.width - 2 * left - 24
    for i in range(first, first + rows):
        y = top + (i - first) * row_h
        title = items[i]
        hint = None if hints is None else hints[i]
        if i == index:
            # 选中项: 只画一圈方框(不用整行反白黑块), 变化像素少很多
            fb.rect(left, y, c.width - 2 * left - bar, row_h - 6, 1)
            font.draw(fb, marker, left + 8, y + ty)
        if i in solid:
            fb.hline(left + 12, y + row_h - 6, sep_w, 1)
        elif i != index:
            dashed_hline(fb, left + 12, y + row_h - 6, sep_w)
        font.draw(fb, title, indent, y + ty)
        if hint:
            text_right(c, hint, c.width - right_pad - bar, y + ty)

    if scrollbar and n > rows:
        # 右侧滚动条: 3px 轨道 + 按比例/位置滚动的滑块
        bx = c.width - 6
        bh = rows * row_h - 6
        fb.rect(bx, top, 3, bh, 1)
        th = bh * rows // n
        if th < 8:
            th = 8
        by = top + (bh - th) * first // (n - rows)
        fb.fill_rect(bx, by, 3, th, 1)


def draw_footer(c, left_text, right_text=None):
    """底部提示条。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fy = c.height - lh - 6
    fb.fill_rect(0, fy - 6, c.width, lh + 8, 0)
    fb.hline(8, fy - 4, c.width - 16, 1)
    font.draw(fb, left_text, 10, fy)
    if right_text:
        text_right(c, right_text, c.width - 10, fy)


def draw_kv(c, rows, top, label_x=12, label_w=96, value_pad=12):
    """两列信息页: 左边标签, 右边值(值过长自动折行, 续行与值列对齐)。
    rows: [(label, value), ...]  返回结束后的 y。"""
    fb = c.fb
    font = c.font
    vx = label_x + label_w
    y = top
    for label, value in rows:
        font.draw(fb, label, label_x, y)
        y = font.draw_wrapped(fb, str(value), vx, y, c.width - value_pad)
        y += 2
    return y
