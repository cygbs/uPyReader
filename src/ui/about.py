# -*- coding: utf-8 -*-
# about.py — "关于本机"页面
#
# 显示: 芯片 / 模块 / 固件 / 主频 / Flash / PSRAM / MAC

from driver import epdlut, sdcard, sysinfo
from ui import canvas

FOOTER = "按下或长按返回"


def _sd_value():
    if not sdcard.is_mounted():
        return "未挂载"
    mode = sdcard.backend() or "?"
    u = sdcard.usage()
    if not u:
        return mode
    return "%s · %s (可用 %s)" % (mode, sysinfo.fmt_size(u[0]),
                                   sysinfo.fmt_size(u[1]))


def _temp_value(c):
    """面板内置温度传感器(约 2ms, 无副作用); 失败显示 -。"""
    epd = getattr(c, "epd", None)
    if epd is None:
        return "-"
    try:
        t = epdlut.read_temp(epd)
    except Exception:
        return "-"
    return "-" if t is None else "%d \u00b0C" % t


def build_rows(c=None):
    return (
        ("屏幕", "HINK-E042A13-A0 SYX1802"),
        ("温度", _temp_value(c)),
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
        rows = build_rows(c)
    c.fb.fill(0)
    y = canvas.title_bar(c, "关于本机") + 4
    canvas.draw_kv(c, rows, y)
    canvas.draw_footer(c, FOOTER)
    return rows
