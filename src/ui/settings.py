# -*- coding: utf-8 -*-
# settings.py — 固件设置页面 + 配置持久化
#
# 设置保存在设备根目录 /settings.json, 例如:
#   {"full_every": 8, "partial_rep": 8}
#
# 两项设置:
#   full_every   每多少次局刷后做一次 OTP 全刷(清残影), 1~16, 默认 8
#                在 16 之后再往上滚一格 = 0 = 「不全刷」: 软件不再自动全刷,
#                改由阅读界面【短按】手动全刷一次。
#   partial_rep  局刷波形的重复次数-1(越大字越黑实、越慢),   0~16, 默认 0
#                (SSD1619 的 RP 是"重复次数-1", 0 也执行 1 遍; 0 ≈ 360ms)
#
# 用法:
#   from ui import settings
#   cfg = settings.load()
#   settings.draw(c, cfg, index, editing)

import json
from ui import canvas

PATH = "/settings.json"
DEFAULTS = {"full_every": 8, "partial_rep": 0}

NO_FULL = 0                                     # full_every 的特殊取值: 不全刷
FULL_ORDER = tuple(range(1, 17)) + (NO_FULL,)   # 滚轮顺序: 1..16 → 不全刷

LIST_TOP = 26
ROW_H = 46

# (key, 标题, 最小, 最大, 说明)
ITEMS = (
    ("full_every", "全刷间隔", 1, 16,
     "每 N 次局刷后全刷一次清残影；滚过 16 设为“不全刷”，改由阅读界面短按手动全刷。"),
    ("partial_rep", "局刷深度", 0, 16,
     "局刷波形的重复次数-1：0=最快(相位跑一遍)，越大字越黑实、越慢。"),
)

DESC = {k: d for k, _, _, _, d in ITEMS}
LABELS = [t for _, t, _, _, _ in ITEMS]


def load():
    """读取 /settings.json, 缺项/无文件/损坏时回落到默认值。"""
    cfg = dict(DEFAULTS)
    try:
        with open(PATH) as f:
            data = json.load(f)
        for k in DEFAULTS:
            if k in data:
                cfg[k] = clamp(k, int(data[k]))
    except Exception:
        pass
    return cfg


def save(cfg):
    try:
        with open(PATH, "w") as f:
            json.dump(cfg, f)
        print("设置已保存:", cfg)
        return True
    except Exception as e:
        print("保存设置失败:", e)
        return False


def limits(key):
    for k, _, lo, hi, _ in ITEMS:
        if k == key:
            return lo, hi
    return 1, 16


def clamp(key, v):
    """把 v 夹到合法范围。full_every 额外允许 NO_FULL(0)=不全刷。"""
    if key == "full_every" and v == NO_FULL:
        return NO_FULL
    lo, hi = limits(key)
    return lo if v < lo else (hi if v > hi else v)


def fmt(key, v):
    """把配置值格式化成界面显示文本。"""
    if key == "full_every" and v == NO_FULL:
        return "不全刷"
    return str(v)


def adjust(cfg, key, delta):
    """把 cfg[key] 调整 delta 并夹到合法范围, 返回新值。

    full_every 的顺序是 1..16 → 不全刷(NO_FULL): 滚到 16 再往上滚一格即
    进入「不全刷」, 到顶/到底即停; 其余项按普通范围夹取。
    """
    if key == "full_every":
        try:
            i = FULL_ORDER.index(cfg[key])
        except ValueError:
            i = FULL_ORDER.index(DEFAULTS["full_every"])
        i += delta
        if i < 0:
            i = 0
        elif i >= len(FULL_ORDER):
            i = len(FULL_ORDER) - 1
        cfg[key] = FULL_ORDER[i]
    else:
        cfg[key] = clamp(key, cfg[key] + delta)
    return cfg[key]


def draw(c, cfg, index, editing=False):
    c.fb.fill(0)
    canvas.title_bar(c, "固件设置")

    hints = []
    for i, (key, _, _, _, _) in enumerate(ITEMS):
        s = fmt(key, cfg[key])
        hints.append("< %s >" % s if (editing and i == index) else s)
    canvas.draw_list(c, LABELS, index, LIST_TOP, ROW_H, hints)

    key, _, lo, hi, _ = ITEMS[index]
    y = LIST_TOP + len(ITEMS) * ROW_H + 4
    y = c.font.draw_wrapped(c.fb, DESC[key], 12, y, c.width - 24)
    if key == "full_every":
        ran = "范围 1 ~ 16，再往上滚 = 不全刷"
    else:
        ran = "范围 %d ~ %d" % (lo, hi)
    c.font.draw(c.fb, ran, 12, y + 4)

    if editing:
        canvas.draw_footer(c, "旋转调整", "按下确认")
    else:
        canvas.draw_footer(c, "旋转选择", "按下调整  长按返回")
