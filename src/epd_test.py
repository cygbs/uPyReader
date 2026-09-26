# -*- coding: utf-8 -*-
"""
epd_test.py — SSD1619 4.2" 400x300 墨水屏「中文显示」测试

依赖:
    library/epd_ssd1619.py    屏驱动
    library/unifont.py        UFB1 位图字库读取 / 渲染
    /fonts/unifont16.bin      字库(由 tools/build_font.py 生成, tools/upload.sh 上传)

用法(板子上):
    import epd_test
    epd_test.run_all()              # 依次跑完全部中文显示测试
    epd_test.run_all(do_sleep=True) # 跑完让屏休眠
    epd_test.menu()                 # 交互菜单, 逐项测试
或从 PC:
    mpremote connect /dev/ttyACM0 exec "import epd_test; epd_test.run_all()"

画布语义: 1 = 墨(黑), 0 = 底(白); 字库默认也是 natural(1=墨), 送显时统一取反。
"""

import time
import sys
import framebuf

try:
    import machine
    from machine import Pin, SPI
except ImportError:                      # 在 PC 上做语法检查时会走到这里
    machine = None
    Pin = SPI = None


# ===========================================================================
# ① 让 library/ 里的模块可导入(兼容设备根目录、/lib、脚本同级)
# ===========================================================================
def _setup_path():
    here = ""
    try:
        here = __file__.rsplit("/", 1)[0]
    except Exception:
        pass
    for p in (here, here + "/library", "library", "/library", "/lib"):
        try:
            if p and p not in sys.path:
                sys.path.append(p)
        except Exception:
            pass


_setup_path()


# ===========================================================================
# ② 硬件配置
#   优先读 library/hwconfig.py(接线的唯一配置源, 与 main.py 共用);
#   找不到时退回下面内置默认值 —— 本文件是可独立运行的诊断工具。
# ===========================================================================
try:
    from hwconfig import (
        EPD_SCK as PIN_SCK, EPD_MOSI as PIN_MOSI, EPD_CS as PIN_CS,
        EPD_DC as PIN_DC, EPD_RST as PIN_RST, EPD_BUSY as PIN_BUSY,
        EPD_SPI_ID as SPI_ID, EPD_SPI_BAUD as SPI_BAUD,
        WIDTH, HEIGHT, FONT_CANDIDATES,
    )
except ImportError:
    PIN_SCK, PIN_MOSI, PIN_CS = 12, 11, 10
    PIN_DC, PIN_RST, PIN_BUSY = 9, 8, 7
    SPI_ID, SPI_BAUD = 1, 4_000_000
    WIDTH, HEIGHT = 400, 300
    FONT_CANDIDATES = (
        "/fonts/unifont16.bin",
        "fonts/unifont16.bin",
        "assets/fonts/unifont16.bin",
    )

MARGIN = 12

# 驱动与字库
try:
    from epd_ssd1619 import EPD_SSD1619
except ImportError:
    raise ImportError("找不到驱动 epd_ssd1619.py(应在 /library/ 下)")

try:
    from unifont import Unifont
except ImportError:
    raise ImportError("找不到 unifont.py(应在 /library/ 下)")


def find_font():
    import os
    for p in FONT_CANDIDATES:
        try:
            os.stat(p)
            return p
        except OSError:
            pass
    return None


# ===========================================================================
# ③ 画布
# ===========================================================================
class Canvas:
    """400x300 framebuf 封装。1=墨, 0=底; 送显时取反为 panel 语义。"""

    def __init__(self, epd, font):
        self.epd = epd
        self.font = font
        self.buf = bytearray(epd.row_bytes * epd.height)
        self.fb = framebuf.FrameBuffer(
            self.buf, epd.width, epd.height, framebuf.MONO_HLSB)
        # 整帧取反用大整数 XOR(C 层), 比逐字节 Python 循环快得多
        self._mask = int.from_bytes(b"\xff" * len(self.buf), "big")
        self._fast_invert = True

    def _to_panel(self):
        if self._fast_invert:
            try:
                return (int.from_bytes(self.buf, "big") ^ self._mask).to_bytes(
                    len(self.buf), "big")
            except Exception:
                self._fast_invert = False
        return EPD_SSD1619.invert(self.buf)

    def show(self, mode="full"):
        t0 = time.ticks_ms()
        self.epd.display(self._to_panel(), mode=mode)
        return time.ticks_diff(time.ticks_ms(), t0)


