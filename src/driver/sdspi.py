# -*- coding: utf-8 -*-
# sdspi.py — 纯 Python 的 SPI 模式 SD/TF 卡驱动
#
# 来源: MicroPython 官方 micropython-lib
#       micropython/drivers/storage/sdcard/sdcard.py  (MIT License)
#   本文件在其基础上做了少量调整: 增加 deinit() 与中文注释。
#   协议实现(CMD0/8/9/16/17/18/24/25/55/58、ACMD41、CRC7、数据令牌)
#   与原实现保持一致。
#
# 相比 machine.SDCard 的好处:
#   * 只需要一个 machine.SPI 对象, 不要求独占某个 SPI 主机 —— 因此可以用
#     machine.SPI(2)=SPI3_HOST, 与占用 SPI(1) 的墨水屏互不干扰;
#   * 每一步失败都会抛出带具体原因的 OSError
#     ("no SD card" / "couldn't determine SD card version" /
#      "timeout waiting for v2 card" / "can't set 512 block size" / EIO),
#     而不是像 machine.SDCard 那样 readblocks 只返回 -5 把原因吞掉;
#   * 初始化固定用 100 kHz, 数据阶段再切到指定频率, 高低速分开可控。
#
# 用法:
#   from machine import Pin, SPI
#   import os
#   from driver import sdspi
#   spi = SPI(2, sck=Pin(13), mosi=Pin(14), miso=Pin(15))
#   sd = sdspi.SDCard(spi, Pin(16), baudrate=10_000_000)
#   os.mount(sd, "/sd")

import time

try:
    from micropython import const
except ImportError:                    # 在 PC 上做语法检查时
    def const(x):
        return x

_CMD_TIMEOUT = const(100)

_R1_IDLE_STATE = const(1 << 0)
_R1_ILLEGAL_COMMAND = const(1 << 2)
_TOKEN_CMD25 = const(0xFC)
_TOKEN_STOP_TRAN = const(0xFD)
_TOKEN_DATA = const(0xFE)


def _crc7(buf, n):
    crc = 0
    for i in range(n):
        crc ^= buf[i]
        for _ in range(8):
            crc = ((crc << 1) ^ (0x12 * (crc >> 7))) & 0xFF
    return crc


