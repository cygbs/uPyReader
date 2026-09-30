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
#             ⚠ 37 尤其不能用: 它是 Octal-PSRAM 的 DQS
#    * 39-42  JTAG
#    * 43,44  UART0
#    * 0,3,45,46  strapping(启动模式)
#    * 48     板载 WS2812 三色 LED 的数据脚, 拿去做 I2C 会随机闪灯(见 DS3231 一节)
# ===========================================================================

# ---- 墨水屏 ----
EPD_SCK  = 12
EPD_MOSI = 11
# 墨水屏只用 SDI(MOSI), 不用 MISO。注意: ESP32-S3 的 SPI(1)=SPI2_HOST 默认 MISO
# 是 GPIO13, 而 GPIO13 要留给 TF 卡的 SDMMC CLK; 所以 epdlut.make_spi() 里显式传
# miso=None, 让 SPI 主机干脆不占任何 MISO 脚(传 None 后 repr 显示 miso=-1)。不指定
# 的话, 每次创建/重建 SPI(1) 都会把 GPIO13 抢去当 MISO, TF 卡就没时钟了。
EPD_CS   = 10
EPD_DC   = 9
EPD_RST  = 8
EPD_BUSY = 7
EPD_SPI_ID = 1
# 墨水屏 SPI 时钟: SSD1619 额定 20MHz。面包板实测 20MHz 稳定(write_ram 15000B
# 从 4MHz 的 30ms 降到 6ms)。若某些板子/飞线出现花屏, 逐级降到 10MHz / 4MHz。
EPD_SPI_BAUD = 20_000_000

# ---- 旋转编码器 ----
ENC_A   = 4
ENC_B   = 5
ENC_KEY = 6
ENC_STEPS_PER_DETENT = 4     # 每"一格"包含的正交跳变数
                             # 手感不对时用 main.encoder_debug() 校准:
                             #   一格打印 4 次 -> 4, 2 次 -> 2, 1 次 -> 1
ENC_LONG_MS = 800            # 长按判定(ms)

# ===========================================================================
#  microSD TF 卡 —— 原生 SDMMC 4-bit (ESP32-S3), SPI 作为后备
# ---------------------------------------------------------------------------
#   模块丝印    含义          GPIO      本文件变量
#   VDD         电源          见下       —
#   VSS         地            GND
#   CLK         时钟          GPIO13    SD_CLK
#   CMD         命令          GPIO14    SD_CMD
#   DAT0        数据 0        GPIO15    SD_D0
#   DAT1        数据 1        GPIO16    SD_D1
#   DAT2        数据 2        GPIO17    SD_D2
#   DAT3        数据 3        GPIO18    SD_D3
#   SD-CD       卡检测(可选)  GPIO21    SD_CD
#
#   用 machine.SDCard(slot=SD_SLOT=1) = 原生 SDMMC 主机: 屏幕走 SPI(1)=
#   SPI2_HOST, 两者互不干扰; ESP32-S3 的 SDMMC 经 GPIO matrix 可任意布线。
#   4-bit 失败自动降 1-bit(只用 DAT0)。
#
#   关于速度: 本板 N16R8 的 8MB Octal-PSRAM 与 SDMMC 的 DMA 存在带宽争用,
#   MicroPython 堆又在 PSRAM 上, 实测顺序读约 0.9 MB/s (见 esp-idf issue #11628);
#   对阅读器"每页只读 4KB"的用法绰绰有余, 不是卡/模块的问题。
#
#   供电: 带 AMS1117/电平转换的模块接 **5V**; 裸 3.3V 模块接 3V3。信号脚一律 3.3V。
#   ESP32-S3 SDMMC 官方建议 CMD/DAT 加 10k 外部上拉(DAT3 尤其), 裸转接也能跑。
#   卡里用 PC 格式化 FAT32 + MBR 分区表即可, FatFs 会自动解析分区表。
# ===========================================================================
SD_MOUNT = "/sd"
SD_SLOT  = 1                  # 1 = 原生 SDMMC (0 亦可)
SD_WIDTH = 4                  # 4 = DAT0..DAT3; 失败会自动降为 1
SD_CLK  = 13
SD_CMD  = 14
SD_D0   = 15
SD_D1   = 16
SD_D2   = 17
SD_D3   = 18
SD_CD   = None                # 卡检测脚: 本模块悬空, 代码未启用; 21 已让位给 DS3231 的 SCL
# 数据阶段依次降频重试(卡初始化阶段固件自己用 400kHz, 与这里无关)
SD_FREQS = (20_000_000, 10_000_000, 5_000_000, 1_000_000)

# ===========================================================================
#  DS3231 高精度 I2C 实时时钟(TCXO 温度补偿 + CR2032 掉电走时)
# ---------------------------------------------------------------------------
#   模块丝印   含义                   接到        本文件变量
#   VCC        电源 3.3V              3V3         —
#   GND        地                     GND         —
#   SDA        数据                   GPIO47      DS3231_SDA
#   SCL        时钟                   GPIO21      DS3231_SCL
#   SQW        方波/闹钟中断输出       不接        —
#   32K        32.768kHz 输出         不接        —
#
#   ⚠ VCC 必须接 3V3, 不要接 5V: ZS-042 类模块的上拉电阻挂在 VCC 上, 接 5V 会把
#     SDA/SCL 拉到 5V, 而 ESP32-S3 的 IO 不耐 5V。接 3.3V 时上拉即为 3.3V, 安全;
#     模块自带上拉(约 4.7k), 无需外加。
#   ⚠ 不要用 GPIO48: 它是板载 WS2812 三色 LED 的数据脚, I2C 时钟会被 LED 当成
#     颜色数据随机点亮(不是故障, 但很晃眼)。
#   ⚠ GPIO19/20 是 USB D-/D+, 占了会当场断掉串口(REPL/上传), 不能用。
#   ⚠ GPIO37 是 Octal-PSRAM 的 DQS, 不能用。
#   总线地址: DS3231=0x68, 模块板上 EEPROM(AT24C32)=0x57(用不到, 不冲突)。
# ===========================================================================
DS3231_I2C_ID = 0
DS3231_SDA = 47
DS3231_SCL = 21
DS3231_FREQ = 100_000
DS3231_ADDR = 0x68

# ---- 屏幕 / 字库 ----
FONT_CANDIDATES = (
    "/fonts/unifont16.bin",
    "fonts/unifont16.bin",
    "assets/fonts/unifont16.bin",
)