# ===========================================================================
# ④ 中文排版小工具
# ===========================================================================
TITLE = "墨水屏中文显示测试"


def title(c, s):
    """黑底白字的标题栏, 返回内容区起始 y。返回的同时也顺带测了反白。"""
    fb = c.fb
    lh = c.font.line_height
    fb.fill_rect(0, 0, WIDTH, lh, 1)
    c.font.draw(fb, s, MARGIN, 1, ink=0)
    return lh + 6


def center(c, s, y, ink=1):
    x = (WIDTH - c.font.text_width(s)) // 2
    return c.font.draw(c.fb, s, x, y, ink)


def right(c, s, x_right, y, ink=1):
    return c.font.draw(c.fb, s, x_right - c.font.text_width(s), y, ink)


# ===========================================================================
# ⑤ 测试项
# ===========================================================================
def t_basic(c, epd):
    """① 中文基础渲染: 字库、行高、每行字数。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "1. 中文基础渲染")

    y += 8
    for line in ("春眠不觉晓，处处闻啼鸟。",
                 "夜来风雨声，花落知多少。",
                 "—— 唐·孟浩然《春晓》"):
        center(c, line, y)
        y += lh

    y += 10
    fb.hline(MARGIN, y, WIDTH - 2 * MARGIN, 1)
    y += 10
    for s in ("字库 Unifont 16x16，行高 %d px" % lh,
              "每行可排 %d 个汉字" % (WIDTH // font.cell_h),
              "整屏可排 %d 行" % (HEIGHT // lh)):
        font.draw(fb, s, MARGIN, y)
        y += lh

    ms = c.show("full")
    print("[1 基础] %d ms" % ms)
    return ms


def t_mixed(c, epd):
    """② 中英数混排 + 基线对齐。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "2. 中英数混排 · 基线")

    y += 6
    for s in ("汉字宽 16px，ASCII 宽 8px",
              "中文English混合test123排版",
              "ABCabc012 汉字 EFGdef345"):
        font.draw(fb, s, MARGIN, y)
        y += lh

    # 基线检查: 先画字, 再在基线上压一条参考线
    y += 4
    font.draw(fb, "基线参照 AMg1e 汉字", MARGIN, y)
    fb.hline(MARGIN, y + font.baseline, WIDTH - 2 * MARGIN, 1)
    y += lh + 10

    font.draw(fb, "全角：ＡＢＣ１２３ａｂｃ", MARGIN, y)
    y += lh
    font.draw(fb, "半角：ABC123abc", MARGIN, y)

    ms = c.show("full")
    print("[2 混排] %d ms" % ms)
    return ms


def t_punct(c, epd):
    """③ 标点与全角符号。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "3. 标点与全角符号")

    y += 4
    for s in ("中文标点：，。！？；：、（）",
              "引号括号：“”‘’《》〈〉【】",
              "省略破折：…… —— · ～",
              "全角符号：＋－×÷＝／％＃＆＠",
              "箭头数学：← ↑ → ↓ ↔ ≤ ≥ ≠ ∞",
              "货币单位：￥ ＄ € ￠ ￡"):
        font.draw(fb, s, MARGIN, y)
        y += lh

    ms = c.show("full")
    print("[3 标点] %d ms" % ms)
    return ms


def t_align(c, epd):
    """④ 左 / 中 / 右 对齐。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "4. 左 / 中 / 右 对齐")
    left, rgt = MARGIN, WIDTH - MARGIN

    y += 6
    # 边界参考竖线
    fb.vline(left - 2, y, 3 * lh + 8, 1)
    fb.vline(rgt + 1, y, 3 * lh + 8, 1)

    font.draw(fb, "左对齐文本", left, y)
    y += lh
    center(c, "居中对齐", y)
    y += lh
    right(c, "右对齐文本", rgt, y)
    y += lh + 8

    fb.hline(MARGIN, y, WIDTH - 2 * MARGIN, 1)
    y += 8
    font.draw(fb, "说明：用 text_width() 精确算宽度，", MARGIN, y)
    y += lh
    font.draw(fb, "中英文混排也不会错位。", MARGIN, y)

    ms = c.show("full")
    print("[4 对齐] %d ms" % ms)
    return ms


