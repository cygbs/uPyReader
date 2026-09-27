# -*- coding: utf-8 -*-
# epd_ssd1619.py
# MicroPython 驱动：HINK-E042A13-A0  4.2"  400x300  黑白电子墨水屏
# 控制芯片：SSD1619（部分货源标注 UC8151D，二者指令集同族，可互换）
#
# 指令集参照：
#   - EastRising ER-EPM042A1-1B（SSD1619 完整初始化，见 init()——默认，背景干净）
#   - Waveshare 4.2" e-Paper V2 官方驱动（最小初始化，见 init_min()）
#
# 像素格式：每行 50 字节，MSB 在前；一个位 = 1 表示白色，= 0 表示黑色。
#           (写入 0xFF => 全白，0x00 => 全黑)
#
# 刷新方式：
#   init()                完整初始化(载入 OTP 全刷波形)
#   display(buf)          整帧全刷(0x22=0xF7, 约 3.5s, 会闪, 用于清残影/首屏)
#   display_lut(buf,lut)  用自定义 LUT 局刷(0x22=0xCF, 不闪), LUT 见 epdlut.py
#   sleep()               深度睡眠
#
# 说明：这块屏的 OTP 只有全刷波形，想不闪必须先用 epdlut 从 OTP 读回、裁出一张
#       短波形再写进 LUT 寄存器(0x32)，然后 0x22 用 0xCF(不带 LOAD_LUT, 否则会
#       被 OTP 波形覆盖)。

import time
from machine import Pin, SPI


