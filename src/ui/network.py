# -*- coding: utf-8 -*-
# network.py — 「网络」页面: WLAN 开关 + Wi-Fi 扫描 + 密码输入(莫尔斯) + 连接
#
# 页面:
#   * 列表页: 第 0 行 WLAN 开关(值 开/关, 下方实线), 其后是扫描到的热点
#             (左侧 SSID、右侧信号强度 dBm)。内容多于一屏时可滚动并有滚动条。
#   * 密码页: 显示 SSID 与当前已输入的密码; 右侧「退格」键; 中间莫尔斯输入框;
#             下方「取消」「连接」。旋转选择目标; 在莫尔斯框上 短按=·、长按=–;
#             停手 MORSE_GAP_MS 后把当前 ·– 解成一个字符(标准 ITU 莫尔斯)。
#   * 连接成功后把 SSID/密码存到 /wifi.json(只存一个), 开机自动连接;
#     主界面「网络」右侧在连接后显示 SSID。
#
# 用法:
#   from ui import network
#   network.draw(c, index)              # 列表页
#   network.toggle()                    # WLAN 开关(打开时扫描)
#   network.begin_pass(ssid); network.pass_draw(c)
#   network.pass_rotate(d); network.pass_press(is_long); network.pass_tick()
#   network.pass_connect(); network.start_autoconnect(); network.poll()
#   network.status_hint()               # 主界面提示文字

import time
from ui import canvas

LIST_TOP = 26
ROW_H = 46
WLAN_ROW = 0
SOLID = (WLAN_ROW,)          # 第 0 行下方画实线(其余行虚线)

WIFI_FILE = "/wifi.json"     # 只保存一个网络: {"ssid":..,"pass":..}

# 密码页: 旋转选择这 4 个目标
SEL_MORSE, SEL_BACK, SEL_CANCEL, SEL_CONNECT = range(4)
SEL_COUNT = 4
MORSE_GAP_MS = 800           # 停手多久算一个字符结束

# 标准莫尔斯(ITU) -> 字符; 字母统一输出小写(WPA 口令区分大小写, 请注意)
_MORSE = {
    ".-": "a", "-...": "b", "-.-.": "c", "-..": "d", ".": "e",
    "..-.": "f", "--.": "g", "....": "h", "..": "i", ".---": "j",
    "-.-": "k", ".-..": "l", "--": "m", "-.": "n", "---": "o",
    ".--.": "p", "--.-": "q", ".-.": "r", "...": "s", "-": "t",
    "..-": "u", "...-": "v", ".--": "w", "-..-": "x", "-.--": "y",
    "--..": "z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4",
    ".....": "5", "-....": "6", "--...": "7", "---..": "8", "----.": "9",
    ".-.-.-": ".", "--..--": ",", "..--..": "?", "-..-.": "/",
    "-....-": "-", "..--.-": "_", ".--.-.": "@", "-...-": "=",
    ".-.-.": "+", "-.-.--": "!", "---...": ":", "-.-.-.": ";",
    "-.--.": "(", "-.--.-": ")", ".-...": "&", "...-..-": "$",
    ".----.": "'", ".-..-.": '"',
}

# ------------------------------------------------------------------ 状态
_on = False
_aps = []                    # [(ssid, rssi_dbm), ...] 信号从强到弱
_saved_ssid = ""             # /wifi.json 里保存的网络
_connected_ssid = ""         # 当前已连接的网络(空=未连接)

_pass_ssid = ""
_pass_text = ""
_morse = ""
_morse_last = 0
_pass_sel = SEL_MORSE
_pass_msg = ""


# ------------------------------------------------------------------ 列表页
def is_on():
    return _on


def status_hint():
    """主界面「网络」右侧文字: 已连接显示 SSID, 否则 开/关。"""
    if _connected_ssid:
        return _connected_ssid
    return "开" if _on else "关"


def items():
    """返回 (labels, hints): 第 0 项是 WLAN 开关, 其后是各热点。"""
    labels = ["WLAN"]
    hints = ["开" if _on else "关"]
    for ssid, rssi in _aps:
        labels.append(ssid)
        hints.append("%d dBm" % rssi)
    return labels, hints


def ap_ssid(i):
    return _aps[i][0] if 0 <= i < len(_aps) else ""


def toggle():
    """切换 WLAN; 打开时扫描一次。返回切换后的开关状态。"""
    global _on, _aps
    _on = not _on
    _aps = _scan() if _on else []
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
        canvas.draw_footer(c, "旋转选择", "按下输密码  长按返回")


def draw_scanning(c):
    c.fb.fill(0)
    canvas.title_bar(c, "网络", "扫描中…")
    canvas.text_center(c, "正在扫描 Wi-Fi…", 130)


# ------------------------------------------------------------------ 密码页
def begin_pass(ssid):
    global _pass_ssid, _pass_text, _morse, _pass_sel, _pass_msg
    _pass_ssid = ssid
    _pass_text = ""
    _morse = ""
    _pass_sel = SEL_MORSE
    _pass_msg = ""


def pass_ssid():
    return _pass_ssid


def pass_rotate(d):
    global _pass_sel
    _pass_sel = (_pass_sel + d) % SEL_COUNT


def _decode(sym):
    return _MORSE.get(sym, "")


def _commit():
    """把当前 ·– 解成一个字符追加到密码; 返回是否有变化。"""
    global _morse, _pass_text
    if not _morse:
        return False
    ch = _decode(_morse)
    _morse = ""
    if ch:
        _pass_text += ch
    return True


