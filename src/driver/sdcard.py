# -*- coding: utf-8 -*-
# sdcard.py — SPI TF 卡(microSD) 挂载 + 诊断
#
# 目标: 把一张 PC 上格式化成 **FAT32 + MBR 分区表** 的 microSD 挂到 /sd。
#       FatFs 会自动解析 MBR 分区表再挂载其中的 FAT 分区, 所以 PC 上普通
#       "格式化为 FAT32" 的卡直接可用, 不需要额外处理。
#
# 后端顺序:
#   1) micropython-lib 的纯 Python 驱动 sdspi.py, 走 machine.SPI(2)=SPI3_HOST
#      —— 不占用屏幕那路 SPI(1), 且每一步失败都会抛具体原因, 便于排查;
#   2) 上面不行时, 再试固件内置的 machine.SDCard(SPI 模式)。
#
# 用法:
#   from driver import sdcard
#   sdcard.mount()          # 挂到 /sd, 成功返回 True
#   sdcard.diagnose()       # 在 REPL 里跑, 打印每一步结果
#
# 挂载后 /sd 就出现在根目录, 阅读器的 list_books() 会自动扫到 /sd/books/*.txt。

import os
import time
from machine import Pin, SPI
from driver import hwconfig as cfg

_MOUNT = cfg.SD_MOUNT
_DEV = None            # 已挂载的块设备(保持引用)
_BUS = None            # sdspi 用的 SPI(保持引用, 否则会被回收)
_BACKEND = None
_FREQ = None
_ATTEMPTS = []

_SUPERFLOPPY = (b"FAT1", b"FAT3")


def attempts():
    """返回本次 mount 的详细尝试记录(用于排查)。"""
    return list(_ATTEMPTS)


def backend():
    return _BACKEND


def mount_point():
    return _MOUNT


def usage():
    """已挂载时返回 (总字节, 可用字节), 否则 None。"""
    if not is_mounted():
        return None
    try:
        s = os.statvfs(_MOUNT)
        return (s[0] * s[2], s[0] * s[3])
    except Exception:
        return None


def frequency():
    return _FREQ


def is_mounted():
    try:
        os.stat(_MOUNT)
        return True
    except OSError:
        return False


def _log(msg):
    _ATTEMPTS.append(msg)
    print("[sd]", msg)


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
            _log("sdspi @%dHz 初始化成功 (%d 扇区)" % (baud, dev.sectors))
            return dev, bus, baud
        except Exception as e:
            _log("sdspi @%dHz 失败: %s" % (baud, e))
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
        _log("machine.SDCard: 本固件不支持")
        return None
    kw = dict(sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI),
              miso=Pin(cfg.SD_MISO), cs=Pin(cfg.SD_CS),
              freq=cfg.SD_FREQS[0])
    variants = (("slot=2", dict(slot=2)),
                ("slot=1", dict(slot=1)),
                ("默认", dict()))
    for name, extra in variants:
        args = dict(kw)
        args.update(extra)
        try:
            dev = machine.SDCard(**args)
            _log("machine.SDCard[%s] 成功" % name)
            return dev
        except TypeError as e:
            _log("machine.SDCard[%s] 参数不支持: %s" % (name, e))
        except Exception as e:
            _log("machine.SDCard[%s] 失败: %s" % (name, e))
    return None


# --------------------------------------------------------------------------- #
# 挂载
# --------------------------------------------------------------------------- #
def mount(force=False):
    """挂载 TF 卡到 /sd。已挂载且 force=False 时直接返回 True。"""
    global _DEV, _BUS, _BACKEND, _FREQ
    if not force and is_mounted() and _BACKEND is not None:
        return True
    _clean()
    del _ATTEMPTS[:]

    # ---- 1) sdspi ----
    dev, bus, baud = _try_sdspi()
    if dev is not None:
        try:
            os.mount(dev, _MOUNT)
            _DEV, _BUS, _BACKEND, _FREQ = dev, bus, "sdspi", baud
            _log("挂载成功: %s @%dHz" % (_MOUNT, baud))
            return True
        except Exception as e:
            _log("os.mount(sdspi) 失败: %s" % e)
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
            _log("挂载成功: %s (machine.SDCard)" % _MOUNT)
            return True
        except Exception as e:
            _log("os.mount(machine.SDCard) 失败: %s" % e)

    _log("挂载失败, 见上面每一步的原因")
    return False


# --------------------------------------------------------------------------- #
# 诊断
# --------------------------------------------------------------------------- #
def _miso_idle():
    """卡未选中时 MISO 应被上拉为高。"""
    cs = Pin(cfg.SD_CS, Pin.OUT, value=1)
    spi = SPI(cfg.SD_SPI_ID, baudrate=1000000, polarity=0, phase=0,
              sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI), miso=Pin(cfg.SD_MISO))
    cs(1)
    for _ in range(16):
        spi.write(b"\xff")
    buf = bytearray(1)
    spi.readinto(buf, 0xFF)
    spi.deinit()
    return buf[0]


