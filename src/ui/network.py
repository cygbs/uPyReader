# -*- coding: utf-8 -*-
# network.py — 「网络」页面: WLAN 开关 + Wi-Fi 扫描列表
#
# 目前只做「开关 + 扫描 + 显示 SSID/信号强度」, 不做连接。
#   第 0 行 = WLAN 开关(值 开/关, 下方为实线分隔符);
#   其后 = 扫描到的热点, 左侧 SSID、右侧信号强度(dBm), 按信号从强到弱排。
#   热点多于一屏时列表可滚动, 右侧有滚动条。
#
# 用法:
#   from ui import network
#   network.draw(c, index)      # 只画面板, 送显由调用方决定
#   if network.toggle(): ...    # 开关; 打开时阻塞扫描一次
#   network.is_on(); network.items()

from ui import canvas

LIST_TOP = 26
ROW_H = 46
WLAN_ROW = 0
SOLID = (WLAN_ROW,)          # 第 0 行下方画实线(其余行虚线)

_on = False
_aps = []                    # [(ssid, rssi_dbm), ...] 信号从强到弱


def is_on():
    return _on


def items():
    """返回 (labels, hints): 第 0 项是 WLAN 开关, 其后是各热点。"""
    labels = ["WLAN"]
    hints = ["开" if _on else "关"]
    for ssid, rssi in _aps:
        labels.append(ssid)
        hints.append("%d dBm" % rssi)
    return labels, hints


def toggle():
    """切换 WLAN; 打开时扫描一次。返回切换后的开关状态。"""
    global _on, _aps
    _on = not _on
    if _on:
        _aps = _scan()
    else:
        _aps = []
    return _on


def _scan():
    """扫描 Wi-Fi, 返回 [(ssid, rssi), ...] 按 rssi 从强到弱。失败返回 []。"""
    out = []
    try:
        import network
        nic = network.WLAN(network.STA_IF)
        if not nic.active():
            nic.active(True)
        for ap in nic.scan():
            ssid = ap[0]
            if isinstance(ssid, bytes):
                ssid = ssid.decode("utf-8", "replace")
            ssid = ssid or "(隐藏网络)"
            out.append((ssid, int(ap[3])))
        out.sort(key=lambda x: x[1], reverse=True)
    except Exception as e:
        print("Wi-Fi 扫描失败:", e)
    return out


def draw(c, index):
    c.fb.fill(0)
    if _on:
        canvas.title_bar(c, "网络", "%d 个" % len(_aps))
    else:
        canvas.title_bar(c, "网络")

    labels, hints = items()
    rows = canvas.list_rows(c, LIST_TOP, ROW_H)
    first = index - rows + 1 if index >= rows else 0
    canvas.draw_list(c, labels, index, LIST_TOP, ROW_H, hints,
                     rows=rows, first=first, scrollbar=True, solid=SOLID)

    if index == WLAN_ROW:
        canvas.draw_footer(c, "旋转选择",
                           "按下%s  长按返回" % ("关闭" if _on else "开启"))
    else:
        canvas.draw_footer(c, "旋转选择", "长按返回")


def draw_scanning(c):
    c.fb.fill(0)
    canvas.title_bar(c, "网络", "扫描中…")
    canvas.text_center(c, "正在扫描 Wi-Fi…", 130)
