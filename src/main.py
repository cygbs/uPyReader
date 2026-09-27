# -*- coding: utf-8 -*-
"""
main.py — 墨水屏阅读器 主界面(设备开机自动运行)

硬件: ESP32-S3-N16R8 + SSD1619 4.2" 400x300 + 增量式旋转编码器
接线: 见 library/hwconfig.py

操作:
    旋转编码器  -> 上下选择
    按下按键    -> 确认(关于本机会进入子页面; 其余项暂只做视觉反馈)
    长按        -> 子页面里返回; 主界面暂未使用

REPL 辅助:
    import main; main.encoder_debug()    # 校准编码器手感 / 确认接线
    main.main()                          # 重新进入主界面
"""

import time
import sys
import os
from machine import Pin, SPI


# --------------------------------------------------------------------------- #
# 路径: 让 library/ 里的模块可导入
# --------------------------------------------------------------------------- #
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

from hwconfig import (
    EPD_SCK, EPD_MOSI, EPD_CS, EPD_DC, EPD_RST, EPD_BUSY,
    EPD_SPI_ID, EPD_SPI_BAUD,
    ENC_A, ENC_B, ENC_KEY, ENC_STEPS_PER_DETENT, ENC_LONG_MS,
    WIDTH, HEIGHT, FONT_CANDIDATES,
)
from epd_ssd1619 import EPD_SSD1619
from unifont import Unifont
from rotary import Rotary, PRESS, RELEASE, CLICK, LONG
import ui
import sysinfo
import about


APP_VERSION = "v0.1"

LIST_TOP = 26            # 列表起始 y
ROW_H = 46               # 行高
PARTIAL_LIMIT = 15       # 连续局刷多少次后插一次全刷(清残影)
TOAST_MS = 1500          # 按下后的提示停留时间
FOOT_HINT = "旋转选择   按下确认"


# --------------------------------------------------------------------------- #
# 菜单项与右侧提示
# --------------------------------------------------------------------------- #
def hint_reading():
    return "无记录"


def hint_files():
    return "内部存储"


def hint_chip():
    return sysinfo.chip_name()


def hint_fw():
    return "MicroPython"


def hint_plugins():
    return "%d 个" % count_plugins()


MENU = (
    ("继续阅读", hint_reading),
    ("浏览文件", hint_files),
    ("关于本机", hint_chip),
    ("固件设置", hint_fw),
    ("插件", hint_plugins),
)
IDX_ABOUT = 2


# --------------------------------------------------------------------------- #
# 硬件初始化
# --------------------------------------------------------------------------- #
def make_spi():
    last = None
    for sid in (EPD_SPI_ID, 2, 1):
        try:
            return SPI(sid, baudrate=EPD_SPI_BAUD, polarity=0, phase=0,
                       sck=Pin(EPD_SCK), mosi=Pin(EPD_MOSI))
        except Exception as e:
            last = e
    raise last


def find_font():
    for p in FONT_CANDIDATES:
        try:
            os.stat(p)
            return p
        except OSError:
            pass
    return None


def count_plugins():
    """统计 /plugins 下的一级子目录数量(仅用于主界面显示)。"""
    for base in ("/plugins", "plugins"):
        try:
            entries = os.ilistdir(base)
        except OSError:
            continue
        except AttributeError:          # 极老的固件没有 ilistdir
            try:
                return len(os.listdir(base))
            except OSError:
                continue
        n = 0
        for e in entries:
            if len(e) > 1 and (e[1] & 0x4000):
                n += 1
        return n
    return 0


def setup():
    """初始化屏 + 字库, 返回 (epd, spi, canvas)。"""
    spi = make_spi()
    epd = EPD_SSD1619(
        spi,
        Pin(EPD_CS, Pin.OUT),
        Pin(EPD_DC, Pin.OUT),
        Pin(EPD_RST, Pin.OUT),
        Pin(EPD_BUSY, Pin.IN),
    )
    print("init e-paper ...")
    epd.init()

    path = find_font()
    if path is None:
        raise OSError("找不到字库 unifont16.bin。"
                      "请先在 PC 上运行 tools/build_font.py, 再用 tools/upload.sh 上传")
    font = Unifont(path)
    print("font: %s (%d 字形, 行高 %d)"
          % (path, len(font.misc) + font.cjk_count, font.line_height))

    return epd, spi, ui.Canvas(epd, font)


# --------------------------------------------------------------------------- #
# 界面
# --------------------------------------------------------------------------- #
def build_hints():
    return [fn() for _, fn in MENU]


