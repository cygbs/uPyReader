# -*- coding: utf-8 -*-
# epdlut.py — 从 SSD1619 面板 OTP 读回波形表, 裁成"不闪的局刷"波形
#
# 背景: 这块屏出厂 OTP 里只有全刷波形(0x22=0xF7, 约 3.5s 且整屏闪)。要得到
# 不闪的局刷, 需要一张短波形写进 LUT 寄存器(0x32)。OTP 里的波形可以用 0x33
# 读回来 —— SSD1619 的 4 线 SPI 是半双工、只有一根数据线(SDI), 所以先释放
# SPI 外设, 再用 bit-bang 在同一根 SDI 上把波形读出来, 读完后重建 SPI 并重新
# 初始化面板。
#
# 用法:
#   from driver import epdlut
#   lut = epdlut.load(epd, rep=8)      # 76 字节局刷 LUT; 失败返回 None
#   canvas.show_lut(lut)               # 用这张 LUT 送显(见 ui/canvas.py)

import time
from machine import Pin, SPI
from driver.hwconfig import (EPD_SCK, EPD_MOSI, EPD_MISO, EPD_SPI_ID,
                             EPD_SPI_BAUD)

READ_BYTES = 97          # 0x33 一次多读几个字节; 7 字节 LUT 实为 76
LUT_BYTES = 76
VS_BYTES = 35            # 波形表头部: vs(电压选择)
GROUP_BYTES = 5          # 每个波形组 = 4 个阶段时间 + 1 个 repeat
GROUP_COUNT = 7
KEEP_GROUP = 3           # 只保留这一组
PHASES = (0x03, 0x02, 0x05, 0x00)   # 实测本屏驱动能力最强的一组阶段
DEFAULT_REP = 8          # repeat 越大字越"实"、越慢(每 +1 约 +0.2s)


def make_spi():
    """按 hwconfig 建 SPI 总线(优先 EPD_SPI_ID, 不行再试 2 / 1)。

    显式指定 miso: ESP32-S3 的 SPI(1) 默认 MISO=GPIO13, 而 GPIO13 是 TF 卡的
    SCK; 不指定的话重建 SPI(1) 会把 GPIO13 抢走, 导致 TF 卡读不了。
    """
    last = None
    for sid in (EPD_SPI_ID, 2, 1):
        try:
            return SPI(sid, baudrate=EPD_SPI_BAUD, polarity=0, phase=0,
                       sck=Pin(EPD_SCK), mosi=Pin(EPD_MOSI), miso=Pin(EPD_MISO))
        except Exception as e:
            last = e
    raise last


def _read_via_bitbang(epd, cmd, n):
    """在单线 SDI 上 bit-bang: 先发命令, 再逐位打时钟读回 n 字节。"""
    sck = Pin(EPD_SCK, Pin.OUT, value=0)
    sdi = Pin(EPD_MOSI, Pin.OUT, value=1)
    cs, dc = epd.cs, epd.dc

    def tx(b):
        for i in range(7, -1, -1):
            sdi.value((b >> i) & 1)
            sck.value(1)
            time.sleep_us(2)
            sck.value(0)
            time.sleep_us(2)

    out = bytearray()
    try:
        cs.value(0)
        dc.value(0)
        tx(cmd)
        dc.value(1)
        sdi.init(Pin.IN, Pin.PULL_UP)
        for _ in range(n):
            v = 0
            for _i in range(8):
                sck.value(1)
                time.sleep_us(2)
                v = (v << 1) | sdi.value()
                sck.value(0)
                time.sleep_us(2)
            out.append(v)
    finally:
        cs.value(1)
        try:
            sdi.init(Pin.OUT)
        except Exception:
            pass
    return bytes(out)


def read_otp_lut(epd, n=READ_BYTES):
    """读回面板当前加载的 OTP 波形(命令 0x33)。

    会先释放面板的 SPI, 读完后用 make_spi() 重建并重新 init 面板。
    失败返回 None。
    """
    try:
        epd.spi.deinit()
    except Exception:
        pass

    data = None
    try:
        data = _read_via_bitbang(epd, 0x33, n)
    except Exception as e:
        print("读 OTP LUT 失败:", e)
    finally:
        try:
            epd.spi = make_spi()
            epd.init()
        except Exception as e:
            print("恢复 SPI / 面板失败:", e)
            return None

    if not data or data[:4] in (b"\x00\x00\x00\x00", b"\xff\xff\xff\xff"):
        return None
    return data


def make_partial_lut(otp, rep=DEFAULT_REP):
    """把 OTP 全刷波形裁成单阶段局刷波形(不闪)。

    保留 OTP 的 vs(电压选择)与尾部电压/frame 参数, 只把 7 个波形组重写成
    KEEP_GROUP 这一组 PHASES、repeat=rep。
    """
    if not otp or len(otp) < LUT_BYTES:
        return None
    lut = bytearray(otp[:LUT_BYTES])
    for gi in range(GROUP_COUNT):
        base = VS_BYTES + gi * GROUP_BYTES
        for k in range(GROUP_BYTES):
            lut[base + k] = 0
    base = VS_BYTES + KEEP_GROUP * GROUP_BYTES
    lut[base + 0] = PHASES[0]
    lut[base + 1] = PHASES[1]
    lut[base + 2] = PHASES[2]
    lut[base + 3] = PHASES[3]
    lut[base + 4] = rep
    return bytes(lut)


def load(epd, rep=DEFAULT_REP):
    """一步到位: 读 OTP -> 裁成局刷 LUT。失败返回 None。"""
    return make_partial_lut(read_otp_lut(epd), rep)