def t_wrap(c, epd):
    """⑤ 自动折行(draw_wrapped)。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "5. 自动折行")

    para = ("这是一个基于 ESP32-S3 与 MicroPython 的墨水屏阅读器实验项目。"
            "屏幕为 400x300 的 SSD1619 黑白墨水屏，字库使用 GNU Unifont 16x16 位图字库。"
            "本段用于测试中文自动折行与整页排版，检查标点、行距以及中英混排 Mixed 123 是否整齐。")

    y0 = y + 6
    y1 = font.draw_wrapped(fb, para, MARGIN, y0, WIDTH - MARGIN)
    lines = (y1 - y0) // lh
    fb.hline(MARGIN, y1 + 2, WIDTH - 2 * MARGIN, 1)
    font.draw(fb, "共 %d 行 / %d 字符，行高 %d" % (lines, len(para), lh),
              MARGIN, y1 + 8)

    ms = c.show("full")
    print("[5 折行] %d ms" % ms)
    return ms


def t_page(c, epd):
    """⑥ 模拟阅读器整页: 状态栏 + 正文 + 底栏。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)

    # 顶部状态栏(黑底白字)
    fb.fill_rect(0, 0, WIDTH, lh, 1)
    font.draw(fb, "将进酒（节选）", MARGIN, 1, ink=0)
    right(c, "1/3", WIDTH - MARGIN, 1, ink=0)

    body = ("君不见黄河之水天上来，奔流到海不复回。"
            "君不见高堂明镜悲白发，朝如青丝暮成雪。"
            "人生得意须尽欢，莫使金樽空对月。"
            "—— 唐·李白")
    font.draw_wrapped(fb, body, MARGIN + 4, lh + 12, WIDTH - MARGIN)

    # 底栏
    fb.hline(MARGIN, HEIGHT - lh - 8, WIDTH - 2 * MARGIN, 1)
    font.draw(fb, "上一页", MARGIN, HEIGHT - lh - 2)
    right(c, "下一页", WIDTH - MARGIN, HEIGHT - lh - 2)

    ms = c.show("full")
    print("[6 整页] %d ms" % ms)
    return ms


def t_invert(c, epd):
    """⑦ 反白 / 强调 / 选中态。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "6. 反白 · 强调 · 选中态")

    y += 8
    fb.fill_rect(MARGIN, y, WIDTH - 2 * MARGIN, lh + 8, 1)
    font.draw(fb, "白字黑底：重点提示", MARGIN + 8, y + 4, ink=0)
    y += lh + 18

    fb.fill_rect(MARGIN, y, WIDTH - 2 * MARGIN, lh, 1)
    font.draw(fb, "> 选中的菜单项", MARGIN + 8, y + 1, ink=0)
    y += lh + 4
    font.draw(fb, "> 未选中的菜单项", MARGIN + 8, y)
    y += lh + 4
    font.draw(fb, "> 未选中的菜单项", MARGIN + 8, y)
    y += lh + 12

    font.draw(fb, "阅读进度 42%", MARGIN, y)
    y += lh - 4
    fb.rect(MARGIN, y, WIDTH - 2 * MARGIN, 12, 1)
    fb.fill_rect(MARGIN + 1, y + 1, int((WIDTH - 2 * MARGIN - 2) * 0.42), 10, 1)

    ms = c.show("full")
    print("[7 反白] %d ms" % ms)
    return ms


def t_missing(c, epd):
    """⑧ 缺字占位(字库外的字符)。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "7. 缺字占位")

    y += 6
    font.draw(fb, "以下字符不在字库里，显示为方框：", MARGIN, y)
    y += lh + 6
    font.draw(fb, "㐀 汉字扩展A", MARGIN, y)
    y += lh
    font.draw(fb, "ᚠ ᚢ ᚦ 卢恩字母", MARGIN, y)
    y += lh
    font.draw(fb, "ก ข ค 泰文", MARGIN, y)
    y += lh
    font.draw(fb, "Ա Բ Գ 亚美尼亚文", MARGIN, y)
    y += lh + 8
    fb.hline(MARGIN, y - 4, WIDTH - 2 * MARGIN, 1)
    font.draw(fb, "方框宽度跟随字符宽度，不会重叠。", MARGIN, y)
    y += lh
    font.draw(fb, "正常字符：中文 ABC 123 依旧对齐。", MARGIN, y)

    ms = c.show("full")
    print("[8 缺字] %d ms" % ms)
    return ms