def _push(sym):
    """加入一个 · 或 –; 距上次已超过 MORSE_GAP_MS 则先结算上一个。"""
    global _morse, _morse_last
    now = time.ticks_ms()
    if _morse and time.ticks_diff(now, _morse_last) >= MORSE_GAP_MS:
        _commit()
    _morse += sym
    _morse_last = now


def pass_tick():
    """主循环定期调用: 停手足够久就把当前莫尔斯结算成字符。返回是否有变化。"""
    if _morse and time.ticks_diff(time.ticks_ms(), _morse_last) >= MORSE_GAP_MS:
        return _commit()
    return False


def pass_press(is_long):
    """密码页按下按键。返回动作: 'morse'/'back'/'cancel'/'connect'。"""
    global _pass_text, _morse
    if _pass_sel == SEL_MORSE:
        _push("-" if is_long else ".")
        return "morse"
    if _pass_sel == SEL_BACK:
        _morse = ""
        if is_long:
            _pass_text = ""
        elif _pass_text:
            _pass_text = _pass_text[:-1]
        return "back"
    if _pass_sel == SEL_CANCEL:
        return "cancel"
    return "connect"


def _text_center(c, s, x, y, w):
    c.font.draw(c.fb, s, x + (w - c.font.text_width(s)) // 2, y)


def _frame(c, x, y, w, h, selected):
    c.fb.rect(x, y, w, h, 1)
    if selected:
        c.fb.rect(x + 2, y + 2, w - 4, h - 4, 1)


def _button(c, x, y, w, h, label, selected):
    _frame(c, x, y, w, h, selected)
    _text_center(c, label, x, y + (h - c.font.cell_h) // 2, w)


def pass_draw(c):
    c.fb.fill(0)
    fb = c.fb
    font = c.font
    canvas.title_bar(c, "输入密码")

    font.draw(fb, "SSID  %s" % _pass_ssid[:40], 12, 26)

    shown = _pass_text[-30:] if _pass_text else ""
    font.draw(fb, "密码  %s" % shown, 12, 48)
    _button(c, 306, 44, 82, 26, "退格", _pass_sel == SEL_BACK)

    bx, by, bw, bh = 12, 80, 376, 62
    _frame(c, bx, by, bw, bh, _pass_sel == SEL_MORSE)
    font.draw(fb, "莫尔斯电码 (短按· 长按–)", bx + 8, by + 4)
    font.draw(fb, _morse if _morse else "(空)", bx + 8, by + 22)
    if _morse:
        ch = _decode(_morse)
        if ch:
            font.draw(fb, "→ %s" % ch, bx + 8, by + 40)

    if _pass_msg:
        font.draw(fb, _pass_msg, 12, 148)

    _button(c, 92, 176, 96, 30, "取消", _pass_sel == SEL_CANCEL)
    _button(c, 212, 176, 96, 30, "连接", _pass_sel == SEL_CONNECT)

    canvas.draw_footer(c, "旋转选择", "短按· 长按–")


def draw_connecting(c, ssid):
    c.fb.fill(0)
    canvas.title_bar(c, "连接 Wi-Fi", "连接中…")
    canvas.text_center(c, "正在连接 %s" % ssid[:24], 110)
    canvas.text_center(c, "(最多等待约 15 秒)", 110 + c.font.line_height + 4)


# ------------------------------------------------------------------ 连接 / 保存
def _save(ssid, pw):
    global _saved_ssid
    _saved_ssid = ssid
    try:
        import json
        with open(WIFI_FILE, "w") as f:
            json.dump({"ssid": ssid, "pass": pw}, f)
    except Exception as e:
        print("保存 Wi-Fi 配置失败:", e)


def _load():
    try:
        import json
        with open(WIFI_FILE) as f:
            d = json.load(f)
        ssid = d.get("ssid")
        if ssid:
            return ssid, d.get("pass", "")
    except Exception:
        pass
    return None


def pass_connect():
    """尝试连接密码页当前 SSID。成功 True, 失败 False(失败原因放 _pass_msg)。"""
    global _pass_msg, _on, _saved_ssid, _connected_ssid
    _commit()
    ssid = _pass_ssid
    pw = _pass_text
    _pass_msg = ""
    try:
        import network
        nic = network.WLAN(network.STA_IF)
        nic.active(True)
        _on = True
        nic.connect(ssid, pw)
    except Exception as e:
        _pass_msg = "连接失败: %s" % str(e)[:16]
        print("Wi-Fi 连接失败:", e)
        return False
    for _ in range(150):                 # ~15s
        if nic.isconnected():
            _saved_ssid = ssid
            _connected_ssid = ssid
            _save(ssid, pw)
            return True
        time.sleep_ms(100)
    _pass_msg = "连接超时"
    return False


def start_autoconnect():
    """开机时调用: 读取已保存的 Wi-Fi 并发起连接(非阻塞)。"""
    global _on, _saved_ssid
    creds = _load()
    if not creds:
        return
    ssid, pw = creds
    _saved_ssid = ssid
    _on = True
    try:
        import network
        nic = network.WLAN(network.STA_IF)
        nic.active(True)
        nic.connect(ssid, pw)
        print("Wi-Fi 自动连接:", ssid)
    except Exception as e:
        print("Wi-Fi 自动连接失败:", e)


def poll():
    """主循环定期调用: 刷新连接状态; 状态变化返回 True。"""
    global _connected_ssid
    if not _saved_ssid:
        return False
    try:
        import network
        nic = network.WLAN(network.STA_IF)
        ssid = _saved_ssid if nic.isconnected() else ""
    except Exception:
        ssid = ""
    if ssid != _connected_ssid:
        _connected_ssid = ssid
        return True
    return False
