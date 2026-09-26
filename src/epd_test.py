# -*- coding: utf-8 -*-
"""
epd_test.py — HINK-E042A13-A0 / SSD1619 4.2" 400x300 黑白墨水屏测试 Demo

配套驱动: library/epd_ssd1619.py

用法（板子上）:
    import epd_test
    epd_test.run_all()          # 依次执行全部测试
    epd_test.menu()             # 交互式菜单（可选单项）
或直接:
    mpremote connect /dev/ttyACM0 run epd_test.py

说明:
  * 点阵字体只有 8x8 ASCII，中文需要自备字库，本 Demo 不含。
  * 屏幕为纯黑白，所谓"灰度"是用 4x4 Bayer 抖动模拟出来的。
  * 首次运行前，请先核对下面的“接线配置”，改成你的实际引脚！
"""

import time
import gc
import sys
import framebuf

try:
    import machine
    from machine import Pin, SPI
except ImportError:          # 在 PC 上做语法检查时会走到这里
    machine = None
    Pin = SPI = None


# ===========================================================================
# ① 接线配置
# ---------------------------------------------------------------------------
#   屏幕丝印   含义                接到 ESP32-S3-N16R8    本文件变量
#   --------   ----------------    -------------------    ----------
#   3V3        电源 3.3V           3V3                    (切勿接 5V!)
#   GND        地                  GND                    --
#   SCLK       时钟 (CLK)          GPIO12                 PIN_SCK
#   SDI        SPI 数据 (MOSI)     GPIO11                 PIN_MOSI
#   CS         片选                GPIO10                 PIN_CS
#   D/C        数据/命令选择 (DC)  GPIO9                  PIN_DC
#   RES        复位 (RST)          GPIO8                  PIN_RST
#   BUSY       忙信号              GPIO7                  PIN_BUSY
#
#   说明:
#     * SDI = MOSI，由 ESP32 输出数据；SCLK = 时钟。屏是只写设备，
#       没有 MISO / 回读引脚，所以 SPI 只初始化 sck + mosi。
#     * 这 6 个 GPIO 可任意选(避开 GPIO26-32、19/20、43/44)，
#       只要和下面几行保持一致即可。
# ===========================================================================
PIN_SCK  = 12    # 屏幕 SCLK
PIN_MOSI = 11    # 屏幕 SDI
PIN_CS   = 10    # 屏幕 CS
PIN_DC   = 9     # 屏幕 D/C
PIN_RST  = 8     # 屏幕 RES
PIN_BUSY = 7     # 屏幕 BUSY
SPI_ID   = 1     # ESP32-S3 用 SPI(1)；失败会自动退回 SPI(2)
SPI_BAUD = 4_000_000     # 4 MHz 稳定；可试 8_000_000

WIDTH  = 400
HEIGHT = 300


# ===========================================================================
# ② 导入驱动（兼容 library/ 放在设备根目录、/lib 或脚本同级目录）
# ===========================================================================
def _import_driver():
    try:
        from epd_ssd1619 import EPD_SSD1619
        return EPD_SSD1619
    except ImportError:
        pass

    cands = ["library", "/library", "/lib"]
    try:
        here = __file__.rsplit("/", 1)[0]
        if here:
            cands.insert(0, here + "/library")
            cands.insert(1, here)
    except Exception:
        pass

    for p in cands:
        try:
            if p and p not in sys.path:
                sys.path.append(p)
        except Exception:
            pass

    from epd_ssd1619 import EPD_SSD1619
    return EPD_SSD1619


EPD = _import_driver()


# ===========================================================================
# ③ 画布封装
# ===========================================================================
class Canvas:
    """把 400x300 的 framebuf(MONO_HLSB) 包一层，负责送显和计时。"""

    def __init__(self, epd):
        self.epd = epd
        self.buf = bytearray(epd.row_bytes * epd.height)
        self.fb = framebuf.FrameBuffer(
            self.buf, epd.width, epd.height, framebuf.MONO_HLSB
        )

    def clear(self, color=0):
        """color=0 -> 白底（驱动会取反）。"""
        self.fb.fill(color)

    def show(self, mode="full"):
        """送显并返回耗时(ms)。mode: 'full' | 'fast' | 'partial'。"""
        t0 = time.ticks_ms()
        self.epd.display(EPD.invert(self.buf), mode=mode)
        return time.ticks_diff(time.ticks_ms(), t0)


