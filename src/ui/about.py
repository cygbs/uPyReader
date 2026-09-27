# -*- coding: utf-8 -*-
# about.py — "关于本机"页面
#
# 显示: 芯片 / 模块 / 固件 / 主频 / Flash / PSRAM / MAC

from driver import sdcard, sysinfo
from ui import canvas

FOOTER = "按下或长按返回"


def _sd_value():
    if not sdcard.is_mounted():
        return "未挂载"
    u = sdcard.usage()
    if not u:
        return "已挂载"
    return "%s (可用 %s)" % (sysinfo.fmt_size(u[0]), sysinfo.fmt_size(u[1]))


def build_rows():
    return (
        ("屏幕", "HINK-E042A13-A0 SYX1802"),
        ("模块", sysinfo.board_name()),
        ("固件", sysinfo.firmware()),
        ("主频", "%d MHz" % sysinfo.freq_mhz()),
        ("Flash", sysinfo.fmt_size(sysinfo.flash_size())),
        ("PSRAM", sysinfo.fmt_size(sysinfo.psram_size())),
        ("TF 卡", _sd_value()),
        ("MAC", sysinfo.mac()),
    )


def draw(c, rows=None):
    if rows is None:
        rows = build_rows()
    c.fb.fill(0)
    y = canvas.title_bar(c, "关于本机") + 4
    canvas.draw_kv(c, rows, y)
    canvas.draw_footer(c, FOOTER)
    return rows
