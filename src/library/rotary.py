# -*- coding: utf-8 -*-
# rotary.py
# 增量式旋转编码器(正交 S1/S2)+ 按键(KEY 低有效)的轮询驱动
#
# 为什么用轮询: 墨水屏应用主循环本来就慢(等待刷新), 5-10ms 轮询一次完全够用,
# 且比 IRQ 更好调试、不会在 SPI 传输期间被中断。
#
# 用法:
#   from rotary import Rotary, CLICK, LONG, PRESS, RELEASE
#   enc = Rotary(ENC_A, ENC_B, ENC_KEY, steps_per_detent=4)
#   while True:
#       enc.update()                 # 尽量频繁调用
#       d = enc.take_steps()         # -1 / 0 / +1 ...(已按"档"折算, 取走即清零)
#       ev = enc.take_events()       # PRESS | RELEASE | CLICK | LONG 的按位或
#       time.sleep_ms(5)

import time
from machine import Pin

PRESS   = 0x01
RELEASE = 0x02
CLICK   = 0x04      # 短按(按下并释放)
LONG    = 0x08      # 长按(达到 long_ms, 只报一次)

# 正交状态机(展平的一维表): 索引 = (prev << 2) | curr, 状态 = (S1 << 1) | S2
#   合法跳变给 ±1, 非法/跨步跳变给 0(自动滤掉大部分机械抖动)
#   行 = prev: 00, 01, 10, 11;  列 = curr: 00, 01, 10, 11
_QUAD = (
    0,  1, -1,  0,      # prev = 00
    -1, 0,  0,  1,      # prev = 01
    1,  0,  0, -1,      # prev = 10
    0, -1,  1,  0,      # prev = 11
)


class Rotary:
    def __init__(self, pin_a, pin_b, pin_key=None,
                 steps_per_detent=4, long_ms=800, button_debounce_ms=20,
                 pull=Pin.PULL_UP):
        self.a = Pin(pin_a, Pin.IN, pull)
        self.b = Pin(pin_b, Pin.IN, pull)
        self.key = Pin(pin_key, Pin.IN, pull) if pin_key is not None else None

        self.spd = max(1, int(steps_per_detent))
        self.long_ms = long_ms
        self.bdeb = button_debounce_ms

        self._prev = (self.a.value() << 1) | self.b.value()
        self._acc = 0            # 未折算成"档"的剩余跳变
        self._steps = 0          # 待取走的档数
        self._ev = 0             # 待取走的事件位

        # 按键消抖状态
        self._raw = self.key.value() if self.key else 1
        self._stable = self._raw
        self._t_change = time.ticks_ms()
        self._t_down = 0
        self._long_fired = False

    # ------------------------------------------------------------------ 采样
    def update(self):
        """采样一次编码器与按键(尽量频繁调用)。"""
        a = self.a.value()
        b = self.b.value()
        cur = (a << 1) | b
        if cur != self._prev:
            self._acc += _QUAD[(self._prev << 2) | cur]
            self._prev = cur
            while self._acc >= self.spd:
                self._acc -= self.spd
                self._steps += 1
            while self._acc <= -self.spd:
                self._acc += self.spd
                self._steps -= 1
        if self.key is not None:
            self._poll_key()

    def _poll_key(self):
        now = time.ticks_ms()
        raw = self.key.value()
        if raw != self._raw:
            self._raw = raw
            self._t_change = now
        elif raw != self._stable and \
                time.ticks_diff(now, self._t_change) >= self.bdeb:
            self._stable = raw
            if raw == 0:                      # 按下(KEY 与 GND 接通)
                self._ev |= PRESS
                self._t_down = now
                self._long_fired = False
            else:                             # 抬起
                self._ev |= RELEASE
                if not self._long_fired:
                    self._ev |= CLICK
        if self._stable == 0 and not self._long_fired:
            if time.ticks_diff(now, self._t_down) >= self.long_ms:
                self._ev |= LONG
                self._long_fired = True

    # ------------------------------------------------------------------ 取值
    def take_steps(self):
        """取走并清空累计的档数(可正可负)。"""
        s = self._steps
        self._steps = 0
        return s

    def take_events(self):
        """取走并清空按键事件位。"""
        e = self._ev
        self._ev = 0
        return e

    def is_down(self):
        return self._stable == 0

    def position(self):
        return self._steps

    # ------------------------------------------------------------------ 自检
    def debug(self, seconds=20, printer=print):
        """原始计数自检, 用于校准 steps_per_detent 与确认接线。
        以 steps_per_detent=1 计数, 数一下"转一格"打印几次即可。"""
        t0 = time.ticks_ms()
        acc = 0
        printer("旋转编码器 / 按下按键, 原始计数(1/跳变), %ds 后结束" % seconds)
        while time.ticks_diff(time.ticks_ms(), t0) < seconds * 1000:
            self.update()
            d = self.take_steps()
            if d:
                acc += d
                printer("  raw=%+d  total=%+d  S1=%d S2=%d"
                        % (d, acc, self.a.value(), self.b.value()))
            ev = self.take_events()
            if ev:
                for name, bit in (("PRESS", PRESS), ("RELEASE", RELEASE),
                                  ("CLICK", CLICK), ("LONG", LONG)):
                    if ev & bit:
                        printer("  button: %s" % name)
            time.sleep_ms(2)
        printer("自检结束: 记住'转一格'打印了几次, 填进 ENC_STEPS_PER_DETENT")