# ===========================================================================
# ④ 绘图小工具
# ===========================================================================
_GLYPH_FB = None


def _glyph_fb():
    global _GLYPH_FB
    if _GLYPH_FB is None:
        _GLYPH_FB = framebuf.FrameBuffer(bytearray(8), 8, 8, framebuf.MONO_HLSB)
    return _GLYPH_FB


def text_width(s, scale=1):
    return 8 * scale * len(s)


def draw_text(fb, s, x, y, color=1, scale=1, bg=0):
    """支持整数倍放大的 8x8 文字。color=1 -> 黑字，color=0 -> 白字(反白)。
    返回结束后下一个字符的 x 坐标。"""
    if scale <= 1:
        fb.text(s, x, y, color)
        return x + 8 * len(s)

    g = _glyph_fb()
    cx = x
    for ch in s:
        g.fill(bg)
        g.text(ch, 0, 0, color)
        for row in range(8):
            for col in range(8):
                if g.pixel(col, row):
                    fb.fill_rect(cx + col * scale, y + row * scale,
                                 scale, scale, color)
        cx += 8 * scale
    return cx


def draw_center(fb, s, y, color=1, scale=1, x=0, w=WIDTH):
    xx = x + (w - text_width(s, scale)) // 2
    draw_text(fb, s, xx, y, color, scale)
    return xx


_BAYER4 = (
    (0,  8,  2, 10),
    (12, 4, 14,  6),
    (3, 11,  1,  9),
    (15, 7, 13,  5),
)


def dither_rect(fb, x, y, w, h, level):
    """用 4x4 Bayer 抖动填充一块“灰度”区域，level 0..16。"""
    for j in range(h):
        row = _BAYER4[j & 3]
        for i in range(w):
            if row[i & 3] < level:
                fb.pixel(x + i, y + j, 1)


