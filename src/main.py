# -*- coding: utf-8 -*-
"""
main.py — 墨水屏阅读器 主界面(设备开机自动运行)

硬件: ESP32-S3-N16R8 + SSD1619 4.2" 400x300 + 增量式旋转编码器
接线: 见 library/hwconfig.py

操作:
    主界面/文件列表  旋转 = 选择, 按下 = 确认, 长按 = 返回
    阅读界面         旋转 = 翻页, 按下 = 退出到主界面
                     每翻一页都会把阅读位置写进 Flash, 下次自动续读

REPL 辅助:
    import main; main.encoder_debug()    # 校准编码器手感 / 确认接线
    main.main()                          # 重新进入主界面
"""

import time
import sys
import os
from machine import Pin, SPI


# --------------------------------------------------------------------------- #
# 路径: 让 library/ 里的模块可导入
# --------------------------------------------------------------------------- #
def _setup_path():
    here = ""
    try:
        here = __file__.rsplit("/", 1)[0]
    except Exception:
        pass
    for p in (here, here + "/library", "library", "/library", "/lib"):
        try:
            if p and p not in sys.path:
                sys.path.append(p)
        except Exception:
            pass


_setup_path()

from hwconfig import (
    EPD_SCK, EPD_MOSI, EPD_CS, EPD_DC, EPD_RST, EPD_BUSY,
    EPD_SPI_ID, EPD_SPI_BAUD,
    ENC_A, ENC_B, ENC_KEY, ENC_STEPS_PER_DETENT, ENC_LONG_MS,
    WIDTH, HEIGHT, FONT_CANDIDATES,
)
from epd_ssd1619 import EPD_SSD1619
from unifont import Unifont
from rotary import Rotary, PRESS, RELEASE, CLICK, LONG
import ui
import sysinfo
import about
import reader


APP_VERSION = "v0.2"

LIST_TOP = 26            # 列表起始 y
ROW_H = 46               # 行高
FILE_ROWS = 5            # 文件列表一屏显示行数
FULL_EVERY = 8           # 每翻/移动多少次插一次全刷(其余用不闪的局刷 LUT)
PARTIAL_REP = 8          # 局刷波形里第 3 组的重复次数(越大字越"实", 越慢)
TOAST_MS = 1500          # 按下后的提示停留时间
FOOT_HINT = "旋转选择   按下确认"
FILE_HINT = "旋转选择   按下阅读   长按返回"

# 运行期由 main() 填入: 从面板 OTP 读出并裁短的局刷波形(与阅读翻页同一套)
PARTIAL_LUT = None


# --------------------------------------------------------------------------- #
# 菜单项与右侧提示
# --------------------------------------------------------------------------- #
def hint_reading():
    name = reader.last_book()
    if not name:
        return "无记录"
    return name.rsplit("/", 1)[-1]


def hint_files():
    try:
        return "%d 本" % len(reader.list_books())
    except Exception:
        return ""


def hint_chip():
    return sysinfo.chip_name()


def hint_fw():
    return "MicroPython"


def hint_plugins():
    return "%d 个" % count_plugins()


MENU = (
    ("继续阅读", hint_reading),
    ("浏览文件", hint_files),
    ("关于本机", hint_chip),
    ("固件设置", hint_fw),
    ("插件", hint_plugins),
)
IDX_CONTINUE = 0
IDX_FILES = 1
IDX_ABOUT = 2


# --------------------------------------------------------------------------- #
# 硬件初始化
# --------------------------------------------------------------------------- #
def make_spi():
    last = None
    for sid in (EPD_SPI_ID, 2, 1):
        try:
            return SPI(sid, baudrate=EPD_SPI_BAUD, polarity=0, phase=0,
                       sck=Pin(EPD_SCK), mosi=Pin(EPD_MOSI))
        except Exception as e:
            last = e
    raise last


def find_font():
    for p in FONT_CANDIDATES:
        try:
            os.stat(p)
            return p
        except OSError:
            pass
    return None


def count_plugins():
    """统计 /plugins 下的一级子目录数量(仅用于主界面显示)。"""
    for base in ("/plugins", "plugins"):
        try:
            entries = os.ilistdir(base)
        except OSError:
            continue
        except AttributeError:          # 极老的固件没有 ilistdir
            try:
                return len(os.listdir(base))
            except OSError:
                continue
        n = 0
        for e in entries:
            if len(e) > 1 and (e[1] & 0x4000):
                n += 1
        return n
    return 0


