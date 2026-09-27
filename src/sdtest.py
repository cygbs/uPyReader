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


def raw_cmd0(rounds=40):
    """完全绕开驱动, 手发一条 CMD0, 把卡回的原始字节全部打出来。

    用来判断“卡到底回没回”:
      * 全是 0xFF        -> 卡根本没反应(没收到命令 / 没被选中 / 没上电)
      * 出现 0x01 之类   -> 卡活着, 那就是驱动/协议层的问题
    """
    from machine import Pin, SPI
    spi = SPI(cfg.SD_SPI_ID, baudrate=400000, polarity=0, phase=0,
              sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI), miso=Pin(cfg.SD_MISO))
    cs = Pin(cfg.SD_CS, Pin.OUT, value=1)

    cs(1)
    for _ in range(16):                 # CS 高时先给≥74个时钟
        spi.write(b"\xff")
    cs(0)
    spi.write(b"\xff")                  # CS 拉低后先补 8 个时钟
    spi.write(bytes((0x40, 0, 0, 0, 0, 0x95)))   # CMD0 + 合法 CRC7
    for r in range(rounds):
        buf = bytearray(1)
        spi.readinto(buf, 0xFF)
        if buf[0] != 0xFF:
            print("   第 %d 个字节收到 0x%02X  <- 卡有反应!" % (r, buf[0]))
            cs(1)
            spi.write(b"\xff")
            spi.deinit()
            return buf[0]
    cs(1)
    spi.write(b"\xff")
    spi.deinit()
    print("   %d 个字节全是 0xFF -> 卡完全没应答" % rounds)
    return None


def loopback():
    """SPI 收发回环测试(需要先把模块的 MOSI/MISO 接开, 用杜邦线把两个 GPIO 短接)。

    做法:
      1) 拔掉模块上的 MOSI 和 MISO 两根线;
      2) 用一根杜邦线把 GPIO%d (MOSI) 和 GPIO%d (MISO) 直接连起来;
      3) 跑 sdtest.loopback()。
    全 OK => ESP32 的 SPI 外设和这两个引脚都没问题, 问题在模块/卡那一侧。
    """
    from machine import Pin, SPI
    print("回环测试: 请确认 GPIO%d(MOSI) 与 GPIO%d(MISO) 已短接, 且模块那两根线已拔掉"
          % (cfg.SD_MOSI, cfg.SD_MISO))
    spi = SPI(cfg.SD_SPI_ID, baudrate=1000000, polarity=0, phase=0,
              sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI), miso=Pin(cfg.SD_MISO))
    allok = True
    for pat in (b"\x55", b"\xaa", b"\x0f", b"\xf0", bytes(range(8))):
        out = bytearray(len(pat))
        spi.write_readinto(pat, out)
        same = bytes(out) == bytes(pat)
        allok = allok and same
        print("   发 %s -> 收 %s  %s" % (pat.hex(), bytes(out).hex(), "OK" if same else "不匹配"))
    spi.deinit()
    print("结果:", "回环正常(ESP32 侧 OK)" if allok else "回环失败(引脚/外设有问题)")
    return allok


def pin_test(seconds=20):
    """慢速翻转 CS/SCK/MOSI, 方便拿万用表或 LED 逐根确认线到底通不通。

    万用表直流档量模块对应引脚对 GND: CS/MOSI 应在 0V/3.3V 之间慢速跳变,
    SCK 会呈中间值(翻转太快)。
    """
    from machine import Pin
    import time as _t
    pins = (("CS  (GPIO%d)" % cfg.SD_CS, Pin(cfg.SD_CS, Pin.OUT)),
            ("SCK (GPIO%d)" % cfg.SD_SCK, Pin(cfg.SD_SCK, Pin.OUT)),
            ("MOSI(GPIO%d)" % cfg.SD_MOSI, Pin(cfg.SD_MOSI, Pin.OUT)))
    print("每根线各翻转 2 秒, 请配合万用表测模块上对应引脚:")
    end = _t.ticks_add(_t.ticks_ms(), seconds * 1000)
    for name, p in pins:
        print("   正在翻转 %s ..." % name)
        for _ in range(4):
            p.value(1); _t.sleep_ms(250)
            p.value(0); _t.sleep_ms(250)
        p.value(1)
    print("翻转结束")


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
        print("结论: 卡对 CMD0 没有任何应答。先做原始探测:")
        print()
        try:
            raw_cmd0()
        except Exception as e:
            print("   raw_cmd0 失败: %r" % (e,))
        print()
        print("  1) 最容易错的: MOSI / MISO 接反(模块常标 DI/DO)。")
        print("     试着把 GPIO%d 和 GPIO%d 两根线对调再跑一次。"
              % (cfg.SD_MOSI, cfg.SD_MISO))
        print()
        print("  3) 验 ESP32 侧:  sdtest.loopback()")
        print("     拔下模块的 MOSI/MISO, 把 GPIO%d 和 GPIO%d 短接, 跑一下。\n"
              "     全 OK => ESP32 的 SPI 没问题, 问题在模块/卡那边。"
              % (cfg.SD_MOSI, cfg.SD_MISO))
        print()
        print("  4) 用万用表逐根确认:  sdtest.pin_test()")
        print()
        print("  5) 给卡彻底断电重启一次(有些卡会锁在 SD 模式, 必须断 VCC 才回 SPI):")
        print("     整块开发板断电 -> 插好卡 -> 再上电。")
        print()
        print("  6) 换一张卡试。少数卡确实不支持 SPI 模式。")
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
