# -*- coding: utf-8 -*-
# about.py — "关于本机"页面
#
# 显示: 芯片 / 模块 / 固件 / 主频 / Flash / PSRAM / TF 卡容量 / MAC
# 打开时会再试一次挂载 TF 卡, 所以插卡后进来看看就能刷新容量。

import ui
import sysinfo
import sdcard

FOOTER = "按下或长按返回"


def tf_text():
    sd, freq = sdcard.ensure_mounted()
    if sd is None:
        err = sdcard.last_error() or "无卡"
        return "未挂载 · %s" % err
    total, free = sdcard.capacity()
    if not total:
        return "已挂载 · 容量未知"
    return "%s 可用 %s · @%dMHz" % (sysinfo.fmt_size(total),
                                   sysinfo.fmt_size(free),
                                   freq // 1000000)


def build_rows():
    return (
        ("芯片", sysinfo.chip_name()),
        ("模块", sysinfo.board_name()),
        ("固件", sysinfo.firmware()),
        ("主频", "%d MHz" % sysinfo.freq_mhz()),
        ("Flash", sysinfo.fmt_size(sysinfo.flash_size())),
        ("PSRAM", sysinfo.fmt_size(sysinfo.psram_size())),
        ("TF 卡", tf_text()),
        ("MAC", sysinfo.mac()),
    )


def draw(c, rows=None):
    if rows is None:
        rows = build_rows()
    c.fb.fill(0)
    y = ui.title_bar(c, "关于本机") + 4
    ui.draw_kv(c, rows, y)
    ui.draw_footer(c, FOOTER)
    return rows
