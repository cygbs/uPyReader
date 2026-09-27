# -*- coding: utf-8 -*-
# settings.py — 固件设置页面 + 配置持久化
#
# 设置保存在设备根目录 /settings.json, 例如:
#   {"full_every": 8, "partial_rep": 8}
#
# 两项设置:
#   full_every   每多少次局刷后做一次 OTP 全刷(清残影), 1~16, 默认 8
#   partial_rep  局刷波形的重复次数(越大字越黑实、越慢),      1~16, 默认 8
#
# 用法:
#   from ui import settings
#   cfg = settings.load()
#   settings.draw(c, cfg, index, editing)

import json
from ui import canvas

PATH = "/settings.json"
DEFAULTS = {"full_every": 8, "partial_rep": 8}

LIST_TOP = 26
ROW_H = 46

# (key, 标题, 最小, 最大, 说明)
ITEMS = (
    ("full_every", "全刷间隔", 1, 16,
     "每 N 次局刷后做一次全刷，清除残影；N 越小越干净，但越闪越慢。"),
    ("partial_rep", "局刷深度", 1, 16,
     "局刷波形的重复次数，越大字越黑实、刷新越慢。默认 8。"),
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
    lo, hi = limits(key)
    return lo if v < lo else (hi if v > hi else v)


def adjust(cfg, key, delta):
    """把 cfg[key] 调整 delta 并夹到合法范围, 返回新值。"""
    cfg[key] = clamp(key, cfg[key] + delta)
    return cfg[key]


def draw(c, cfg, index, editing=False):
    c.fb.fill(0)
    canvas.title_bar(c, "固件设置")

    hints = []
    for i, (key, _, _, _, _) in enumerate(ITEMS):
        v = cfg[key]
        hints.append("< %d >" % v if (editing and i == index) else str(v))
    canvas.draw_list(c, LABELS, index, LIST_TOP, ROW_H, hints)

    key, _, lo, hi, _ = ITEMS[index]
    lh = c.font.line_height
    y = LIST_TOP + len(ITEMS) * ROW_H + 4
    c.font.draw_wrapped(c.fb, DESC[key], 12, y, c.width - 24)
    c.font.draw(c.fb, "范围 %d ~ %d" % (lo, hi), 12, y + lh * 2 + 4)

    if editing:
        canvas.draw_footer(c, "旋转调整", "按下确认")
    else:
        canvas.draw_footer(c, "旋转选择", "按下调整  长按返回")