def draw_main(c, index, hints):
    # 必须先清屏: 只刷新局部窗口, 否则旧的选中项反白条会残留在缓冲区里
    # (framebuf.fill 是 C 层实现, 15000 字节开销可忽略)
    c.fb.fill(0)
    ui.title_bar(c, "阅读器主菜单", APP_VERSION)
    ui.draw_list(c, [t for t, _ in MENU], index, LIST_TOP, ROW_H, hints)
    # 底部提示保持静态(不放会变化的计数), 这样移动光标时只需刷新列表那两行
    ui.draw_footer(c, FOOT_HINT)


def item_band(i):
    """第 i 项占据的 y 区间(半开)。"""
    y0 = LIST_TOP + i * ROW_H
    return (y0, y0 + ROW_H)


def footer_band(c):
    lh = c.font.line_height
    return (c.height - lh - 12, c.height)


def refresh_bands(c, bands):
    """把脏区 y 区间合并后做一次窗口局部刷新。返回刷新的窗口数(总是 1)。

    先合并相邻区间(光标移一格 -> 两个相邻行合并成一条, 只驱动 ~2 行高度);
    如果还有不相邻的区间(例如从最后一项回绕到第一项), 再合并成一个大窗口 ——
    因为局部波形的一次激活耗时基本固定, 一次扫完比分两次激活更快。
    """
    bs = sorted(b for b in bands if b and b[1] > b[0])
    if not bs:
        return 0
    merged = []
    for y0, y1 in bs:
        if merged and y0 <= merged[-1][1]:
            if y1 > merged[-1][1]:
                merged[-1][1] = y1
        else:
            merged.append([y0, y1])
    if len(merged) > 1:
        merged = [[merged[0][0], merged[-1][1]]]
    c.show_rect(0, merged[0][0], c.width, merged[0][1] - merged[0][0])
    return 1


def show_toast(c, left, right=None):
    ui.draw_footer(c, left, right)
    y0, y1 = footer_band(c)
    c.show_rect(0, y0, c.width, y1 - y0)


def open_about(c):
    """进入"关于本机"。"""
    about.draw(c)
    return c.show("full")


# --------------------------------------------------------------------------- #
# 主循环
# --------------------------------------------------------------------------- #
def main():
    epd, spi, c = setup()
    enc = Rotary(ENC_A, ENC_B, ENC_KEY,
                 steps_per_detent=ENC_STEPS_PER_DETENT, long_ms=ENC_LONG_MS)

    hints = build_hints()
    index = 0
    screen = "menu"
    draw_main(c, index, hints)
    ms = c.show("full")
    print("主界面就绪(首屏 %d ms)。旋转=选择, 按下=确认。" % ms)

    partial_n = 0
    toast_until = 0

    try:
        while True:
            enc.update()
            d = enc.take_steps()
            ev = enc.take_events()

            if screen == "menu":
                # ---- 旋转: 移动光标(只刷新受影响的那两行) ----
                if d:
                    old = index
                    index = (index + d) % len(MENU)
                    draw_main(c, index, hints)
                    bands = [item_band(old), item_band(index)]
                    if toast_until:
                        bands.append(footer_band(c))     # 顺带把提示恢复掉
                        toast_until = 0
                    partial_n += refresh_bands(c, bands)
                    if partial_n >= PARTIAL_LIMIT:       # 定期全刷清残影
                        partial_n = 0
                        c.show("full")

                # ---- 按键 ----
                if ev & CLICK:
                    if index == IDX_ABOUT:
                        open_about(c)
                        screen = "about"
                    else:
                        show_toast(c, "已选择：%s" % MENU[index][0],
                                   "子页面待实现")
                        toast_until = time.ticks_add(time.ticks_ms(), TOAST_MS)
                elif ev & LONG:
                    show_toast(c, "长按(暂未使用)", "返回")
                    toast_until = time.ticks_add(time.ticks_ms(), TOAST_MS)

                # ---- 提示超时后只恢复底部那一小条 ----
                if toast_until and time.ticks_diff(time.ticks_ms(), toast_until) >= 0:
                    draw_main(c, index, hints)
                    refresh_bands(c, [footer_band(c)])
                    toast_until = 0

            else:
                # ---- 关于本机: 按一下或长按都返回主界面 ----
                if ev & (CLICK | LONG):
                    screen = "menu"
                    toast_until = 0
                    hints = build_hints()        # 插件数量可能刚变化
                    draw_main(c, index, hints)
                    c.show("full")

            time.sleep_ms(5)

    except KeyboardInterrupt:
        print("主界面退出")
        try:
            epd.sleep()
        except Exception:
            pass


def encoder_debug(seconds=20):
    """编码器自检: 校准 ENC_STEPS_PER_DETENT / 确认接线。"""
    Rotary(ENC_A, ENC_B, ENC_KEY, steps_per_detent=1,
           long_ms=ENC_LONG_MS).debug(seconds)


if __name__ == "__main__":
    main()