def _paint_page(c, name):
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "%s 波形测试" % name)
    font.draw(fb, "春眠不觉晓，处处闻啼鸟。", MARGIN, y)
    y += lh
    font.draw(fb, "夜来风雨声，花落知多少。", MARGIN, y)
    y += lh + 10
    for i in range(4):
        fb.fill_rect(MARGIN + i * 92, y, 72, 44, 1)
    font.draw(fb, "观察对比度与残影", MARGIN, y + 56)


def t_refresh(c, epd):
    """⑨ 全刷 / 快刷 / 局刷 三种波形耗时对比。"""
    results = []
    for name, pre, mode in (
            ("全刷", lambda: epd.init(), "full"),
            ("快刷", lambda: epd.init_fast(1.0), "fast"),
            ("局刷", lambda: epd.init(), "partial")):
        _paint_page(c, name)
        pre()
        ms = c.show(mode)
        results.append((name, ms))
        print("[9 刷新] %s = %d ms" % (name, ms))
        time.sleep_ms(800)

    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "8. 刷新波形耗时对比")
    y += 8
    for name, ms in results:
        font.draw(fb, name, MARGIN, y)
        s = "%d ms" % ms
        font.draw(fb, s, 150 - font.text_width(s), y)
        w = min(200, ms * 200 // max(1, results[0][1]))
        fb.fill_rect(160, y + 5, w, 6, 1)
        y += lh + 6
    y += 6
    font.draw(fb, "全刷：对比度最好，残影最少", MARGIN, y)
    y += lh
    font.draw(fb, "局刷：最快，但有残影，需定期全刷", MARGIN, y)
    epd.init()
    c.show("full")
    return results


def t_partial(c, epd, seconds=12):
    """⑩ 局部刷新动态(中文计数 + 进度条)。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    y = title(c, "9. 局部刷新 · 中文动态")

    lab1 = "刷新次数："
    lab2 = "已用时间："
    font.draw(fb, lab1, MARGIN, y)
    font.draw(fb, lab2, MARGIN, y + lh)
    bar_y = y + 2 * lh + 8
    fb.rect(MARGIN, bar_y, WIDTH - 2 * MARGIN, 14, 1)
    font.draw(fb, "每 25 帧自动全刷一次，清除残影", MARGIN, HEIGHT - lh - 4)

    epd.init()
    c.show("full")

    x1 = MARGIN + font.text_width(lab1)
    x2 = MARGIN + font.text_width(lab2)
    t0 = time.ticks_ms()
    end = time.ticks_add(t0, int(seconds * 1000))
    n = 0
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        el = time.ticks_diff(time.ticks_ms(), t0)
        ratio = el / float(seconds * 1000)
        if ratio > 1.0:
            ratio = 1.0

        fb.fill_rect(x1, y, 180, lh, 0)
        font.draw(fb, "%d" % n, x1, y)

        fb.fill_rect(x2, y + lh, 180, lh, 0)
        font.draw(fb, "%d.%d 秒" % (el // 1000, (el % 1000) // 100), x2, y + lh)

        fb.fill_rect(MARGIN + 1, bar_y + 1, WIDTH - 2 * MARGIN - 2, 12, 0)
        fb.fill_rect(MARGIN + 1, bar_y + 1,
                     int((WIDTH - 2 * MARGIN - 2) * ratio), 12, 1)

        c.show("partial")
        n += 1
        if n % 25 == 0:
            epd.init()
            c.show("full")

    print("[10 局刷] %d 帧 / %d 秒" % (n, seconds))
    return n


def t_done(c, epd):
    """结束页。"""
    fb = c.fb
    font = c.font
    lh = font.line_height
    fb.fill(0)
    fb.rect(0, 0, WIDTH, HEIGHT, 1)
    y = 66
    center(c, "中文显示测试", y)
    y += lh + 8
    center(c, "全部完成", y)
    y += lh + 12
    fb.hline(90, y, WIDTH - 180, 1)
    y += 14
    center(c, "若以上中文显示均正常，", y)
    y += lh
    center(c, "说明字库、驱动与接线都正确。", y)
    epd.init()
    return c.show("full")


# ===========================================================================
# ⑥ 组装 / 运行
# ===========================================================================
def make_spi():
    last = None
    for sid in (SPI_ID, 2, 1):
        try:
            return SPI(sid, baudrate=SPI_BAUD, polarity=0, phase=0,
                       sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI))
        except Exception as e:
            last = e
    raise last


def setup():
    """初始化 SPI + 驱动 + 字库, 返回 (epd, spi, canvas)。"""
    spi = make_spi()
    epd = EPD_SSD1619(
        spi,
        Pin(PIN_CS, Pin.OUT),
        Pin(PIN_DC, Pin.OUT),
        Pin(PIN_RST, Pin.OUT),
        Pin(PIN_BUSY, Pin.IN),
    )
    print("init e-paper ...")
    epd.init()

    path = find_font()
    if path is None:
        raise OSError("找不到字库 unifont16.bin。"
                      "请先在 PC 上运行 tools/build_font.py，再用 tools/upload.sh 上传")
    print("load font: %s" % path)
    font = Unifont(path)
    print("font: cell=%d line_height=%d glyphs=%d (%s)"
          % (font.cell_h, font.line_height,
             len(font.misc) + font.cjk_count,
             "panel" if font.panel else "natural"))

    c = Canvas(epd, font)
    return epd, spi, c


TESTS = (
    ("basic", t_basic),
    ("mixed", t_mixed),
    ("punct", t_punct),
    ("align", t_align),
    ("wrap", t_wrap),
    ("page", t_page),
    ("invert", t_invert),
    ("missing", t_missing),
    ("refresh", t_refresh),
    ("partial", t_partial),
    ("done", t_done),
)


def run_all(pause=1.0, do_sleep=False):
    """依次跑完全部中文显示测试。pause=每步停留秒数。"""
    epd, spi, c = setup()
    for name, fn in TESTS:
        print("==== %s ====" % name)
        try:
            fn(c, epd)
        except Exception as e:
            print("!! %s 失败: %r" % (name, e))
        try:
            time.sleep(pause)
        except Exception:
            pass
    if do_sleep:
        epd.sleep()
        print("e-paper sleeping")
    print("run_all 结束")


def menu():
    """交互菜单, 可在 REPL 里逐项测试。"""
    epd, spi, c = setup()
    while True:
        print("\n=== 中文显示测试菜单 ===")
        for i, (n, _) in enumerate(TESTS):
            print("  %d) %s" % (i + 1, n))
        print("  q) 退出")
        try:
            sel = input("select> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if sel in ("q", "quit", ""):
            break
        hit = None
        for i, (n, fn) in enumerate(TESTS):
            if sel == str(i + 1) or sel == n:
                hit = fn
                break
        if hit is None:
            print("无效选择")
            continue
        try:
            hit(c, epd)
        except Exception as e:
            print("!! 失败: %r" % e)
    print("bye")


if __name__ == "__main__":
    run_all()
