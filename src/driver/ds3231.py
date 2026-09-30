# -*- coding: utf-8 -*-
# ds3231.py — DS3231 高精度 I2C 实时时钟驱动(只用时钟与温度, 不含闹钟)
#
# 为什么值得单独用一颗 RTC:
#   * ESP32-S3 掉电/重启后内部 RTC 就归零, 无法独立走时;
#   * DS3231 精度 ±2ppm(0~40°C), 自带 CR2032 电池可掉电走时,
#     内置 TCXO 靠片内温度传感器做温度补偿;
#   * 状态寄存器 0x0F 的 OSF 位记录"供电曾经丢失", 置位说明时间不可信。
#
# 寄存器(全部 BCD):
#   0x00 秒 | 0x01 分 | 0x02 时 | 0x03 周 | 0x04 日 | 0x05 月 | 0x06 年(2位)
#   0x0F 状态: bit7=OSF(掉电标志), bit3=EN32kHz ...
#   0x11 温度整数(有符号) | 0x12 高 2 位 = 小数, 步进 0.25°C
#   温度每 64 秒才刷新一次, 精度 ±3°C 且芯片自热会略偏高, 适合看趋势不适合精测。
#
# 接线/地址见 driver/hwconfig.py。用法:
#   from driver import ds3231
#   rtc = ds3231.DS3231()
#   if rtc.present():
#       print(rtc.datetime())      # (年, 月, 日, 周, 时, 分, 秒)
#       print(rtc.temperature())
#       rtc.set_datetime(2026, 9, 30, 3, 20, 30, 0)   # 周: 1=周一 .. 7=周日

from machine import I2C, Pin

from driver.hwconfig import (
    DS3231_I2C_ID, DS3231_SDA, DS3231_SCL, DS3231_FREQ, DS3231_ADDR,
)

REG_TIME = 0x00          # 秒/分/时/周/日/月/年, 共 7 字节
REG_STATUS = 0x0F        # bit7 = OSF(掉电标志)
REG_TEMP = 0x11          # 温度: 整数(有符号) + 高 2 位小数(0.25°C)


def _bcd2int(v):
    return (v >> 4) * 10 + (v & 0x0F)


def _int2bcd(v):
    return ((v // 10) << 4) | (v % 10)


class DS3231:
    def __init__(self, i2c_id=DS3231_I2C_ID, sda=DS3231_SDA, scl=DS3231_SCL,
                 freq=DS3231_FREQ, addr=DS3231_ADDR):
        self.i2c = I2C(i2c_id, sda=Pin(sda), scl=Pin(scl), freq=freq)
        self.addr = addr

    # ------------------------------------------------------------ 探测
    def present(self):
        """总线上能否读到本芯片(比 i2c.scan() 快, 只读 1 字节)。"""
        try:
            self.i2c.readfrom_mem(self.addr, REG_TIME, 1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ 时间
    def datetime(self):
        """返回 (年(4位), 月, 日, 周(1=周一..7=周日), 时, 分, 秒)。"""
        d = self.i2c.readfrom_mem(self.addr, REG_TIME, 7)
        sec = _bcd2int(d[0] & 0x7F)
        minute = _bcd2int(d[1] & 0x7F)
        hr = d[2]
        if hr & 0x40:                      # bit6=1 -> 12 小时制
            hour = _bcd2int(hr & 0x1F) % 12
            if hr & 0x20:                  # bit5=1 -> PM
                hour += 12
        else:
            hour = _bcd2int(hr & 0x3F)
        wday = d[3] & 0x07
        day = _bcd2int(d[4] & 0x3F)
        month = _bcd2int(d[5] & 0x1F)
        year = 2000 + _bcd2int(d[6])
        return (year, month, day, wday, hour, minute, sec)

    def set_datetime(self, year, month, day, wday, hour, minute, second):
        """写入时间并清掉 OSF(掉电标志)。wday: 1=周一 .. 7=周日。"""
        buf = bytes((
            _int2bcd(second & 0x7F), _int2bcd(minute & 0x7F),
            _int2bcd(hour & 0x3F), wday & 0x07,
            _int2bcd(day & 0x3F), _int2bcd(month & 0x1F),
            _int2bcd(year % 100),
        ))
        self.i2c.writeto_mem(self.addr, REG_TIME, buf)
        self.clear_osf()

    def set_from_localtime(self, tm=None):
        """用 time.localtime() 的元组设置(周几按 MicroPython 的 0=周一 自动 +1)。"""
        if tm is None:
            import time
            tm = time.localtime()
        self.set_datetime(tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5])

    # ------------------------------------------------------------ 温度 / 状态
    def temperature(self):
        """片内温度(°C, 0.25 步进)。每 64 秒才更新一次, 且芯片自热会略偏高。"""
        d = self.i2c.readfrom_mem(self.addr, REG_TEMP, 2)
        whole = d[0] - 256 if d[0] >= 128 else d[0]
        return whole + (d[1] >> 6) * 0.25

    def osf(self):
        """掉电标志: True 表示供电曾经丢失, 当前时间可能不准。"""
        return bool(self.i2c.readfrom_mem(self.addr, REG_STATUS, 1)[0] & 0x80)

    def clear_osf(self):
        """清状态寄存器(含 OSF 与闹钟标志)。"""
        self.i2c.writeto_mem(self.addr, REG_STATUS, b"\x00")

    def deinit(self):
        try:
            self.i2c.deinit()
        except Exception:
            pass