# ===========================================================================
# ⑤ 各项测试
# ===========================================================================
def t_info(c, epd):
    """屏幕信息 + 引脚信息。"""
    fb = c.fb
    fb.fill(0)
    fb.rect(0, 0, WIDTH, HEIGHT, 1)
    fb.rect(1, 1, WIDTH - 2, HEIGHT - 2, 1)
    draw_center(fb, "E-PAPER TEST", 12, 1, 3)
    fb.hline(24, 46, WIDTH - 48, 1)
    draw_center(fb, "SSD1619 / UC8151D   400x300  1-bit", 54, 1, 1)

    lines = [
        "SPI%d  SCK=%d  MOSI=%d  %dMHz" % (
            SPI_ID, PIN_SCK, PIN_MOSI, SPI_BAUD // 1000000),
        "CTRL  CS=%d  DC=%d  RST=%d  BUSY=%d" % (
            PIN_CS, PIN_DC, PIN_RST, PIN_BUSY),
    ]
    if machine is not None:
        try:
            lines.append("CPU freq   : %d MHz" % (machine.freq() // 1000000))
        except Exception:
            pass
    try:
        lines.append("MicroPython: %s" % ".".join(
            str(v) for v in sys.implementation.version))
    except Exception:
        lines.append("MicroPython: (unknown)")
    lines.append("free heap  : %d KB" % (gc.mem_free() // 1024))

    y = 82
    for s in lines:
        fb.text(s, 20, y, 1)
        y += 14

    # 色块 / 图案测试
    fb.fill_rect(20, 190, 70, 50, 1)
    fb.text("black", 26, 246, 1)
    fb.rect(110, 190, 70, 50, 1)
    fb.text("white", 116, 246, 1)
    # 棋盘格
    for j in range(5):
        for i in range(9):
            if (i + j) & 1:
                fb.fill_rect(200 + i * 10, 190 + j * 10, 10, 10, 1)
    fb.text("checker", 232, 246, 1)
    fb.text("worst-case pattern", 20, 266, 1)

    ms = c.show("full")
    print("[info] full refresh = %d ms" % ms)
    return ms


def t_shapes(c, epd):
    """基本图元。"""
    fb = c.fb
    fb.fill(0)
    draw_center(fb, "SHAPES", 2, 1, 2)
    fb.hline(20, 22, WIDTH - 40, 1)

    # 线 / 三角形
    fb.line(20, 40, 180, 140, 1)
    fb.line(180, 140, 20, 140, 1)
    fb.line(20, 140, 20, 40, 1)
    # 空心矩形
    fb.rect(210, 40, 80, 60, 1)
    # 实心矩形
    fb.fill_rect(300, 40, 80, 60, 1)
    # 分隔线
    fb.hline(20, 162, WIDTH - 40, 1)
    # 椭圆
    fb.ellipse(70, 218, 45, 40, 1)
    fb.fill_ellipse(180, 218, 45, 40, 1)
    # 反白文字
    fb.fill_rect(260, 178, 120, 80, 1)
    draw_center(fb, "INV", 208, 0, 3, x=260, w=120)

    fb.text("triangle", 20, 150 - 6, 1)
    fb.text("rect", 210, 104, 1)
    fb.text("fill", 300, 104, 1)
    fb.text("ellipse", 40, 268, 1)
    fb.text("fill_ellipse", 140, 268, 1)
    fb.text("inverted", 278, 262, 1)

    ms = c.show("full")
    print("[shapes] full refresh = %d ms" % ms)
    return ms


def t_font(c, epd):
    """ASCII 字库 + 放大倍数 + 反白。"""
    fb = c.fb
    fb.fill(0)
    draw_center(fb, "FONT 8x8", 4, 1, 2)

    # 全部可打印 ASCII，50 个一行
    for i, code in enumerate(range(32, 127)):
        fb.text(chr(code), 8 * (i % 50), 24 + 12 * (i // 50), 1)
    fb.hline(20, 50, WIDTH - 40, 1)

    draw_text(fb, "scale=1  ABCdef 0123 !@#", 16, 58, 1, 1)
    draw_text(fb, "scale=2", 16, 74, 1, 2)
    draw_text(fb, "scale=3 ABC", 16, 96, 1, 3)
    draw_text(fb, "scale=4 Big!", 16, 126, 1, 4)

    fb.fill_rect(16, 170, WIDTH - 32, 44, 1)
    draw_center(fb, "INVERTED  white-on-black", 182, 0, 2)

    fb.text("Chinese needs a bitmap font (not included)", 16, 228, 1)
    fb.text("this line is 8px tall", 16, 244, 1)
    fb.line(16, 262, WIDTH - 16, 262, 1)
    fb.text("bottom edge marker", 16, 276, 1)

    ms = c.show("full")
    print("[font] full refresh = %d ms" % ms)
    return ms


def t_gray(c, epd):
    """B/W 屏的“灰度”模拟：有序抖动。"""
    fb = c.fb
    fb.fill(0)
    draw_center(fb, "ORDERED DITHER", 6, 1, 2)

    # 连续渐变条
    x0, y0, w, h = 20, 30, 360, 80
    fb.rect(x0 - 1, y0 - 1, w + 2, h + 2, 1)
    for j in range(h):
        row = _BAYER4[j & 3]
        for i in range(w):
            if row[i & 3] < (i * 16) // w:
                fb.pixel(x0 + i, y0 + j, 1)
    fb.text("0%", x0, y0 + h + 4, 1)
    fb.text("50%", x0 + w // 2 - 12, y0 + h + 4, 1)
    fb.text("100%", x0 + w - 32, y0 + h + 4, 1)

    # 5 级灰阶色块
    labels = ("0%", "25%", "50%", "75%", "100%")
    levels = (0, 4, 8, 12, 16)
    pw, ph = 64, 70
    for i, (lab, lv) in enumerate(zip(labels, levels)):
        px = 24 + i * (pw + 12)
        py = 160
        fb.rect(px - 1, py - 1, pw + 2, ph + 2, 1)
        dither_rect(fb, px, py, pw, ph, lv)
        fb.text(lab, px + pw // 2 - 12, py + ph + 4, 1)

    fb.text("dither = fake gray, not real 4-level output", 24, 262, 1)

    ms = c.show("full")
    print("[gray] full refresh = %d ms" % ms)
    return ms


def t_align(c, epd):
    """边界 / 居中 / 偏移检查图案。"""
    fb = c.fb
    fb.fill(0)

    # 单像素外框 + 内框
    fb.rect(0, 0, WIDTH, HEIGHT, 1)
    fb.rect(1, 1, WIDTH - 2, HEIGHT - 2, 1)

    # 四角实心块
    for (px, py) in ((0, 0), (WIDTH - 12, 0), (0, HEIGHT - 12),
                     (WIDTH - 12, HEIGHT - 12)):
        fb.fill_rect(px, py, 12, 12, 1)

    # 中心十字
    cx, cy = WIDTH // 2, HEIGHT // 2
    fb.line(cx - 20, cy, cx + 20, cy, 1)
    fb.line(cx, cy - 20, cx, cy + 20, 1)
    fb.rect(cx - 6, cy - 6, 12, 12, 1)

    # 1px 网格（左上区域）
    for i in range(0, 120, 10):
        fb.vline(20 + i, 20, 60, 1)
    for j in range(0, 60, 10):
        fb.hline(20, 20 + j, 120, 1)

    fb.text("(0,0)", 16, 16, 1)
    fb.text("(399,0)", WIDTH - 56, 16, 1)
    fb.text("(0,299)", 16, HEIGHT - 16, 1)
    fb.text("(399,299)", WIDTH - 72, HEIGHT - 16, 1)
    draw_center(fb, "CENTER", cy + 26, 1, 1)
    fb.text("10px grid", 24, 88, 1)
    fb.text("1px border -> check clipping / offset", 150, 200, 1)

    ms = c.show("full")
    print("[align] full refresh = %d ms" % ms)
    return ms


def _paint_refresh_frame(fb, title, note):
    fb.fill(0)
    fb.rect(0, 0, WIDTH, HEIGHT, 1)
    draw_center(fb, title, 30, 1, 4)
    draw_center(fb, note, 90, 1, 1)
    # 一些细节，便于肉眼比较残影
    for i in range(4):
        fb.fill_rect(40 + i * 85, 130, 60, 60, 1)
    draw_center(fb, "timing test", 210, 1, 1)
    draw_center(fb, "watch ghosting / contrast", 230, 1, 1)


def t_refresh(c, epd):
    """对比 full / fast / partial 三种波形的耗时。"""
    results = []

    # 全刷
    _paint_refresh_frame(c.fb, "FULL", "init() -> display(mode='full')")
    epd.init()
    ms = c.show("full")
    results.append(("full", ms))
    print("[refresh] full    = %d ms" % ms)
    time.sleep_ms(900)

    # 快刷
    _paint_refresh_frame(c.fb, "FAST", "init_fast(1.0) -> display('fast')")
    epd.init_fast(1.0)
    ms = c.show("fast")
    results.append(("fast", ms))
    print("[refresh] fast    = %d ms" % ms)
    time.sleep_ms(900)

    # 局部/快速波形
    _paint_refresh_frame(c.fb, "PARTIAL", "init() -> display('partial')")
    epd.init()
    ms = c.show("partial")
    results.append(("partial", ms))
    print("[refresh] partial = %d ms" % ms)
    time.sleep_ms(900)

    # 结果汇总
    fb = c.fb
    fb.fill(0)
    fb.rect(0, 0, WIDTH, HEIGHT, 1)
    draw_center(fb, "REFRESH TIME", 16, 1, 2)
    fb.hline(30, 40, WIDTH - 60, 1)
    y = 70
    for name, ms in results:
        fb.text("%-8s : %4d ms" % (name, ms), 70, y, 1)
        # 条形图
        w = min(220, ms * 220 // max(1, results[0][1]))
        fb.fill_rect(170, y + 1, w, 6, 1)
        y += 34
    epd.init()
    c.show("full")
    return results


def t_partial(c, epd, seconds=12):
    """局部刷新（计数器 + 进度条），验证残影表现。"""
    fb = c.fb
    fb.fill(0)
    fb.rect(0, 0, WIDTH, HEIGHT, 1)
    draw_center(fb, "PARTIAL UPDATE", 8, 1, 2)
    fb.hline(20, 32, WIDTH - 40, 1)
    fb.text("count:", 24, 60, 1)
    fb.text("time :", 24, 180, 1)
    fb.rect(20, 220, 360, 24, 1)
    fb.text("(full refresh every 25 frames)", 24, 256, 1)

    epd.init()
    c.show("full")

    print("[partial] running %ds ..." % seconds)
    t0 = time.ticks_ms()
    end = time.ticks_add(t0, int(seconds * 1000))
    n = 0
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        elapsed = time.ticks_diff(time.ticks_ms(), t0)
        ratio = elapsed / float(seconds * 1000)
        if ratio > 1.0:
            ratio = 1.0

        # 清掉旧数字区域再画新的
        fb.fill_rect(110, 50, 240, 56, 0)
        draw_text(fb, "%d" % n, 120, 50, 1, 6)

        fb.fill_rect(110, 178, 160, 30, 0)
        draw_text(fb, "%d.%ds" % (elapsed // 1000, (elapsed % 1000) // 100),
                  120, 180, 1, 3)

        # 进度条
        fb.fill_rect(21, 221, 358, 22, 0)
        fb.fill_rect(21, 221, int(358 * ratio), 22, 1)

        c.show("partial")
        n += 1

        # 定期全刷，清掉累积残影
        if n % 25 == 0:
            epd.init()
            c.show("full")

    print("[partial] %d frames in %ds" % (n, seconds))
    return n


def t_init_check(c, epd):
    """对比 init() 与 init_min() 两种初始化参数的效果。"""
    for name, fn in (("init (full SSD1619)", epd.init),
                     ("init_min (Waveshare V2)", epd.init_min)):
        fb = c.fb
        fb.fill(0)
        fb.rect(0, 0, WIDTH, HEIGHT, 1)
        draw_center(fb, name, 24, 1, 2)
        fb.hline(30, 60, WIDTH - 60, 1)
        dither_rect(fb, 40, 90, 320, 60, 8)
        draw_center(fb, "ABCDEFGHIJKLM", 170, 1, 3)
        draw_center(fb, "0123456789 !@#$%", 210, 1, 1)
        for i in range(6):
            fb.fill_rect(40 + i * 55, 240, 40, 30, 1)
        fn()
        ms = c.show("full")
        print("[init] %-24s = %d ms" % (name, ms))
        time.sleep_ms(1500)
    return None


def t_done(c, epd):
    fb = c.fb
    fb.fill(0)
    fb.rect(0, 0, WIDTH, HEIGHT, 1)
    draw_center(fb, "ALL TESTS", 70, 1, 3)
    draw_center(fb, "DONE", 110, 1, 3)
    fb.hline(80, 150, WIDTH - 160, 1)
    draw_center(fb, "if the screen looks correct,", 170, 1, 1)
    draw_center(fb, "your wiring + driver are OK", 186, 1, 1)
    fb.text("next: write your reader app :)", 60, 250, 1)
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
        except Exception as e:      # 该 SPI id 不可用就换下一个
            last = e
    raise last


def setup():
    """初始化 SPI + 驱动，返回 (epd, spi, canvas)。"""
    spi = make_spi()
    epd = EPD(
        spi,
        Pin(PIN_CS, Pin.OUT),
        Pin(PIN_DC, Pin.OUT),
        Pin(PIN_RST, Pin.OUT),
        Pin(PIN_BUSY, Pin.IN),
    )
    print("init e-paper ...")
    epd.init()
    c = Canvas(epd)
    print("ready: %dx%d, row_bytes=%d" % (epd.width, epd.height, epd.row_bytes))
    return epd, spi, c


TESTS = (
    ("info", t_info),
    ("shapes", t_shapes),
    ("font", t_font),
    ("gray", t_gray),
    ("align", t_align),
    ("init", t_init_check),
    ("refresh", t_refresh),
    ("partial", t_partial),
    ("done", t_done),
)


def run_all(pause=1.2, do_sleep=False):
    """依次跑完所有测试。pause=每步之间的停留秒数。"""
    epd, spi, c = setup()
    for name, fn in TESTS:
        print("==== %s ====" % name)
        try:
            fn(c, epd)
        except Exception as e:
            print("!! %s failed: %r" % (name, e))
        try:
            time.sleep(pause)
        except Exception:
            pass
    if do_sleep:
        epd.sleep()
        print("e-paper sleeping")
    print("run_all finished")


def menu():
    """交互式菜单，可在 REPL 里逐项测试。"""
    epd, spi, c = setup()
    names = [n for n, _ in TESTS]
    while True:
        print("\n=== EPD Test Menu ===")
        for i, (n, _) in enumerate(TESTS):
            print("  %d) %s" % (i + 1, n))
        print("  q) quit")
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
            print("invalid choice")
            continue
        try:
            hit(c, epd)
        except Exception as e:
            print("!! failed: %r" % e)
    print("bye")


def sleep_now(epd):
    epd.sleep()


if __name__ == "__main__":
    run_all()
