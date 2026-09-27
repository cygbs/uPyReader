# -*- coding: utf-8 -*-
# epd_ssd1619.py
# MicroPython 驱动：HINK-E042A13-A0  4.2"  400x300  黑白电子墨水屏
# 控制芯片：SSD1619（部分货源标注 UC8151D，二者指令集同族，可互换）
#
# 指令集参照：
#   - EastRising ER-EPM042A1-1B（SSD1619 完整初始化，见 init()——默认，背景干净）
#   - Waveshare 4.2" e-Paper V2 官方驱动（最小初始化，见 init_min()）
#   - Good Display GDEH042Z96 / gao19970120/esp32-epaper-weather（同型号实测）
#
# 像素格式：每行 50 字节，MSB 在前；一个位 = 1 表示白色，= 0 表示黑色。
#           (写入 0xFF => 全白，0x00 => 全黑)

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
        self._fast = False                          # 记录上次用的快速模式
        # 初始化时用的 Border Waveform / Display Update Control 1,
        # 供全刷前恢复(局部刷新会临时改这两个寄存器)
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
        """整块写入 RAM：DC=1，CS=0，一次性 SPI 写完整帧"""
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
        self._fast = False
        return self

    def init_min(self):
        """Waveshare 4.2" V2 风格最小初始化（对 SSD1619 / UC8176 通用，
        已在 HINK-E042A13-A0 上实测可用）。默认全刷波形，对比度最好。"""
        self._border = 0x05
        self._ctrl21 = b"\x40\x00"
        self._reset()
        self._wait_busy()
        self._cmd(0x12)                            # SWRESET 软件复位
        self._wait_busy()
        self._cmd(0x21)                            # Display Update Control 1
        for _b in self._ctrl21:
            self._data(_b)
        self._cmd(0x3C)                            # Border Waveform
        self._data(self._border)
        self._cmd(0x11)                            # Data Entry Mode (X+ Y+)
        self._data(0x03)
        self._cmd(0x44)                            # RAM X 0..399
        self._data(0x00)
        self._data(0x31)
        self._cmd(0x45)                            # RAM Y 0..299
        self._data(0x00)
        self._data(0x00)
        self._data(0x2B)
        self._data(0x01)
        self._cmd(0x4E)                            # RAM X 计数器 = 0
        self._data(0x00)
        self._cmd(0x4F)                            # RAM Y 计数器 = 0
        self._data(0x00)
        self._data(0x00)
        self._wait_busy()
        self._hibernated = False
        self._fast = False
        return self

    def init_fast(self, seconds=1.0):
        """Waveshare 4.2" V2 官方快速模式初始化。
        seconds=1.0 -> 0x1A=0x5A（约 1 秒刷新）；seconds=1.5 -> 0x1A=0x6E。
        比 init() 的全刷快近一倍，配合 display(mode='fast') 使用。
        注意：快速波形残影略明显，长时间高频刷新时建议定期用一次全刷。"""
        self._border = 0x05
        self._ctrl21 = b"\x40\x00"
        self._reset()
        self._wait_busy()
        self._cmd(0x12)                            # SWRESET
        self._wait_busy()
        self._cmd(0x21)
        for _b in self._ctrl21:
            self._data(_b)
        self._cmd(0x3C)                            # Border Waveform
        self._data(self._border)
        self._cmd(0x1A)                            # 刷新时长档位
        self._data(0x5A if seconds <= 1.0 else 0x6E)
        self._cmd(0x22)                            # Load temperature value
        self._data(0x91)
        self._cmd(0x20)                            # Master Activation
        self._wait_busy()
        self._cmd(0x11)                            # Data Entry Mode (X+ Y+)
        self._data(0x03)
        self._cmd(0x44)                            # RAM X 0..399
        self._data(0x00)
        self._data(0x31)
        self._cmd(0x45)                            # RAM Y 0..299
        self._data(0x00)
        self._data(0x00)
        self._data(0x2B)
        self._data(0x01)
        self._cmd(0x4E)
        self._data(0x00)
        self._cmd(0x4F)
        self._data(0x00)
        self._data(0x00)
        self._wait_busy()
        self._hibernated = False
        self._fast = True
        return self

    def init_full(self):
        """= init() 的别名（兼容旧代码）。完整 SSD1619 初始化。"""
        return self.init()

    # ---------------------------------------------------------------- 窗口/寄存器
    def _set_window(self, x0, y0, x1, y1):
        """设置 RAM 窗口与写入计数器(像素坐标)。
        注意: SSD1619/UC8151D 的 X 地址以【字节】为单位(400px -> 0..49),
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
        """全刷/快刷前恢复初始化时的 0x3C / 0x21。"""
        self._cmd(0x3C); self._data(self._border)
        self._cmd(0x21)
        for b in self._ctrl21:
            self._data(b)

    def _setup_partial(self):
        """局部刷新前的寄存器状态(照 Waveshare 4.2" V2 官方序列):
        0x3C=0x80, 0x21=0x00 0x00 —— 意思是“不复位、不重新加载波形”,
        直接复用面板里已有的 LUT, 这才是真正的快刷路径。
        少了这两步, 局部刷新会退化成“整屏重画”, 又慢又闪。"""
        self._cmd(0x3C); self._data(0x80)
        self._cmd(0x21); self._data(0x00); self._data(0x00)
        self._cmd(0x3C); self._data(0x80)

    def _write_region(self, buf, x0, y0, x1, y1):
        """只把 buf 里 (x0,y0)-(x1,y1) 的字节写进 RAM。"""
        rb = self.row_bytes
        xb0 = x0 >> 3
        xb1 = x1 >> 3
        self.dc.value(1)
        self.cs.value(0)
        if xb0 == 0 and xb1 == rb - 1:
            # 整行宽 -> 在缓冲区里是连续的, 一次写完
            self.spi.write(buf[y0 * rb:(y1 + 1) * rb])
        else:
            n = xb1 - xb0 + 1
            for y in range(y0, y1 + 1):
                base = y * rb + xb0
                self.spi.write(buf[base:base + n])
        self.cs.value(1)

    # ---------------------------------------------------------------- 显示
    def display(self, buf, mode='full'):
        """整帧送显。buf: row_bytes*height 字节，位=1 白色，位=0 黑色。
        mode: 'full'    全屏刷新 0xF7（对比度最好，约 1.5~2s）
              'fast'    快速刷新 0xC7（约 1s，残影略重）
              'partial' 局部波形 0xFF（约 0.3~0.5s，但驱动整屏）
        如果只需要刷新一小块, 用 display_partial_rect() 会快得多。
        """
        if self._hibernated:
            # 上次用什么模式初始化，就再用什么模式唤醒，避免速度悄悄变回去
            if self._fast:
                self.init_fast(1.0)
            else:
                self.init()
        if mode == 'partial':
            self._setup_partial()
        else:
            self._setup_full()
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._cmd(0x24)                            # WRITE RAM (黑白)
        self._write_ram(buf)
        self._refresh(mode)

    def _write_lut(self, lut):
        """把自定义波形表写进 LUT 寄存器(0x32)。"""
        self._cmd(0x32)
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(lut)
        self.cs.value(1)

    def display_lut(self, buf, lut):
        """用自定义 LUT 送显(局刷/快刷波形)。

        lut 通常是启动时从面板 OTP 读回、再裁短的 76 字节波形(见 main.read_lut)。
        0x22 用 0xCF(MODE1|MODE2, 不 LOAD_LUT) —— 若带 LOAD_LUT(0xF7) 会用 OTP
        波形把刚写进去的自定义 LUT 覆盖掉。
        """
        if self._hibernated:
            self.init()
        self._write_lut(lut)
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._cmd(0x24)                            # WRITE RAM
        self._write_ram(buf)
        self._cmd(0x22)
        self._data(0xCF)
        self._cmd(0x20)
        self._wait_busy()

    def display_partial_rect(self, buf, x, y, w, h):
        """窗口局部刷新: 只写、只驱动 (x, y, w, h) 这块矩形, 其余像素不动。
        buf 仍然是整帧缓冲; x 会对齐到 8 的倍数。
        适合菜单光标移动、计时器、进度条这类小范围变化。"""
        if self._hibernated:
            self.init()
        x0 = x & ~7
        y0 = y
        x1 = x + w - 1
        if x1 > self.width - 1:
            x1 = self.width - 1
        y1 = y + h - 1
        if y1 > self.height - 1:
            y1 = self.height - 1
        if x1 < x0 or y1 < y0 or x1 < 0 or y1 < 0:
            return
        self._setup_partial()
        self._set_window(x0, y0, x1, y1)
        self._cmd(0x24)                            # WRITE RAM
        self._write_region(buf, x0, y0, x1, y1)
        self._refresh('partial')

    def clear(self, white=True, mode='full'):
        v = 0xFF if white else 0x00
        buf = bytes((v,)) * (self.row_bytes * self.height)
        self.display(buf, mode=mode)

    def _refresh(self, mode='full'):
        self._cmd(0x22)                            # Display Update Control 2
        if mode == 'fast':
            self._data(0xC7)                       # 快速刷新波形
        elif mode == 'partial':
            self._data(0xF8)                       # MODE2: 硬件快刷/局刷波形(快且不闪)
        else:
            self._data(0xF7)                       # 全屏刷新波形（默认）
        self._cmd(0x20)                            # Master Activation
        self._wait_busy()

    def sleep(self):
        """进入深度睡眠（省电）。再次显示前需重新 init()。"""
        self._cmd(0x10)                            # Deep Sleep
        self._data(0x01)
        time.sleep_ms(10)
        self._hibernated = True

    # ---------------------------------------------------------------- 工具
    @staticmethod
    def invert(buf):
        """framebuf 格式（1=前景黑） -> e-Paper 格式（1=白, 0=黑）"""
        return bytes(b ^ 0xFF for b in buf)
