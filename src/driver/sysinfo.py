# -*- coding: utf-8 -*-
# sysinfo.py — 收集"关于本机"要显示的信息
#
# 数据来源：
#   模块/芯片型号 : sys.implementation._machine / os.uname().machine
#                    （固件编译时的 MICROPY_HW_BOARD_NAME，例如
#                      "Generic ESP32S3 module with Octal-SPIRAM"）
#   固件          : sys.implementation.version / _build
#   主频          : machine.freq()
#   Flash 容量    : 自动创建的 vfs 分区末端（它一直铺到 flash 末尾）
#   PSRAM 容量    : esp32.idf_heap_info() 里最大的那个内存区
#   MAC           : machine.unique_id()

import sys
import os

try:
    import machine
except ImportError:
    machine = None

try:
    import esp32
except ImportError:
    esp32 = None


# --------------------------------------------------------------------------- #
def chip_name():
    """尽量给出芯片型号, 如 ESP32-S3。"""
    txt = ""
    for getter in (lambda: sys.implementation._machine,
                   lambda: os.uname().machine):
        try:
            txt = getter() or ""
        except Exception:
            txt = ""
        if txt:
            break
    up = (txt or "").upper()
    for tag, name in (("ESP32S3", "ESP32-S3"), ("ESP32S2", "ESP32-S2"),
                      ("ESP32C3", "ESP32-C3"), ("ESP32C6", "ESP32-C6"),
                      ("ESP32C2", "ESP32-C2"), ("ESP32P4", "ESP32-P4"),
                      ("ESP32H2", "ESP32-H2"), ("ESP32", "ESP32")):
        if tag in up:
            return name
    return getattr(sys, "platform", "esp32")


def board_name():
    """固件里的板级名称(能看出模块类型与 PSRAM 模式)。"""
    for getter in (lambda: sys.implementation._machine,
                   lambda: os.uname().machine):
        try:
            v = getter()
            if v:
                return str(v)
        except Exception:
            pass
    return "-"


def firmware():
    ver = ""
    try:
        ver = "v" + ".".join(str(x) for x in sys.implementation.version)
    except Exception:
        pass
    build = ""
    try:
        build = str(sys.implementation._build or "")
    except Exception:
        build = ""
    if build:
        return ("%s  %s" % (ver, build)).strip()
    return ver or "-"


def freq_mhz():
    try:
        return machine.freq() // 1000000
    except Exception:
        return 0


def mac():
    try:
        return ":".join("%02X" % b for b in machine.unique_id())
    except Exception:
        return "-"


def flash_size():
    """从自动创建的 vfs 分区末端推断 Flash 总容量。"""
    if esp32 is None:
        return None
    try:
        parts = esp32.Partition.find(esp32.Partition.TYPE_DATA, label="vfs")
        if parts:
            info = parts[0].info()      # (type, subtype, addr, size, label, enc)
            return info[2] + info[3]
    except Exception:
        pass
    return None


def psram_size():
    """从 IDF 堆区里挑最大的那块当作 PSRAM 容量。"""
    if esp32 is None:
        return None
    try:
        regions = esp32.idf_heap_info(esp32.HEAP_DATA)
    except Exception:
        return None
    best = 0
    for r in regions:
        if r[0] > best:
            best = r[0]
    return best or None


# --------------------------------------------------------------------------- #
def fmt_size(n):
    if not n:
        return "-"
    if n >= (1 << 30):
        return "%.1f GB" % (n / (1 << 30))
    if n >= (1 << 20):
        return "%.0f MB" % (n / (1 << 20))
    if n >= (1 << 10):
        return "%d KB" % (n // (1 << 10))
    return "%d B" % n