class EPD_SSD1619:
    EPD_WIDTH = 400
    EPD_HEIGHT = 300

    def __init__(self, spi, cs, dc, rst, busy,
                 width=EPD_WIDTH, height=EPD_HEIGHT):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.busy = busy
        self.width = width
        self.height = height
        self.row_bytes = (width + 7) // 8          # 400 // 8 = 50
        self._hibernated = False
        # 初始化时用的 Border Waveform / Display Update Control 1,
        # 全刷前需要恢复这两个寄存器。
        self._border = 0x01
        self._ctrl21 = b"\x80"

    # ---------------------------------------------------------------- 底层
    def _reset(self):
        self.rst.value(1)
        time.sleep_ms(100)
        self.rst.value(0)
        time.sleep_ms(2)
        self.rst.value(1)
        time.sleep_ms(100)

    def _cmd(self, c):
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes((c,)))
        self.cs.value(1)

    def _data(self, d):
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(bytes((d,)))
        self.cs.value(1)

    def _wait_busy(self, timeout_s=10):
        t0 = time.ticks_ms()
        while self.busy.value() == 1:              # HIGH=忙, LOW=空闲
            if time.ticks_ms() - t0 > timeout_s * 1000:
                raise RuntimeError('e-Paper busy timeout')
            time.sleep_ms(20)

    def _write_ram(self, buf):
        """整块写入 RAM：DC=1，CS=0，一次性 SPI 写完整帧。"""
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(buf)
        self.cs.value(1)

    # ---------------------------------------------------------------- 初始化
    def init(self):
        """SSD1619 完整初始化（EastRising 官方例程）：显式设置模拟/数字块
        控制(0x74/0x7E)、VCOM(0x2B)、软启动(0x0C)和内部温度传感器，
        确保驱动电压轨正确 -> 背景干净、对比度好。这是默认初始化。
        窗口方向用 Y 0..299（与整帧顺序写入一致，画面不倒置）。"""
        self._border = 0x01
        self._ctrl21 = b"\x80"
        self._reset()
        self._cmd(0x12); self._wait_busy(); time.sleep_ms(5)   # SWRESET
        self._cmd(0x74); self._data(0x54)          # Analog Block Control
        self._cmd(0x7E); self._data(0x3B)          # Digital Block Control
        self._cmd(0x2B); self._data(0x04); self._data(0x63)   # ACVCOM 设置
        self._cmd(0x0C)                            # Soft Start 软启动
        self._data(0x8E); self._data(0x8C); self._data(0x85); self._data(0x3F)
        self._cmd(0x01); self._data(0x2B); self._data(0x01); self._data(0x00)  # MUX 300
        self._cmd(0x11); self._data(0x03)          # Data Entry Mode (X+ Y+)
        self._cmd(0x44); self._data(0x00); self._data(0x31)   # RAM X 0..399
        self._cmd(0x45); self._data(0x00); self._data(0x00); self._data(0x2B); self._data(0x01)  # RAM Y 0..299
        self._cmd(0x4E); self._data(0x00)          # RAM X 计数器
        self._cmd(0x4F); self._data(0x00); self._data(0x00)   # RAM Y 计数器
        self._cmd(0x3C); self._data(self._border)  # Border Waveform: HIZ
        self._cmd(0x21); self._data(self._ctrl21[0])  # Display Update Control 1: RAM 内容
        self._cmd(0x18); self._data(0x80)          # 内部温度传感器
        self._cmd(0x22); self._data(0xB1)          # Load temperature and waveform
        self._cmd(0x20)                            # Master Activation
        self._wait_busy()
        self._hibernated = False
        return self

    def init_min(self):
        """Waveshare 4.2" V2 风格最小初始化（备用；默认用 init()）。
        不同批次的模组若用 init() 显示异常, 可在 REPL 里换成这个试试。"""
        self._border = 0x05
        self._ctrl21 = b"\x40\x00"
        self._reset()
        self._wait_busy()
        self._cmd(0x12); self._wait_busy()         # SWRESET
        self._cmd(0x21)                            # Display Update Control 1
        for b in self._ctrl21:
            self._data(b)
        self._cmd(0x3C); self._data(self._border)  # Border Waveform
        self._cmd(0x11); self._data(0x03)          # Data Entry Mode (X+ Y+)
        self._cmd(0x44); self._data(0x00); self._data(0x31)   # RAM X 0..399
        self._cmd(0x45); self._data(0x00); self._data(0x00); self._data(0x2B); self._data(0x01)
        self._cmd(0x4E); self._data(0x00)          # RAM X 计数器
        self._cmd(0x4F); self._data(0x00); self._data(0x00)   # RAM Y 计数器
        self._wait_busy()
        self._hibernated = False
        return self

    # ---------------------------------------------------------------- 窗口/寄存器
    def _set_window(self, x0, y0, x1, y1):
        """设置 RAM 窗口与写入计数器(像素坐标)。
        注意: SSD1619 的 X 地址以【字节】为单位(400px -> 0..49),
        Y 地址以【像素】为单位(0..299)。"""
        xb0 = x0 >> 3
        xb1 = x1 >> 3
        self._cmd(0x44)
        self._data(xb0); self._data(xb1)
        self._cmd(0x45)
        self._data(y0 & 0xFF); self._data((y0 >> 8) & 0xFF)
        self._data(y1 & 0xFF); self._data((y1 >> 8) & 0xFF)
        self._cmd(0x4E)
        self._data(xb0)
        self._cmd(0x4F)
        self._data(y0 & 0xFF); self._data((y0 >> 8) & 0xFF)

    def _setup_full(self):
        """全刷前恢复初始化时的 0x3C / 0x21。"""
        self._cmd(0x3C); self._data(self._border)
        self._cmd(0x21)
        for b in self._ctrl21:
            self._data(b)

    def _write_lut(self, lut):
        """把自定义波形表写进 LUT 寄存器(0x32)。"""
        self._cmd(0x32)
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(lut)
        self.cs.value(1)

    # ---------------------------------------------------------------- 显示
    def display(self, buf):
        """整帧全刷。buf: row_bytes*height 字节，位=1 白色，位=0 黑色。
        波形 0x22=0xF7(带 LOAD_LUT), 对比度最好但约 3.5s 且会闪；
        连续局刷后用它清残影。"""
        if self._hibernated:
            self.init()
        self._setup_full()
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._cmd(0x24)                            # WRITE RAM
        self._write_ram(buf)
        self._refresh_full()

    def display_lut(self, buf, lut, prev=None):
        """用自定义 LUT 局刷(不闪)。lut 见 epdlut.py。

        prev: 面板当前正在显示的那一帧。SSD16xx 的局刷是拿 RAM 0x26(上一帧)
        和 0x24(当前帧)做差分的, 刷新前要先把上一帧写进 0x26, 否则会把更早的
        画面当成基线, 翻页时冒出旧内容。
        0x22 用 0xCF(MODE1|MODE2, 不 LOAD_LUT) —— 带 LOAD_LUT 会被 OTP 覆盖。
        """
        if self._hibernated:
            self.init()
        self._write_lut(lut)
        if prev is not None:
            self._set_window(0, 0, self.width - 1, self.height - 1)
            self._cmd(0x26)                        # WRITE RAM (上一帧 / 基线)
            self._write_ram(prev)
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._cmd(0x24)                            # WRITE RAM (当前帧)
        self._write_ram(buf)
        self._cmd(0x22); self._data(0xCF)
        self._cmd(0x20)
        self._wait_busy()

    def _refresh_full(self):
        self._cmd(0x22); self._data(0xF7)          # 全屏刷新波形
        self._cmd(0x20)                            # Master Activation
        self._wait_busy()

    def sleep(self):
        """进入深度睡眠（省电）。再次显示前会自动重新 init()。"""
        self._cmd(0x10)                            # Deep Sleep
        self._data(0x01)
        time.sleep_ms(10)
        self._hibernated = True
