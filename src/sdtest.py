# -*- coding: utf-8 -*-
"""
sdtest.py — TF 卡诊断脚本(在 REPL 里跑)

    import sdtest
    sdtest.run()

目的: 把"卡到底哪一步不行"分清楚, 而不是只看一句"未挂载"。

  A. machine.SDCard 是否存在
  B. 每个 (slot, 频率) 组合的**真实错误**
     (slot 2 优先 —— 它对应空闲的 SPI3 主机; slot 3 是屏幕占用的 SPI2,
      失败时一定报 "SPI bus already in use", 那是预期内的)
  C. 卡有没有响应 —— 直接读扇区 0
  D. 扇区 0 是不是 MBR + FAT 分区(若卡是 exFAT, FatFs 认不出)
  E. 挂载结果与容量

注意: 运行前把屏幕那条路的程序停掉(Ctrl-C), 或者直接开机后立刻跑。
"""

import os

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


def _describe_sector0(buf):
    out = []
    if not (buf[510] == 0x55 and buf[511] == 0xAA):
        out.append("  扇区0 结尾没有 0x55AA -> 既不是 MBR 也不是 FAT 引导扇区")
        return out
    out.append("  扇区0 结尾有 0x55AA 签名")
    # 16x16 字节的 FAT 引导扇区特征
    if buf[0x36:0x3A] in (b"FAT1", b"FAT3"):
        out.append("  扇区0 本身是 FAT 引导扇区(超软盘格式, 无分区表)")
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


def probe(slot, freq):
    """构造 SDCard 并读扇区 0。返回 (sd, buf, err)。"""
    from machine import Pin, SDCard
    try:
        sd = SDCard(slot=slot, sck=Pin(cfg.SD_SCK), mosi=Pin(cfg.SD_MOSI),
                    miso=Pin(cfg.SD_MISO), cs=Pin(cfg.SD_CS), freq=freq)
    except Exception as e:
        return None, None, "构造失败: %r" % (e,)
    buf = bytearray(512)
    try:
        sd.readblocks(0, buf)
    except Exception as e:
        try:
            sd.deinit()
        except Exception:
            pass
        return None, None, "卡无响应(读扇区0失败): %r" % (e,)
    return sd, buf, None


def run(try_mount=True):
    print("=" * 44)
    print("TF 卡诊断")
    print("=" * 44)
    print("引脚: SCK=%d MOSI=%d MISO=%d CS=%d"
          % (cfg.SD_SCK, cfg.SD_MOSI, cfg.SD_MISO, cfg.SD_CS))

    try:
        from machine import SDCard
        print("machine.SDCard : 存在")
    except ImportError:
        print("machine.SDCard : 不存在! 本固件未编入")
        return

    print("slot 顺序:", cfg.SD_SLOTS)
    print("频率顺序:", ["%dMHz" % (f // 1000000) for f in cfg.SD_FREQS])
    print()

    good = None
    for slot in cfg.SD_SLOTS:
        for freq in cfg.SD_FREQS:
            print("-- slot=%d @%dMHz ..." % (slot, freq // 1000000))
            sd, buf, err = probe(slot, freq)
            if err:
                print("   %s" % err)
                if "构造失败" in err:
                    break                    # 该 slot 不可用, 换下一个
                continue
            print("   卡有响应!  扇区0 前16字节: %s" % _dump(buf))
            for line in _describe_sector0(buf):
                print(line)
            good = (sd, buf, slot, freq)
            break
        if good:
            break

    print()
    if not good:
        print("结论: 卡完全没响应。按顺序排查:")
        print("  1) 供电! 多数 microSD 模块板载 AMS1117/电平转换,")
        print("     VCC 必须接 5V; 接 3V3 时卡只有 ~2.3V, 会完全不响应。")
        print("     用表量一下模块上 3.3V 那一点。")
        print("  2) MISO / CS 是否接错(模块丝印 D0=MISO, D3=CS, CMD=MOSI, CLK)。")
        print("  3) CS 是否确实接在 GPIO%d。" % cfg.SD_CS)
        print("  4) 换一张卡/换杜邦线, 或焊短线。")
        return

    sd, buf, slot, freq = good
    print("选中的接口: slot=%d @%dMHz" % (slot, freq // 1000000))

    if not try_mount:
        return

    print()
    print("-- 尝试挂载 ...")
    ok = False
    try:
        import vfs
        vfs.mount(vfs.VfsFat(sd), "/sd")
        ok = True
    except Exception as e1:
        try:
            os.mount(sd, "/sd")
            ok = True
        except Exception as e2:
            print("   挂载失败 vfs: %r" % (e1,))
            print("   挂载失败 os : %r" % (e2,))
    if not ok:
        print("   -> 卡能读, 但 FatFs 认不出文件系统。")
        print("      常见原因: 分区是 exFAT(≥64GB 卡出厂常见) / 未格式化 /")
        print("                分区表不是 MBR / 分区起始不是 2048 扇区对齐。")
        print("      解决: 在 PC 上用 FAT32(MBR) 重新格式化。")
        try:
            sd.deinit()
        except Exception:
            pass
        return

    print("   挂载成功!")
    st = os.statvfs("/sd")
    print("   容量: 总 %.2f GB / 可用 %.2f GB"
          % (st[0] * st[2] / (1 << 30), st[0] * st[3] / (1 << 30)))
    try:
        print("   根目录:", os.listdir("/sd")[:12])
    except OSError as e:
        print("   列目录失败:", e)