class SDCard:
    def __init__(self, spi, cs, baudrate=1320000):
        self.spi = spi
        self.cs = cs

        self.cmdbuf = bytearray(6)
        self.dummybuf = bytearray(512)
        self.tokenbuf = bytearray(1)
        for i in range(512):
            self.dummybuf[i] = 0xFF
        self.dummybuf_memoryview = memoryview(self.dummybuf)

        self.sectors = 0
        self.cdv = 1

        # 初始化卡(内部先用 100kHz, 成功后再切到 baudrate)
        self.init_card(baudrate)

    # ------------------------------------------------------------------ 总线
    def init_spi(self, baudrate):
        # 只改频率, 不动引脚(MicroPython 会保留构造时设置的 sck/mosi/miso)
        try:
            self.spi.init(baudrate=baudrate, phase=0, polarity=0)
        except TypeError:              # 个别端口的 init 需要 MASTER 位置参数
            self.spi.init(self.spi.MASTER, baudrate=baudrate, phase=0, polarity=0)

    def deinit(self):
        """释放这根 SPI 总线(降频重试/换主机时用)。"""
        try:
            self.cs(1)
        except Exception:
            pass
        try:
            self.spi.write(b"\xff")
            self.spi.deinit()
        except Exception:
            pass

    # ------------------------------------------------------------------ 初始化
    def init_card(self, baudrate):
        self.cs.init(self.cs.OUT, value=1)
        self.init_spi(100000)

        # CS 拉高时先给至少 100 个时钟
        for _ in range(16):
            self.spi.write(b"\xff")

        # CMD0: 回到 idle, 期望 R1_IDLE_STATE
        for _ in range(5):
            if self.cmd(0, 0) == _R1_IDLE_STATE:
                break
        else:
            raise OSError("no SD card")

        # CMD8: 判断卡版本
        r = self.cmd(8, 0x01AA, 4)
        if r == _R1_IDLE_STATE:
            self.init_card_v2()
        elif r == (_R1_IDLE_STATE | _R1_ILLEGAL_COMMAND):
            self.init_card_v1()
        else:
            raise OSError("couldn't determine SD card version")

        # CMD9: 读 CSD, 解析容量
        if self.cmd(9, 0, 0, False) != 0:
            raise OSError("no response from SD card")
        csd = bytearray(16)
        self.readinto(csd)
        if csd[0] & 0xC0 == 0x40:                      # CSD v2.0 (SDHC/SDXC)
            self.sectors = ((csd[7] << 16 | csd[8] << 8 | csd[9]) + 1) * 1024
        elif csd[0] & 0xC0 == 0x00:                    # CSD v1.0 (<=2GB)
            c_size = (csd[6] & 0b11) << 10 | csd[7] << 2 | csd[8] >> 6
            c_size_mult = (csd[9] & 0b11) << 1 | csd[10] >> 7
            read_bl_len = csd[5] & 0b1111
            capacity = (c_size + 1) * (2 ** (c_size_mult + 2)) * (2 ** read_bl_len)
            self.sectors = capacity // 512
        else:
            raise OSError("SD card CSD format not supported")

        # CMD16: 块长度固定 512
        if self.cmd(16, 512) != 0:
            raise OSError("can't set 512 block size")

        # 切到目标频率
        self.init_spi(baudrate)

    def init_card_v1(self):
        for _ in range(_CMD_TIMEOUT):
            time.sleep_ms(50)
            self.cmd(55, 0)
            if self.cmd(41, 0) == 0:
                self.cdv = 512          # SDSC: 字节寻址
                return
        raise OSError("timeout waiting for v1 card")

    def init_card_v2(self):
        for _ in range(_CMD_TIMEOUT):
            time.sleep_ms(50)
            self.cmd(58, 0, 4)
            self.cmd(55, 0)
            if self.cmd(41, 0x40000000) == 0:
                self.cmd(58, 0, -4)
                ocr = self.tokenbuf[0]
                self.cdv = 1 if (ocr & 0x40) else 512   # SDHC/XC 块寻址
                return
        raise OSError("timeout waiting for v2 card")

    # ------------------------------------------------------------------ 命令
    def cmd(self, cmd, arg, final=0, release=True, skip1=False):
        self.cs(0)

        buf = self.cmdbuf
        buf[0] = 0x40 | cmd
        buf[1] = arg >> 24
        buf[2] = arg >> 16
        buf[3] = arg >> 8
        buf[4] = arg
        buf[5] = _crc7(buf, 5) | 0x01
        self.spi.write(buf)

        if skip1:
            self.spi.readinto(self.tokenbuf, 0xFF)

        for _ in range(_CMD_TIMEOUT):
            self.spi.readinto(self.tokenbuf, 0xFF)
            response = self.tokenbuf[0]
            if not (response & 0x80):
                if final < 0:
                    self.spi.readinto(self.tokenbuf, 0xFF)
                    final = -1 - final
                for _ in range(final):
                    self.spi.write(b"\xff")
                if release:
                    self.cs(1)
                    self.spi.write(b"\xff")
                return response

        self.cs(1)
        self.spi.write(b"\xff")
        return -1

    # ------------------------------------------------------------------ 读写
    def readinto(self, buf):
        self.cs(0)

        for _ in range(_CMD_TIMEOUT):
            self.spi.readinto(self.tokenbuf, 0xFF)
            if self.tokenbuf[0] == _TOKEN_DATA:
                break
            time.sleep_ms(1)
        else:
            self.cs(1)
            raise OSError("timeout waiting for response")

        mv = self.dummybuf_memoryview
        if len(buf) != len(mv):
            mv = mv[:len(buf)]
        self.spi.write_readinto(mv, buf)

        self.spi.write(b"\xff")
        self.spi.write(b"\xff")

        self.cs(1)
        self.spi.write(b"\xff")

    def write(self, token, buf):
        self.cs(0)

        self.spi.read(1, token)
        self.spi.write(buf)
        self.spi.write(b"\xff")
        self.spi.write(b"\xff")

        if (self.spi.read(1, 0xFF)[0] & 0x1F) != 0x05:
            self.cs(1)
            self.spi.write(b"\xff")
            return

        while self.spi.read(1, 0xFF)[0] == 0:
            pass

        self.cs(1)
        self.spi.write(b"\xff")

    def write_token(self, token):
        self.cs(0)
        self.spi.read(1, token)
        self.spi.write(b"\xff")
        while self.spi.read(1, 0xFF)[0] == 0x00:
            pass
        self.cs(1)
        self.spi.write(b"\xff")

    def readblocks(self, block_num, buf, retries=3):
        """读扇区; 失败自动重试(长杜飞线/接触不良会有偶发 CMD 失败)。"""
        last = None
        for i in range(retries):
            try:
                return self._readblocks_once(block_num, buf)
            except OSError as e:
                last = e
                if i + 1 < retries:
                    time.sleep_ms(10)
        raise last

    def _readblocks_once(self, block_num, buf):
        # 共享总线时有用: 事务开始前先把 MOSI 抬高
        self.spi.write(b"\xff")

        nblocks = len(buf) // 512
        if nblocks == 0 or len(buf) % 512 != 0:
            raise ValueError("buffer length is invalid")
        if nblocks == 1:
            if self.cmd(17, block_num * self.cdv, release=False) != 0:
                self.cs(1)
                raise OSError(5)                       # EIO
            self.readinto(buf)
        else:
            if self.cmd(18, block_num * self.cdv, release=False) != 0:
                self.cs(1)
                raise OSError(5)
            offset = 0
            mv = memoryview(buf)
            while nblocks:
                self.readinto(mv[offset:offset + 512])
                offset += 512
                nblocks -= 1
            if self.cmd(12, 0, skip1=True):
                raise OSError(5)

    def writeblocks(self, block_num, buf, retries=3):
        """写扇区; 失败自动重试。"""
        last = None
        for i in range(retries):
            try:
                return self._writeblocks_once(block_num, buf)
            except OSError as e:
                last = e
                if i + 1 < retries:
                    time.sleep_ms(10)
        raise last

    def _writeblocks_once(self, block_num, buf):
        self.spi.write(b"\xff")

        nblocks, err = divmod(len(buf), 512)
        if nblocks == 0 or err:
            raise ValueError("buffer length is invalid")
        if nblocks == 1:
            if self.cmd(24, block_num * self.cdv) != 0:
                raise OSError(5)
            self.write(_TOKEN_DATA, buf)
        else:
            if self.cmd(25, block_num * self.cdv) != 0:
                raise OSError(5)
            offset = 0
            mv = memoryview(buf)
            while nblocks:
                self.write(_TOKEN_CMD25, mv[offset:offset + 512])
                offset += 512
                nblocks -= 1
            self.write_token(_TOKEN_STOP_TRAN)

    def ioctl(self, op, arg):
        if op == 4:                                     # 扇区数
            return self.sectors
        if op == 5:                                     # 扇区大小
            return 512

    def info(self):
        """(总字节, 扇区大小) —— 与 machine.SDCard.info() 对齐。"""
        return self.sectors * 512, 512
