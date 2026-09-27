# -*- coding: utf-8 -*-
# sdcard.py — SPI TF 卡（microSD）挂载 / 容量查询
#
# FAT32 + MBR 分区表由 FatFs 自动识别（FatFs 内置 FDISK/MBR 解析：
# 先读扇区 0，若不是 FAT 引导扇区就当作 MBR 解析分区表，再读分区引导扇区）。
# 所以在 PC 上用普通工具格式化成 FAT32 的卡直接就能挂载。
#
# 为什么用纯 Python 的 sdspi.py 而不是 machine.SDCard：
#   1) machine.SDCard 在 SPI 模式下要求独占一个 SPI 主机；
#   2) 更要命的是它的 readblocks 失败时 **只返回 -5，不抛异常**
#      （见 machine_sdcard.c: return err == ESP_OK ? 0 : -MP_EIO），
#      错误原因被完全吞掉，根本无法排查；
#   3) 纯 Python 驱动每一步都会抛带原因的 OSError，且初始化固定用 100kHz。
#
# 现在的分工：
#   屏幕  -> machine.SPI(1) = SPI2_HOST
#   TF 卡 -> machine.SPI(2) = SPI3_HOST，引脚 SCK13 / MOSI14 / MISO15 / CS16
#
# 用法：
#   import sdcard
#   sd, baud = sdcard.ensure_mounted()
#   total, free = sdcard.capacity()
#   print(sdcard.attempts())        # 每次尝试的真实错误

import os

try:
    import vfs
except ImportError:
    vfs = None

from machine import Pin, SPI

import sdspi

from hwconfig import (
    SD_SCK, SD_MOSI, SD_MISO, SD_CS, SD_SPI_ID, SD_FREQS, SD_MOUNT,
)

_state = {
    "sd": None, "spi": None, "freq": 0,
    "err": None, "attempts": [], "mount": SD_MOUNT,
}


# --------------------------------------------------------------------------- #
def _open_spi(baud):
    return SPI(SD_SPI_ID, baudrate=baud, polarity=0, phase=0,
               sck=Pin(SD_SCK), mosi=Pin(SD_MOSI), miso=Pin(SD_MISO))


def _release(spi):
    try:
        spi.deinit()
    except Exception:
        pass


def mount(mount_point=SD_MOUNT):
    """挂载 TF 卡。成功返回 (sd, 实际频率)，失败返回 (None, 第一次失败原因)。

    会按 SD_FREQS 依次降频重试，每次失败原因都记在 attempts() 里。
    """
    _state["mount"] = mount_point
    if _state["sd"] is not None:
        return _state["sd"], _state["freq"]

    attempts = []
    for baud in SD_FREQS:
        spd = "%dMHz" % (baud // 1000000)
        try:
            spi = _open_spi(baud)
        except Exception as e:
            attempts.append("%s: SPI(%d) 打开失败: %s" % (spd, SD_SPI_ID, e))
            break                      # 主机/引脚有问题, 换频率也没用
        try:
            cs = Pin(SD_CS, Pin.OUT, value=1)
            sd = sdspi.SDCard(spi, cs, baudrate=baud)
        except Exception as e:
            attempts.append("%s: 卡初始化失败: %s" % (spd, e))
            _release(spi)
            continue
        try:
            mount_fs(sd, mount_point)
        except OSError as e:
            attempts.append("%s: 挂载失败: %s" % (spd, e))
            _release(spi)
            continue
        _state["sd"] = sd
        _state["spi"] = spi
        _state["freq"] = baud
        _state["err"] = None
        _state["attempts"] = attempts
        return sd, baud

    _state["attempts"] = attempts
    _state["err"] = attempts[0] if attempts else "未尝试"
    return None, _state["err"]


def mount_fs(sd, mount_point):
    """真正执行挂载。优先 vfs.VfsFat，退回 os.mount。"""
    if vfs is not None:
        vfs.mount(vfs.VfsFat(sd), mount_point)
    else:
        os.mount(sd, mount_point)


def mounted(mount_point=None):
    if _state["sd"] is not None:
        return True
    mp = mount_point or _state["mount"]
    try:
        os.statvfs(mp)
        return True
    except OSError:
        return False


def ensure_mounted(mount_point=SD_MOUNT):
    """已挂载就返回；否则尝试挂载一次。"""
    if mounted():
        return _state["sd"], _state["freq"]
    return mount(mount_point)


def unmount(mount_point=None):
    mp = mount_point or _state["mount"]
    try:
        if vfs is not None:
            vfs.umount(mp)
        else:
            os.umount(mp)
    except OSError:
        pass
    if _state["spi"] is not None:
        _release(_state["spi"])
    _state["sd"] = None
    _state["spi"] = None
    _state["freq"] = 0


def capacity(mount_point=None):
    """返回 (总字节, 可用字节)。未挂载返回 (None, None)。"""
    mp = mount_point or _state["mount"]
    try:
        st = os.statvfs(mp)
    except OSError:
        return None, None
    return st[0] * st[2], st[0] * st[3]


def last_error():
    """第一次失败的原因 —— 那才是卡/接线的真实问题。"""
    return _state["err"]


def attempts():
    """所有 (频率 → 失败原因) 记录，用于排查。"""
    return list(_state["attempts"])


def speed_mhz():
    return _state["freq"] // 1000000
