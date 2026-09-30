# -*- coding: utf-8 -*-
# clock.py — 「时钟模式」页面
#
# 版面(400x300):
#   ┌──────────────────────────────┐
#   │ 时钟模式                       │  标题栏
#   │                              │
#   │          20:22               │  屏幕正中: 超大 HH:MM(24 小时, 补 0)
#   │                              │
#   │      2026-09-30 周三          │  年月日 + 周几
#   │         21.50 °C             │  DS3231 片内温度(不用屏内温度计)
#   │                              │
#   │ 按下退出    长按与 NTP 对时    │  提示栏
#   └──────────────────────────────┘
#
# 刷新策略由 main.py 主循环控制: 进入时全刷一次, 之后每整分钟局刷一次(不闪)。
# 大号数字用 Unifont.draw_scaled 放大绘制; 补 0 保证位数不变、字位不跳。
#
# 用法:
#   from ui import clock
#   clock.draw(c, dt, temp, msg)     # dt=None 表示没接模块
#   clock.date_text(dt) / clock.week_cn(wday)

from ui import canvas

WEEK_CN = ("一", "二", "三", "四", "五", "六", "日")

TITLE = "时钟模式"
BIG_SCALE = 8                    # HH:MM 放大倍数: (5 字符 × 8px) × 8 = 320px 宽
FOOT_L = "按下退出"
FOOT_R = "长按与 NTP 对时"

NO_RTC = "未检测到时钟模块"
NO_RTC_HINT = "请检查 SDA=47 / SCL=21"


def week_cn(wday):
    """DS3231 的周(1=周一..7=周日) -> 「周X」。"""
    if 1 <= wday <= 7:
        return "周" + WEEK_CN[wday - 1]
    return "周?"


def date_text(dt):
    """「2026-09-30 周三」。"""
    return "%04d-%02d-%02d %s" % (dt[0], dt[1], dt[2], week_cn(dt[3]))


def temp_text(temp):
    return "温度 --" if temp is None else "温度 %.2f \u00b0C" % temp


def big_time(dt):
    """24 小时制、补 0 的 HH:MM(位数固定, 显示位置不会跳)。"""
    return "%02d:%02d" % (dt[4], dt[5])


def draw(c, dt, temp=None, msg=""):
    """dt: (年,月,日,周,时,分,秒); None = 没接模块。msg: 底部状态提示。"""
    fb = c.fb
    font = c.font
    fb.fill(0)
    canvas.title_bar(c, TITLE)

    if dt is None:
        canvas.text_center(c, NO_RTC, 118)
        canvas.text_center(c, NO_RTC_HINT, 118 + font.line_height + 6)
        canvas.draw_footer(c, "按下返回")
        return

    # ---- 屏幕正中: 超大 HH:MM ----
    scale = BIG_SCALE
    s = big_time(dt)
    w = font.scaled_width(s, scale)
    th = font.cell_h * scale
    x = (c.width - w) // 2
    ytop = (c.height - th) // 2 - 14
    font.draw_scaled(fb, s, x, ytop, scale)

    # ---- 年月日 + 周几 / 温度 / 状态 ----
    dy = ytop + th + 8
    canvas.text_center(c, date_text(dt), dy)
    wy = dy + font.line_height + 4
    canvas.text_center(c, temp_text(temp), wy)
    if msg:
        canvas.text_center(c, msg, wy + font.line_height + 2)

    canvas.draw_footer(c, FOOT_L, FOOT_R)