def raw_cmd0(rounds=40):
    """绕开驱动, 手发一条 CMD0, 把卡回的原始字节打出来。

    全 0xFF -> 卡根本没应答(没选中/没上电/MOSI-MISO 接反);
    出现 0x01 -> 卡活着, 问题在协议/驱动层。
    """
    spi = SPI(cfg.SD_SPI_ID, baudrate=400000, polarity=0, phase=0,
              sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI), miso=Pin(cfg.SD_MISO))
    cs = Pin(cfg.SD_CS, Pin.OUT, value=1)
    cs(1)
    for _ in range(16):
        spi.write(b"\xff")
    cs(0)
    spi.write(b"\xff")
    spi.write(bytes((0x40, 0, 0, 0, 0, 0x95)))       # CMD0 + 合法 CRC7
    found = None
    for r in range(rounds):
        buf = bytearray(1)
        spi.readinto(buf, 0xFF)
        if buf[0] != 0xFF:
            found = buf[0]
            print("   第 %d 字节收到 0x%02X <- 卡有反应" % (r, found))
            break
    cs(1)
    spi.write(b"\xff")
    spi.deinit()
    if found is None:
        print("   %d 字节全是 0xFF -> 卡完全没应答" % rounds)
    return found


def _describe_sector0(buf):
    if not (buf[510] == 0x55 and buf[511] == 0xAA):
        print("   扇区0 无 0x55AA: 既不是 MBR 也不是 FAT 引导扇区")
        return
    print("   扇区0 有 0x55AA")
    if buf[0x36:0x3A] in _SUPERFLOPPY:
        print("   扇区0 本身就是 FAT 引导扇区(超软盘格式, 无分区表)")
        return
    types = {0x01: "FAT12", 0x04: "FAT16<32M", 0x06: "FAT16",
             0x0B: "FAT32(CHS)", 0x0C: "FAT32(LBA)", 0x07: "exFAT/NTFS",
             0x83: "Linux", 0xEE: "GPT"}
    for i in range(4):
        e = 446 + i * 16
        ptype = buf[e + 4]
        lba = (buf[e + 8] | (buf[e + 9] << 8)
               | (buf[e + 10] << 16) | (buf[e + 11] << 24))
        if ptype:
            print("   分区%d: 类型 0x%02X (%s), 起始扇区 %d"
                  % (i + 1, ptype, types.get(ptype, "未知"), lba))


def loopback():
    """回环自测: 验证 ESP32 的 SPI 引脚与连线是否真的在通。

    做法(二选一):
      a) 把 GPIO14(MOSI) 和 GPIO15(MISO) 用跳线短接(先拔掉模块那两根线); 或
      b) 保留模块接线, 用跳线把模块上的 DI 和 DO 两个脚短接。
    然后跑 main.sd_loopback(): 发什么就该收到什么。
    """
    print("回环测试: 确认 MOSI(GPIO%d) 与 MISO(GPIO%d) 已短接"
          % (cfg.SD_MOSI, cfg.SD_MISO))
    spi = SPI(cfg.SD_SPI_ID, baudrate=1000000, polarity=0, phase=0,
              sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI), miso=Pin(cfg.SD_MISO))
    allok = True
    for pat in (b"\x55", b"\xaa", b"\x0f", b"\xf0", bytes(range(8))):
        out = bytearray(len(pat))
        spi.write_readinto(pat, out)
        same = bytes(out) == bytes(pat)
        allok = allok and same
        print("   发 %s -> 收 %s  %s"
              % (pat.hex(), bytes(out).hex(), "OK" if same else "不匹配"))
    spi.deinit()
    print("结果:", "回环正常(ESP32 侧与连线 OK)" if allok else "回环失败(引脚/连线/模块有问题)")
    return allok


def diagnose():
    """在 REPL 里跑: 逐项打印, 定位卡读不到的原因。"""
    print("=" * 46)
    print("TF 卡诊断")
    print("　引脚: SPI(%d) SCK=%d MOSI=%d MISO=%d CS=%d"
          % (cfg.SD_SPI_ID, cfg.SD_SCK, cfg.SD_MOSI, cfg.SD_MISO, cfg.SD_CS))
    print("=" * 46)

    print("\nA. MISO 空闲电平(卡未选中, 应为高):")
    try:
        v = _miso_idle()
        print("   MISO = 0x%02X %s" % (v, "OK" if v == 0xFF else "异常(见下)"))
        if v == 0x00:
            print("   被拉低 -> 接线短路 / 模块电平转换供电不足(试试给模块接 5V)")
    except Exception as e:
        print("   采样失败: %s" % e)

    print("\nB. 原始 CMD0 探测:")
    try:
        raw_cmd0()
    except Exception as e:
        print("   失败: %s" % e)

    print("\nC. 按频率逐个尝试初始化 + 挂载:")
    ok = mount(force=True)
    for a in attempts():
        print("   -", a)

    print("\nD. 结果:")
    if not ok:
        print("   失败。常见原因:")
        print("   1) MOSI/MISO 接反(模块常标 DI/DO 或 SI/SO) —— 对调 GPIO%d/GPIO%d 再试"
              % (cfg.SD_MOSI, cfg.SD_MISO))
        print("   2) 模块供电不足: 带 AMS1117 的模块 VCC 要接 5V")
        print("   3) 卡需要彻底断电一次才会回到 SPI 模式(整板断电重上)")
        print("   4) 换一张卡试(个别卡不支持 SPI 模式)")
        return False
    st = os.statvfs(_MOUNT)
    print("   挂载成功! 后端=%s @%dHz" % (_BACKEND, _FREQ or 0))
    print("   容量: 总 %.2f GB / 可用 %.2f GB"
          % (st[0] * st[2] / (1 << 30), st[0] * st[3] / (1 << 30)))
    try:
        names = os.listdir(_MOUNT)
        print("   根目录(%d 项): %s" % (len(names), names[:12]))
    except OSError as e:
        print("   列目录失败:", e)
    return True
