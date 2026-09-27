# -*- coding: utf-8 -*-
# about.py — "关于本机"页面
#
# 显示: 芯片 / 模块 / 固件 / 主频 / Flash / PSRAM / MAC

import ui
import sysinfo

FOOTER = "按下或长按返回"


def build_rows():
    return (
        ("芯片", sysinfo.chip_name()),
        ("模块", sysinfo.board_name()),
        ("固件", sysinfo.firmware()),
        ("主频", "%d MHz" % sysinfo.freq_mhz()),
        ("Flash", sysinfo.fmt_size(sysinfo.flash_size())),
        ("PSRAM", sysinfo.fmt_size(sysinfo.psram_size())),
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
