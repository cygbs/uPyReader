# -*- coding: utf-8 -*-
# sdcard.py — microSD(TF) 挂载: ESP32-S3 原生 SDMMC
#
# 目标: 把一张 PC 上格式化成 **FAT32 + MBR 分区表** 的 microSD 挂到 /sd。
#       FatFs 会自动解析 MBR 分区表再挂载其中的 FAT 分区, 所以 PC 上普通
#       "格式化为 FAT32" 的卡直接可用。
#
# 后端(引脚见 driver/hwconfig.py):
#   machine.SDCard(slot=SD_SLOT=1) = ESP32-S3 原生 SDMMC 主机, 先 4-bit,
#   失败再 1-bit(只用 DAT0)。每一步都按 SD_FREQS 从高到低降频重试;
#   卡初始化阶段固件自己用 400kHz。
#
# 说明: ESP32-S3 的 SDMMC 经 GPIO matrix 可任意布线; 屏幕走 SPI(1)=SPI2_HOST,
#       SDMMC 不占用 SPI 主机, 两者互不干扰。
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
_DEV = None                    # 已挂载的块设备(保持引用)
_BACKEND = None
_FREQ = None


def mount_point():
    return _MOUNT


def backend():
    """返回当前后端描述字符串, 如 "SDMMC 4-bit"; 未挂载为 None。"""
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


def _mount_dev(dev, label, freq):
    """把块设备挂到 /sd, 成功则记录并返回 True。"""
    global _DEV, _BACKEND, _FREQ
    try:
        os.mount(dev, _MOUNT)
    except Exception as e:
        print("[sd] %s @%dHz: %s" % (label, freq, e))
        try:
            dev.deinit()
        except Exception:
            pass
        try:
            os.umount(_MOUNT)
        except Exception:
            pass
        return False
    _DEV, _BACKEND, _FREQ = dev, label, freq
    print("[sd] 挂载 %s @%dHz (%s)" % (_MOUNT, freq, label))
    return True


def _make_sdmmc(width, freq):
    data = ((cfg.SD_D0,) if width == 1
            else (cfg.SD_D0, cfg.SD_D1, cfg.SD_D2, cfg.SD_D3))
    return machine.SDCard(
        slot=cfg.SD_SLOT, width=width,
        sck=Pin(cfg.SD_CLK), cmd=Pin(cfg.SD_CMD),
        data=tuple(Pin(p) for p in data), freq=freq)


def mount(force=False):
    """挂载 TF 卡到 /sd。已挂载且 force=False 时直接返回 True。"""
    if not force and _BACKEND is not None:
        return True
    _clean()

    if not hasattr(machine, "SDCard"):
        print("[sd] 固件未编译 machine.SDCard")
        return False

    # 原生 SDMMC: 先按配置宽度(默认 4-bit), 失败再 1-bit
    widths = (cfg.SD_WIDTH,) if cfg.SD_WIDTH == 1 else (4, 1)
    for width in widths:
        label = "SDMMC %d-bit" % width
        for freq in cfg.SD_FREQS:
            try:
                dev = _make_sdmmc(width, freq)
            except Exception as e:
                print("[sd] %s @%dHz: %s" % (label, freq, e))
                continue
            if _mount_dev(dev, label, freq):
                return True

    print("[sd] 未检测到 TF 卡")
    return False