def setup():
    """初始化屏 + 字库, 返回 (epd, spi, canvas)。"""
    spi = make_spi()
    epd = EPD_SSD1619(
        spi,
        Pin(EPD_CS, Pin.OUT),
        Pin(EPD_DC, Pin.OUT),
        Pin(EPD_RST, Pin.OUT),
        Pin(EPD_BUSY, Pin.IN),
    )
    print("init e-paper ...")
    epd.init()

    path = find_font()
    if path is None:
        raise OSError("找不到字库 unifont16.bin。"
                      "请先在 PC 上运行 tools/build_font.py, 再用 tools/upload.sh 上传")
    font = Unifont(path)
    print("font: %s (%d 字形, 行高 %d)"
          % (path, len(font.misc) + font.cjk_count, font.line_height))

    return epd, spi, ui.Canvas(epd, font)


# --------------------------------------------------------------------------- #
# 局刷 LUT: 从面板 OTP 读回全刷波形, 裁成单阶段短波形
# --------------------------------------------------------------------------- #
def read_otp_lut(epd, n=97):
    """从面板 OTP 读回 LUT 寄存器(命令 0x33)。

    SSD1619 的 4 线 SPI 是半双工、只有一根数据线(SDI), 所以先释放 SPI 外设,
    再用 bit-bang 在 SDI 上把 76/97 字节的波形读回来。读完后自动重建 SPI 并
    重新初始化面板。失败返回 None。
    """
    try:
        epd.spi.deinit()
    except Exception:
        pass

    sck = Pin(EPD_SCK, Pin.OUT, value=0)
    sdi = Pin(EPD_MOSI, Pin.OUT, value=1)
    cs = epd.cs
    dc = epd.dc

    def tx(b):
        for i in range(7, -1, -1):
            sdi.value((b >> i) & 1)
            sck.value(1)
            time.sleep_us(2)
            sck.value(0)
            time.sleep_us(2)

    out = None
    try:
        cs.value(0)
        dc.value(0)
        tx(0x33)
        dc.value(1)
        sdi.init(Pin.IN, Pin.PULL_UP)
        out = bytearray()
        for _ in range(n):
            v = 0
            for _i in range(8):
                sck.value(1)
                time.sleep_us(2)
                v = (v << 1) | sdi.value()
                sck.value(0)
                time.sleep_us(2)
            out.append(v)
        cs.value(1)
    except Exception as e:
        print("读 OTP LUT 失败:", e)
    finally:
        try:
            sdi.init(Pin.OUT)
        except Exception:
            pass
        try:
            epd.spi = make_spi()
            epd.init()
        except Exception as e:
            print("恢复 SPI / 面板失败:", e)

    if out is None:
        return None
    out = bytes(out)
    if out[:4] in (b"\x00\x00\x00\x00", b"\xff\xff\xff\xff"):
        return None
    return out


def make_partial_lut(otp, rep=PARTIAL_REP):
    """把 OTP 全刷波形裁成单阶段局刷波形(不闪)。

    前 35 字节的 vs(电压选择)和最后 6 字节的电压/frame 参数沿用面板 OTP，
    只把 7 个波形组重写成单组: 第 3 组的阶段时间为 [03 02 05 00]、repeat=rep。
    这组阶段是实测定下来的 —— 驱动相("05")足够长，字才够黑、不会发虚/卡住。
    """
    if not otp or len(otp) < 76:
        return None
    lut = bytearray(otp[:76])
    g = 35
    for gi in range(7):
        base = g + gi * 5
        for k in range(5):
            lut[base + k] = 0
    base = g + 3 * 5
    lut[base + 0] = 0x03
    lut[base + 1] = 0x02
    lut[base + 2] = 0x05
    lut[base + 3] = 0x00
    lut[base + 4] = rep
    return bytes(lut)


# --------------------------------------------------------------------------- #
# 公共绘制 / 局部刷新
# --------------------------------------------------------------------------- #
def build_hints():
    return [fn() for _, fn in MENU]


