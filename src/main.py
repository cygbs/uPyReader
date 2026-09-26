# -*- coding: utf-8 -*-
"""
main.py — 墨水屏阅读器 主界面(设备开机自动运行)

硬件: ESP32-S3-N16R8 + SSD1619 4.2" 400x300 + 增量式旋转编码器(带按键)
接线: 见 library/hwconfig.py

操作:
    旋转编码器  -> 上下选择
    按下按键    -> 确认(当前只做视觉反馈, 子页面待实现)

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


APP_VERSION = "v0.1"

# --------------------------------------------------------------------------- #
# 主菜单内容
#   hint = None 表示运行时计算
# --------------------------------------------------------------------------- #
MENU = (
    ("继续阅读", "无记录"),
    ("浏览文件", "内部存储"),
    ("关于本机", "ESP32-S3-N16R8"),
    ("固件设置", "MicroPython"),
    ("插件", None),
)

LIST_TOP = 26            # 列表起始 y
ROW_H = 46               # 行高
PARTIAL_LIMIT = 15       # 连续局刷多少次后插一次全刷(清残影)
TOAST_MS = 1500          # 按下后的提示停留时间
FOOT_HINT = "旋转选择   按下确认"


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
    out = []
    for _, hint in MENU:
        out.append(("%d 个" % count_plugins()) if hint is None else hint)
    return out


def draw_main(c, index, hints):
    # 必须先清屏: 局刷只刷新变化像素, 否则旧的选中项反白条会残留
    # (framebuf.fill 是 C 层实现, 15000 字节开销可忽略)
    c.fb.fill(0)
    ui.title_bar(c, "阅读器主菜单", APP_VERSION)
    ui.draw_list(c, [t for t, _ in MENU], index, LIST_TOP, ROW_H, hints)
    ui.draw_footer(c, FOOT_HINT, "%d/%d" % (index + 1, len(MENU)))


# --------------------------------------------------------------------------- #
# 主循环
# --------------------------------------------------------------------------- #
def main():
    epd, spi, c = setup()
    enc = Rotary(ENC_A, ENC_B, ENC_KEY,
                 steps_per_detent=ENC_STEPS_PER_DETENT, long_ms=ENC_LONG_MS)

    hints = build_hints()
    index = 0
    draw_main(c, index, hints)
    ms = c.show("full")
    print("主界面就绪(首屏 %d ms)。旋转=选择, 按下=确认。" % ms)

    partial_n = 0
    toast_until = 0

    try:
        while True:
            enc.update()

            # ---- 旋转: 移动光标 ----
            d = enc.take_steps()
            if d:
                index = (index + d) % len(MENU)
                draw_main(c, index, hints)
                toast_until = 0
                partial_n += 1
                if partial_n >= PARTIAL_LIMIT:       # 定期全刷清残影
                    partial_n = 0
                    c.show("full")
                else:
                    c.show("partial")

            # ---- 按键 ----
            ev = enc.take_events()
            if ev & CLICK:
                ui.draw_footer(c, "已选择：%s" % MENU[index][0], "子页面待实现")
                c.show("partial")
                toast_until = time.ticks_add(time.ticks_ms(), TOAST_MS)
            elif ev & LONG:
                ui.draw_footer(c, "长按(暂未使用)", "返回")
                c.show("partial")
                toast_until = time.ticks_add(time.ticks_ms(), TOAST_MS)

            # ---- 提示超时后恢复 ----
            if toast_until and time.ticks_diff(time.ticks_ms(), toast_until) >= 0:
                draw_main(c, index, hints)
                c.show("partial")
                toast_until = 0

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
