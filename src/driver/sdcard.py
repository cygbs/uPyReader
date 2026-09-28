# -*- coding: utf-8 -*-
# sdcard.py — SPI TF 卡(microSD) 挂载
#
# 目标: 把一张 PC 上格式化成 **FAT32 + MBR 分区表** 的 microSD 挂到 /sd。
#       FatFs 会自动解析 MBR 分区表再挂载其中的 FAT 分区, 所以 PC 上普通
#       "格式化为 FAT32" 的卡直接可用。
#
# 后端顺序:
#   1) micropython-lib 的纯 Python 驱动 sdspi.py, 走 machine.SPI(2)=SPI3_HOST
#      —— 不占用屏幕那路 SPI(1), 且每一步失败都会抛具体原因;
#   2) 上面不行时, 再试固件内置的 machine.SDCard(SPI 模式)。
#
# 挂载后 /sd 出现在根目录, 阅读器的 list_books() 会自动扫到 /sd/books/*.txt。
#
# 用法:
#   from driver import sdcard
#   sdcard.mount()          # 挂到 /sd, 成功返回 True

import os
from machine import Pin, SPI
from driver import hwconfig as cfg

_MOUNT = cfg.SD_MOUNT
_DEV = None            # 已挂载的块设备(保持引用)
_BUS = None            # sdspi 用的 SPI(保持引用, 否则会被回收)
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
    global _DEV, _BUS, _BACKEND, _FREQ
    if _BACKEND is not None:
        try:
            os.umount(_MOUNT)
        except Exception:
            pass
    if _BUS is not None:
        try:
            _BUS.deinit()
        except Exception:
            pass
    _DEV = _BUS = _BACKEND = _FREQ = None


# --------------------------------------------------------------------------- #
# 后端 1: 纯 Python sdspi (machine.SPI(2) = SPI3_HOST)
# --------------------------------------------------------------------------- #
def _try_sdspi():
    from driver import sdspi
    for baud in cfg.SD_FREQS:
        bus = None
        try:
            bus = SPI(cfg.SD_SPI_ID, baudrate=baud, polarity=0, phase=0,
                      sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI),
                      miso=Pin(cfg.SD_MISO))
            cs = Pin(cfg.SD_CS, Pin.OUT, value=1)
            dev = sdspi.SDCard(bus, cs, baudrate=baud)
            return dev, bus, baud
        except Exception as e:
            print("[sd] sdspi @%dHz: %s" % (baud, e))
            if bus is not None:
                try:
                    bus.deinit()
                except Exception:
                    pass
    return None, None, None


# --------------------------------------------------------------------------- #
# 后端 2: 固件内置 machine.SDCard (SPI 模式)
# --------------------------------------------------------------------------- #
def _try_builtin():
    import machine
    if not hasattr(machine, "SDCard"):
        return None
    kw = dict(sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI),
              miso=Pin(cfg.SD_MISO), cs=Pin(cfg.SD_CS),
              freq=cfg.SD_FREQS[0])
    for slot in (2, 1, None):
        args = dict(kw)
        if slot is not None:
            args["slot"] = slot
        try:
            return machine.SDCard(**args)
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# 挂载
# --------------------------------------------------------------------------- #
def mount(force=False):
    """挂载 TF 卡到 /sd。已挂载且 force=False 时直接返回 True。"""
    global _DEV, _BUS, _BACKEND, _FREQ
    if not force and _BACKEND is not None:
        return True
    _clean()

    # ---- 1) sdspi ----
    dev, bus, baud = _try_sdspi()
    if dev is not None:
        try:
            os.mount(dev, _MOUNT)
            _DEV, _BUS, _BACKEND, _FREQ = dev, bus, "sdspi", baud
            print("[sd] 挂载 %s @%dHz (sdspi)" % (_MOUNT, baud))
            return True
        except Exception as e:
            print("[sd] os.mount(sdspi): %s" % e)
            try:
                bus.deinit()
            except Exception:
                pass

    # ---- 2) 内置 machine.SDCard ----
    dev = _try_builtin()
    if dev is not None:
        try:
            os.mount(dev, _MOUNT)
            _DEV, _BACKEND, _FREQ = dev, "machine.SDCard", cfg.SD_FREQS[0]
            print("[sd] 挂载 %s (machine.SDCard)" % _MOUNT)
            return True
        except Exception as e:
            print("[sd] os.mount(machine.SDCard): %s" % e)

    print("[sd] 未检测到 TF 卡")
    return False