def draw_main(c, index, hints):
    # 必须先清屏: 只刷新局部窗口, 否则旧的选中项反白条会残留在缓冲区里
    # (framebuf.fill 是 C 层实现, 15000 字节开销可忽略)
    c.fb.fill(0)
    ui.title_bar(c, "阅读器主菜单", APP_VERSION)
    ui.draw_list(c, [t for t, _ in MENU], index, LIST_TOP, ROW_H, hints)
    ui.draw_footer(c, FOOT_HINT)


def show_partial(c):
    """用自裁局刷 LUT 刷新整屏(不闪, 和阅读翻页同一套处理)。
    没有 LUT 或刷新失败时回退全刷。"""
    if PARTIAL_LUT is not None:
        try:
            c.show_lut(PARTIAL_LUT)
            return
        except Exception as e:
            print("局刷失败, 回退全刷:", e)
    c.show("full")


def show_toast(c, left, right=None):
    ui.draw_footer(c, left, right)
    show_partial(c)


def open_about(c):
    """进入"关于本机"。"""
    about.draw(c)
    return c.show("full")


# --------------------------------------------------------------------------- #
# 文件列表 / 阅读
# --------------------------------------------------------------------------- #
def draw_files(c, books, index, scroll):
    c.fb.fill(0)
    ui.title_bar(c, "浏览文件", "%d 本" % len(books))
    if books:
        vis = books[scroll:scroll + FILE_ROWS]
        ui.draw_list(c, [n.rsplit("/", 1)[-1] for n, _ in vis], index - scroll,
                     LIST_TOP, ROW_H, [sysinfo.fmt_size(s) for _, s in vis])
    else:
        lh = c.font.line_height
        ui.text_center(c, "没有找到 .txt 文件", 120)
        ui.text_center(c, "把小说放到 /books/ 目录", 120 + lh + 4)
    ui.draw_footer(c, FILE_HINT)


def open_book(c, name):
    """打开一本书并显示第一屏。失败返回 None。"""
    try:
        book = reader.Book(name, c)
    except Exception as e:
        print("打开失败:", name, e)
        show_toast(c, "打开失败", str(e)[:20])
        return None
    reader.draw(c, book)
    c.show("full")
    print("打开 %s 第 %d 页 (%d%%)" % (name, book.page_no(), book.progress()))
    return book


def open_continue(c):
    """打开上次阅读的书。"""
    name = reader.last_book()
    if not name:
        show_toast(c, "暂无阅读记录", "先浏览文件")
        return None
    try:
        os.stat("/" + name)
    except OSError:
        show_toast(c, "上次的书不见了", name.rsplit("/", 1)[-1][:16])
        return None
    return open_book(c, name)


