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

# ===========================================================================
#  SPI TF 卡（microSD，SPI 模式）
# ---------------------------------------------------------------------------
#   模块丝印   含义         GPIO      本文件变量
#   VCC        电源        (见下方说明)
#   GND        地          GND
#   SCK/CLK    时钟        GPIO13    SD_SCK
#   MOSI/CMD   数据出      GPIO14    SD_MOSI
#   MISO/D0    数据入      GPIO15    SD_MISO
#   CS/D3      片选        GPIO16    SD_CS
#
#   为什么用另一组引脚、而不是和屏幕共用 SPI：
#     MicroPython 的 machine.SDCard 在 SPI 模式下要求 **独占一个 SPI 主机**，
#     不能与其它 SPI 设备共用（源码里会直接报 "SPI bus already in use"）。
#     ESP32-S3 正好有两个可用主机：
#       屏幕 -> machine.SPI(1) = SPI2_HOST
#       TF 卡 -> SDCard(slot=2) = SPI3_HOST
#     所以两组引脚分开，但两个总线可以同时工作。
#
#   供电注意：很多 microSD 模块板载 AMS1117/电平转换，VCC 需要 **5V**
#     才能稳定输出 3.3V（AMS1117 压差大）。裸 3.3V 模块则接 3V3。
#     信号脚都是 3.3V 逻辑，不要接 5V 信号。
# ===========================================================================
SD_SCK  = 13
SD_MOSI = 14
SD_MISO = 15
SD_CS   = 16

# slot 2 -> SPI3_HOST（空闲）；slot 3 -> SPI2_HOST（被屏幕占用）。
# 仍按顺序尝试，万一以后改了 EPD_SPI_ID 也能自动选到空闲主机。
SD_SLOTS = (2, 3)
# 依次降频尝试，提高兼容性（杜邦线/长线/差模块先降频）
SD_FREQS = (20_000_000, 10_000_000, 4_000_000)
SD_MOUNT = "/sd"

# ---- 屏幕 / 字库 ----
WIDTH  = 400
HEIGHT = 300
FONT_CANDIDATES = (
    "/fonts/unifont16.bin",
    "fonts/unifont16.bin",
    "assets/fonts/unifont16.bin",
)
