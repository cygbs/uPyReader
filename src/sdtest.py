# -*- coding: utf-8 -*-
"""
sdtest.py — TF 卡诊断脚本（在 REPL 里跑）

    import sdtest
    sdtest.run()

现在用的是纯 Python 驱动(library/sdspi.py), 每一步失败都会抛带原因的异常,
所以输出能直接定位到是哪一步不行:

  A. SPI 总线能不能建起来(SPI(2)=SPI3_HOST, 引脚 13/14/15/16)
  B. 空闲时 MISO 电平是否正常(卡未选中时应为高) —— 判断接线/供电
  C. 卡初始化: CMD0 / CMD8 / ACMD41 / CSD / CMD16 各自的结果
  D. 扇区 0 原始内容 + MBR/分区表解析
  E. 挂载结果与容量
"""

import os
import time

try:
    import hwconfig as cfg
except ImportError:
    import sys
    sys.path.append("library")
    import hwconfig as cfg

_PART_TYPE = {
    0x01: "FAT12", 0x04: "FAT16<32M", 0x06: "FAT16",
    0x0B: "FAT32(CHS)", 0x0C: "FAT32(LBA)",
    0x07: "exFAT / NTFS", 0x83: "Linux", 0xEE: "GPT 保护分区",
}


def _dump(b, n=16):
    return " ".join("%02X" % x for x in b[:n])


def _describe(buf):
    out = []
    if not (buf[510] == 0x55 and buf[511] == 0xAA):
        out.append("  扇区0 结尾没有 0x55AA -> 既不是 MBR 也不是 FAT 引导扇区")
        return out
    out.append("  扇区0 结尾有 0x55AA")
    if buf[0x36:0x3A] in (b"FAT1", b"FAT3"):
        out.append("  扇区0 本身就是 FAT 引导扇区(超软盘格式, 无分区表)")
        return out
    found = False
    for i in range(4):
        e = 446 + i * 16
        ptype = buf[e + 4]
        lba = (buf[e + 8] | (buf[e + 9] << 8)
               | (buf[e + 10] << 16) | (buf[e + 11] << 24))
        if ptype:
            found = True
            out.append("  分区%d: 类型 0x%02X (%s), 起始扇区 %d"
                       % (i + 1, ptype, _PART_TYPE.get(ptype, "未知"), lba))
    if not found:
        out.append("  是 MBR, 但 4 个分区表项全为空(未格式化?)")
    return out


def _miso_idle(spi, cs):
    """卡未选中时 MISO 应为高。返回读到的一字节。"""
    cs(1)
    spi.write(b"\xff")
    buf = bytearray(1)
    spi.readinto(buf, 0xFF)
    return buf[0]


def run(try_mount=True):
    from machine import Pin, SPI
    import sdspi

    print("=" * 46)
    print("TF 卡诊断 (纯 Python SPI 驱动)")
    print("=" * 46)
    print("引脚: SPI(%d) SCK=%d MOSI=%d MISO=%d CS=%d"
          % (cfg.SD_SPI_ID, cfg.SD_SCK, cfg.SD_MOSI, cfg.SD_MISO, cfg.SD_CS))
    print("频率: %s" % ["%dMHz" % (f // 1000000) for f in cfg.SD_FREQS])

    # ---- A. 建 SPI ----
    print()
    print("A. 打开 SPI 总线 ...")
    try:
        spi = SPI(cfg.SD_SPI_ID, baudrate=1_000_000, polarity=0, phase=0,
                  sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI), miso=Pin(cfg.SD_MISO))
        print("   OK")
    except Exception as e:
        print("   失败: %r" % (e,))
        print("   -> 检查 SD_SPI_ID / 引脚号是否和其它外设冲突")
        return

    # ---- B. MISO 空闲电平 ----
    print()
    print("B. MISO 空闲电平(卡未选中) ...")
    cs = Pin(cfg.SD_CS, Pin.OUT, value=1)
    try:
        v = _miso_idle(spi, cs)
        print("   MISO = 0x%02X" % v)
        if v == 0xFF:
            print("   正常(被上拉到高)")
        elif v == 0x00:
            print("   异常! MISO 被拉低 -> 接线短路 / 模块电平转换供电不足")
        else:
            print("   不确定(悬空?)")
    except Exception as e:
        print("   采样失败: %r" % (e,))

    # ---- C/D/E. 逐个频率试 ----
    good = None
    for baud in cfg.SD_FREQS:
        spd = "%dMHz" % (baud // 1000000)
        print()
        print("C. 初始化卡 @%s ..." % spd)
        try:
            spi.init(baudrate=baud)
        except Exception:
            pass
        try:
            sd = sdspi.SDCard(spi, cs, baudrate=baud)
        except Exception as e:
            print("   失败: %r" % (e,))
            continue
        print("   OK  容量 %d 扇区 (%.1f GB), 寻址单位 %s"
              % (sd.sectors, sd.sectors * 512 / (1 << 30),
                 "块" if sd.cdv == 1 else "字节"))

        print("D. 读扇区 0 ...")
        buf = bytearray(512)
        try:
            sd.readblocks(0, buf)
        except Exception as e:
            print("   失败: %r" % (e,))
            continue
        print("   前16字节: %s" % _dump(buf))
        for line in _describe(buf):
            print(line)
        good = (sd, baud)
        break

    print()
    if not good:
        print("结论: 卡初始化或读扇区失败。")
        print("  报 'no SD card'        -> CMD0 没回应, 基本是接线/供电/CS;")
        print("                            先量模块 3.3V 脚: 有 AMS1117 的模块 VCC 必须 5V。")
        print("  报 'timeout waiting for v2 card' -> ACMD41 超时, 卡没进入就绪态, 多半还是供电。")
        print("  报 'timeout waiting for response' -> 数据令牌收不到, 通常是 MISO 或频率太高。")
        try:
            spi.deinit()
        except Exception:
            pass
        return

    sd, baud = good
    print("可用接口: SPI(%d) @%dMHz" % (cfg.SD_SPI_ID, baud // 1000000))
    try:
        spi.deinit()
    except Exception:
        pass

    if not try_mount:
        print("(已跳过挂载)")
        return

    # ---- 重新挂一遍, 用正式代码路径 ----
    print()
    print("E. 用 sdcard.py 正式挂载 ...")
    import sdcard
    mount_sd, freq = sdcard.mount()
    if mount_sd is None:
        print("   失败: %s" % sdcard.last_error())
        for a in sdcard.attempts():
            print("     -", a)
        return
    st = os.statvfs("/sd")
    print("   挂载成功 @%dMHz" % (freq // 1000000))
    print("   容量: 总 %.2f GB / 可用 %.2f GB"
          % (st[0] * st[2] / (1 << 30), st[0] * st[3] / (1 << 30)))
    try:
        names = os.listdir("/sd")
        print("   根目录(%d 项): %s" % (len(names), names[:12]))
    except OSError as e:
        print("   列目录失败:", e)