# --------------------------------------------------------------------------- #
# 主循环
# --------------------------------------------------------------------------- #
def main():
    epd, spi, c = setup()
    enc = Rotary(ENC_A, ENC_B, ENC_KEY,
                 steps_per_detent=ENC_STEPS_PER_DETENT, long_ms=ENC_LONG_MS)

    # 读一次面板 OTP 波形并裁成局刷 LUT(失败则退化为全刷)
    global PARTIAL_LUT
    otp_lut = read_otp_lut(epd)
    PARTIAL_LUT = make_partial_lut(otp_lut)
    if PARTIAL_LUT is None:
        print("未能取得局刷 LUT, 将使用全刷")
    else:
        print("局刷 LUT 就绪 (OTP %d 字节, g3 repeat=%d)" % (len(otp_lut), PARTIAL_REP))

    hints = build_hints()
    index = 0
    screen = "menu"
    books = []
    book_i = 0
    book_scroll = 0
    book = None
    page_turns = 0
    menu_moves = 0
    file_moves = 0

    draw_main(c, index, hints)
    ms = c.show("full")
    print("主界面就绪(首屏 %d ms)。旋转=选择, 按下=确认。" % ms)

    toast_until = 0

    try:
        while True:
            enc.update()
            d = enc.take_steps()
            ev = enc.take_events()

            if screen == "menu":
                # ---- 旋转: 移动光标(只刷新受影响的那两行) ----
                if d:
                    index = (index + d) % len(MENU)
                    draw_main(c, index, hints)
                    toast_until = 0
                    menu_moves += 1
                    if PARTIAL_LUT is None or menu_moves % FULL_EVERY == 0:
                        c.show("full")          # 每 FULL_EVERY 次插一次全刷清残影
                    else:
                        show_partial(c)         # 和阅读翻页同一套不闪局刷

                # ---- 按键 ----
                if ev & CLICK:
                    if index == IDX_FILES:
                        books = reader.list_books()
                        book_i = 0
                        book_scroll = 0
                        draw_files(c, books, book_i, book_scroll)
                        c.show("full")
                        screen = "files"
                    elif index == IDX_CONTINUE:
                        b = open_continue(c)
                        if b is not None:
                            book = b
                            page_turns = 0
                            screen = "reader"
                        else:
                            toast_until = time.ticks_add(
                                time.ticks_ms(), TOAST_MS)
                    elif index == IDX_ABOUT:
                        open_about(c)
                        screen = "about"
                    else:
                        show_toast(c, "已选择：%s" % MENU[index][0],
                                   "子页面待实现")
                        toast_until = time.ticks_add(time.ticks_ms(), TOAST_MS)
                elif ev & LONG:
                    show_toast(c, "长按(暂未使用)", "返回")
                    toast_until = time.ticks_add(time.ticks_ms(), TOAST_MS)

                # ---- 提示超时后只恢复底部那一小条 ----
                if toast_until and time.ticks_diff(time.ticks_ms(), toast_until) >= 0:
                    draw_main(c, index, hints)
                    show_partial(c)
                    toast_until = 0

            elif screen == "files":
                # ---- 旋转: 移动文件选择 ----
                if d and books:
                    book_i = (book_i + d) % len(books)
                    if book_i < book_scroll:
                        book_scroll = book_i
                    elif book_i >= book_scroll + FILE_ROWS:
                        book_scroll = book_i - FILE_ROWS + 1
                    draw_files(c, books, book_i, book_scroll)
                    file_moves += 1
                    if PARTIAL_LUT is None or file_moves % FULL_EVERY == 0:
                        c.show("full")
                    else:
                        show_partial(c)

                if ev & CLICK:
                    if books:
                        b = open_book(c, books[book_i][0])
                        if b is not None:
                            book = b
                            page_turns = 0
                            screen = "reader"
                elif ev & LONG:
                    screen = "menu"
                    hints = build_hints()
                    draw_main(c, index, hints)
                    c.show("full")

            elif screen == "reader" and book is not None:
                # ---- 旋转: 翻页(向前/向后); 每翻一页都会存进度 ----
                if d:
                    turned = 0
                    prev_turns = page_turns
                    n = abs(d)
                    if n > 5:
                        n = 5
                    for _ in range(n):
                        if d > 0:
                            if not book.next_page():
                                break
                        else:
                            if not book.prev_page():
                                break
                        turned += 1
                    if turned:
                        reader.draw(c, book)
                        page_turns += turned
                        # 平时用自裁局刷 LUT(不闪); 每 FULL_EVERY 页用 OTP 全刷清残影
                        if PARTIAL_LUT is None or \
                                page_turns // FULL_EVERY != prev_turns // FULL_EVERY:
                            c.show("full")
                        else:
                            show_partial(c)

                # ---- 按下: 保存进度并回到主界面 ----
                if ev & (CLICK | LONG):
                    book.save()
                    book = None
                    screen = "menu"
                    hints = build_hints()
                    draw_main(c, index, hints)
                    c.show("full")

            else:
                # ---- 关于本机: 按一下或长按都返回主界面 ----
                if ev & (CLICK | LONG):
                    screen = "menu"
                    toast_until = 0
                    hints = build_hints()        # 插件数量可能刚变化
                    draw_main(c, index, hints)
                    c.show("full")

            time.sleep_ms(5)

    except KeyboardInterrupt:
        print("主界面退出")
        try:
            epd.sleep()
        except Exception:
            pass


def encoder_debug(seconds=20):
    """编码器自检: 校准 ENC_STEPS_PER_DETENT / 确认接线。"""
    Rotary(ENC_A, ENC_B, ENC_KEY, steps_per_detent=1,
           long_ms=ENC_LONG_MS).debug(seconds)


if __name__ == "__main__":
    main()
