# -*- coding: utf-8 -*-
# sdcard.py — SPI TF 卡(microSD) 挂载
#
# 目标: 把一张 PC 上格式化成 **FAT32 + MBR 分区表** 的 microSD 挂到 /sd。
#       FatFs 会自动解析 MBR 分区表再挂载其中的 FAT 分区, 所以 PC 上普通
#       "格式化为 FAT32" 的卡直接可用。
#
# 后端: 直接用固件内置的 machine.SDCard(SPI 模式), slot=SD_SPI_ID(=2) 即
#       SPI3_HOST —— 与屏幕那路 SPI(1)=SPI2_HOST 互不干扰, 且是 C 实现,
#       比纯 Python 的 sdspi 更稳更快。数据阶段按 SD_FREQS 依次降频重试
#       (卡初始化阶段固件自己用 100kHz, 与这里无关)。
#
# 挂载后 /sd 出现在根目录, 阅读器的 list_books() 会自动扫到 /sd/books/*.txt。
#
# 用法:
#   from driver import sdcard
#   sdcard.mount()          # 挂到 /sd, 成功返回 True

import os
import machine
from machine import Pin
from driver import hwconfig as cfg

_MOUNT = cfg.SD_MOUNT
_SLOT = cfg.SD_SPI_ID          # machine.SDCard 的 slot: 2 = SPI3_HOST
_DEV = None                    # 已挂载的块设备(保持引用)
_BACKEND = None
_FREQ = None


def mount_point():
    return _MOUNT


def backend():
    return _BACKEND


def is_mounted():
    try:
        os.stat(_MOUNT)
        return True
    except OSError:
        return False


def usage():
    """已挂载时返回 (总字节, 可用字节), 否则 None。"""
    if not is_mounted():
        return None
    try:
        s = os.statvfs(_MOUNT)
        return (s[0] * s[2], s[0] * s[3])
    except Exception:
        return None


def _clean():
    global _DEV, _BACKEND, _FREQ
    if _BACKEND is not None:
        try:
            os.umount(_MOUNT)
        except Exception:
            pass
    _DEV = _BACKEND = _FREQ = None


def mount(force=False):
    """挂载 TF 卡到 /sd。已挂载且 force=False 时直接返回 True。"""
    global _DEV, _BACKEND, _FREQ
    if not force and _BACKEND is not None:
        return True
    _clean()

    if not hasattr(machine, "SDCard"):
        print("[sd] 固件未编译 machine.SDCard")
        return False

    for freq in cfg.SD_FREQS:
        try:
            dev = machine.SDCard(
                sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI),
                miso=Pin(cfg.SD_MISO), cs=Pin(cfg.SD_CS),
                freq=freq, slot=_SLOT)
            os.mount(dev, _MOUNT)
            _DEV, _BACKEND, _FREQ = dev, "machine.SDCard", freq
            print("[sd] 挂载 %s @%dHz (machine.SDCard slot=%d)"
                  % (_MOUNT, freq, _SLOT))
            return True
        except Exception as e:
            print("[sd] machine.SDCard @%dHz: %s" % (freq, e))
            try:
                os.umount(_MOUNT)
            except Exception:
                pass

    print("[sd] 未检测到 TF 卡")
    return False
