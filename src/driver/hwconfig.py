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
# 墨水屏只用 SDI(MOSI), 不用 MISO。切注意: ESP32-S3 的 SPI(1)=SPI2_HOST 默认 MISO
# 是 GPIO13, 而 GPIO13 是 TF 卡的 SCK; 所以 epdlut.make_spi() 里显式传 miso=None,
# 让 SPI 主机干脆不占任何 MISO 脚(传 None 后 repr 显示 miso=-1)。不指定的话, 每次
# 创建/重建 SPI(1) 都会把 GPIO13 抢去当 MISO, TF 卡就没时钟了(读子目录报 EIO)。
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
#  SPI TF 卡 (microSD, SPI 模式)
# ---------------------------------------------------------------------------
#   模块丝印    含义         GPIO      本文件变量
#   VCC         电源        见下       —
#   GND         地          GND
#   SCK/CLK     时钟        GPIO13    SD_SCK
#   MOSI/DI(SI) 数据出      GPIO17    SD_MOSI   <- 从 14 改到 17(排查)
#   MISO/DO(SO) 数据入      GPIO15    SD_MISO
#   CS          片选        GPIO16    SD_CS
#
#   屏幕占 machine.SPI(1) = SPI2_HOST, TF 卡单独用 machine.SPI(2) = SPI3_HOST:
#   两路硬件 SPI 主机互不干扰。不跟屏幕共用一组的另一个好处是屏幕是半双工
#   (只有 SDI), 而 TF 卡需要真正的 MOSI+MISO。
#
#   供电: 带 AMS1117/电平转换的模块要接 **5V** 才能稳定输出 3.3V(压差大);
#         裸 3.3V 模块接 3V3。信号脚一律 3.3V。
#   卡里用 PC 格式化 FAT32 + MBR 分区表即可, FatFs 会自动解析分区表。
# ===========================================================================
SD_SPI_ID = 2
SD_SCK  = 13
SD_MOSI = 17
SD_MISO = 15
SD_CS   = 16
# 数据阶段依次降频重试(卡初始化固定 100kHz, 与这里无关)
SD_FREQS = (20_000_000, 10_000_000, 5_000_000, 1_000_000)
SD_MOUNT = "/sd"

# ---- 屏幕 / 字库 ----
WIDTH  = 400
HEIGHT = 300
FONT_CANDIDATES = (
    "/fonts/unifont16.bin",
    "fonts/unifont16.bin",
    "assets/fonts/unifont16.bin",
)
