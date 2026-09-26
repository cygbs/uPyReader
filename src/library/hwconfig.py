# -*- coding: utf-8 -*-
# hwconfig.py
# 硬件接线的唯一配置源 —— 改引脚只改这里
#
# ===========================================================================
#  墨水屏 SSD1619 4.2" 400x300
# ---------------------------------------------------------------------------
#   屏幕丝印   含义             GPIO      本文件变量
#   3V3        电源 3.3V        (不接 5V)
#   GND        地               GND
#   SCLK       时钟             GPIO12    EPD_SCK
#   SDI        SPI 数据(MOSI)   GPIO11    EPD_MOSI
#   CS         片选             GPIO10    EPD_CS
#   D/C        数据/命令(DC)    GPIO9     EPD_DC
#   RES        复位(RST)        GPIO8     EPD_RST
#   BUSY       忙信号           GPIO7     EPD_BUSY
#
# ===========================================================================
#  旋转编码器(增量式, 带按键)
# ---------------------------------------------------------------------------
#   模块丝印  含义                       GPIO
#   5V        电源(接 3.3V 即可)        3V3
#   GND       地                         GND
#   S1        正交 A 相                  GPIO4     ENC_A
#   S2        正交 B 相                  GPIO5     ENC_B
#   KEY       按下时与 GND 接通(低有效)  GPIO6     ENC_KEY
#
#  接线就地取材即可, 但请避开这些被占用的 GPIO:
#    * 7-12   墨水屏
#    * 19,20  USB D-/D+
#    * 26-37  内部 Flash / Octal-PSRAM(N16R8 的 R8 用掉 33-37)
#    * 39-42  JTAG
#    * 43,44  UART0
#    * 0,3,45,46  strapping(启动模式)
# ===========================================================================

# ---- 墨水屏 ----
EPD_SCK  = 12
EPD_MOSI = 11
EPD_CS   = 10
EPD_DC   = 9
EPD_RST  = 8
EPD_BUSY = 7
EPD_SPI_ID = 1
EPD_SPI_BAUD = 4_000_000

# ---- 旋转编码器 ----
ENC_A   = 4
ENC_B   = 5
ENC_KEY = 6
ENC_STEPS_PER_DETENT = 4     # 每"一格"包含的正交跳变数
                             # 手感不对时用 main.encoder_debug() 校准:
                             #   一格打印 4 次 -> 4, 2 次 -> 2, 1 次 -> 1
ENC_LONG_MS = 800            # 长按判定(ms)

# ---- 屏幕 / 字库 ----
WIDTH  = 400
HEIGHT = 300
FONT_CANDIDATES = (
    "/fonts/unifont16.bin",
    "fonts/unifont16.bin",
    "assets/fonts/unifont16.bin",
)
