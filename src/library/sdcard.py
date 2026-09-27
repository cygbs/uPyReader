# -*- coding: utf-8 -*-
# sdcard.py — SPI TF 卡（microSD）挂载 / 容量查询
#
# FAT32 + MBR 分区表由 FatFs 自动识别（FatFs 内置 FDISK/MBR 解析：
# 先读扇区 0，若不是 FAT 引导扇区就当作 MBR 解析分区表，再读分区引导扇区）。
# 所以在 PC 上用普通工具格式化成 FAT32 的卡直接就能挂载，不需要额外处理。
#
# 重要：MicroPython 的 machine.SDCard 在 SPI 模式下要求 **独占一个 SPI 主机**，
# 不能与屏幕共用（源码：if host.slot != sdspi_handle -> raise "SPI bus already in use"）。
# ESP32-S3 有两个可用主机：屏幕占 SPI(1)=SPI2_HOST，TF 卡走 slot=2=SPI3_HOST。
#
# 用法：
#   import sdcard
#   sd, freq = sdcard.ensure_mounted()
#   total, free = sdcard.capacity()

import os

try:
    import vfs
except ImportError:                  # 很旧的固件
    vfs = None

try:
    from machine import Pin, SDCard
except ImportError:
    Pin = None
    SDCard = None

from hwconfig import (
    SD_SCK, SD_MOSI, SD_MISO, SD_CS, SD_SLOTS, SD_FREQS, SD_MOUNT,
)

_state = {"sd": None, "freq": 0, "err": None, "attempts": [], "mount": SD_MOUNT}


def mounted(mount_point=None):
    """卡是否已经挂载可用。"""
    if _state["sd"] is not None:
        return True
    mp = mount_point or _state["mount"]
    try:
        os.statvfs(mp)
        return True
    except OSError:
        return False


def mount(mount_point=SD_MOUNT):
    """挂载 TF 卡。成功返回 (sdcard, freq)，失败返回 (None, 错误描述)。

    会按 SD_SLOTS × SD_FREQS 逐个尝试, 并把**每一次**的失败原因记下来。
    last_error() 返回**第一次**失败的原因(那才是卡/接线的真实问题;
    后面的 slot3 失败往往是 "SPI bus already in use", 那是预期内的)。
    """
    _state["mount"] = mount_point
    if _state["sd"] is not None:
        return _state["sd"], _state["freq"]
    if SDCard is None:
        _state["err"] = "本固件没有 machine.SDCard"
        _state["attempts"] = [_state["err"]]
        return None, _state["err"]

    attempts = []
    for slot in SD_SLOTS:
        for freq in SD_FREQS:
            try:
                sd = SDCard(slot=slot, sck=Pin(SD_SCK), mosi=Pin(SD_MOSI),
                            miso=Pin(SD_MISO), cs=Pin(SD_CS), freq=freq)
            except (OSError, ValueError) as e:
                # 该 slot 的 SPI 主机被占用 / 引脚非法 -> 换下一个 slot
                attempts.append("slot%d: %s" % (slot, e))
                break
            try:
                mount_fs(sd, mount_point)
            except OSError as e:
                attempts.append("slot%d@%dMHz: %s" % (slot, freq // 1000000, e))
                try:
                    sd.deinit()
                except Exception:
                    pass
                continue                  # 降频再试
            _state["sd"] = sd
            _state["freq"] = freq
            _state["err"] = None
            _state["attempts"] = attempts
            return sd, freq

    _state["attempts"] = attempts
    _state["err"] = attempts[0] if attempts else "未尝试"
    return None, _state["err"]


def mount_fs(sd, mount_point):
    """真正执行挂载。优先用 vfs.VfsFat, 退回 os.mount。"""
    if vfs is not None:
        vfs.mount(vfs.VfsFat(sd), mount_point)
    else:
        os.mount(sd, mount_point)


def ensure_mounted(mount_point=SD_MOUNT):
    """已挂载就直接返回；否则尝试挂载一次。"""
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
    if _state["sd"] is not None:
        try:
            _state["sd"].deinit()
        except Exception:
            pass
    _state["sd"] = None
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
    return _state["err"]


def attempts():
    """所有尝试过的 (slot@频率) 及失败原因, 便于调优。"""
    return list(_state["attempts"])


def speed_mhz():
    return _state["freq"] // 1000000
