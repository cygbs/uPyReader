# -*- coding: utf-8 -*-
"""
main.py — MPReader 主界面(设备开机自动运行)

MPReader = MicroPython Reader, 基于 ESP32-S3 + SSD1619 墨水屏的阅读器。

硬件: ESP32-S3-N16R8 + SSD1619 4.2" 400x300 + 增量式旋转编码器
接线: 见 driver/hwconfig.py

操作:
    主界面/文件列表  旋转 = 选择, 按下 = 确认, 长按 = 返回
    阅读界面         旋转 = 翻页, 按下 = 退出到主界面
                     每翻一页都会把阅读位置写进 Flash, 下次自动续读

翻页/移动光标用"自裁局刷 LUT"送显(不闪), 每 FULL_EVERY 次插一次全刷清残影;
局刷 LUT 的来历见 driver/epdlut.py。

REPL 辅助:
    import main; main.encoder_debug()    # 校准编码器手感 / 确认接线
    main.main()                          # 重新进入主界面
"""

import time
import sys
import os
from machine import Pin


# --------------------------------------------------------------------------- #
# 路径: 让 driver/ 与 ui/ 两个包可导入
# --------------------------------------------------------------------------- #
def _setup_path():
    """把 src/ 根加入 sys.path, 使 driver/ 与 ui/ 两个包可导入。"""
    here = ""
    try:
        here = os.path.dirname(__file__)
    except Exception:
        pass
    for p in (here, "/", "src"):
        if p and p not in sys.path:
            try:
                sys.path.append(p)
            except Exception:
                pass


_setup_path()

from driver.hwconfig import (
    EPD_CS, EPD_DC, EPD_RST, EPD_BUSY, FONT_CANDIDATES,
    ENC_A, ENC_B, ENC_KEY, ENC_STEPS_PER_DETENT, ENC_LONG_MS,
)
from driver.epd_ssd1619 import EPD_SSD1619
from driver.rotary import Rotary, CLICK, LONG
from driver import epdlut, sdcard, sysinfo
from ui.unifont import Unifont
from ui import about, canvas, reader, settings


LIST_TOP = 26            # 列表起始 y
ROW_H = 46               # 行高
FILE_ROWS = 5            # 文件列表一屏显示行数
# 下面两项可在「固件设置」里改(默认 8), 运行期由 apply_settings() 更新
FULL_EVERY = 8           # 每移动/翻页多少次插一次全刷(其余用不闪的局刷 LUT)
PARTIAL_REP = 8          # 局刷波形里保留组的 repeat(越大字越"实", 越慢)
TOAST_MS = 1500          # 按下后的提示停留时间
FOOT_HINT = "旋转选择   按下确认"
FILE_HINT = "旋转选择   按下阅读   长按返回"

PARTIAL_OTP = None       # 面板 OTP 里的原始波形(改局刷深度时用它重新裁)
PARTIAL_LUT = None       # 运行期由 main() 填入(epdlut 裁出的局刷波形)


# --------------------------------------------------------------------------- #
# 菜单项与右侧提示
# --------------------------------------------------------------------------- #
def hint_reading():
    name = reader.last_book()
    return name.rsplit("/", 1)[-1] if name else "无记录"


def hint_files():
    try:
        return "%d 本" % len(reader.list_books())
    except Exception:
        return ""


def hint_chip():
    return sysinfo.chip_name()


def hint_fw():
    return "全刷 %d / 深度 %d" % (FULL_EVERY, PARTIAL_REP)


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
IDX_SETTINGS = 3
IDX_PLUGINS = 4


# --------------------------------------------------------------------------- #
# 硬件初始化
# --------------------------------------------------------------------------- #
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
    """初始化屏 + 字库, 返回 (epd, canvas)。"""
    epd = EPD_SSD1619(
        epdlut.make_spi(),
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

    return epd, canvas.Canvas(epd, font)


# --------------------------------------------------------------------------- #
# 刷新: 局刷 LUT(不闪) + 定期全刷清残影
# --------------------------------------------------------------------------- #
def show_partial(c):
    """用自裁局刷 LUT 刷新整屏(不闪)。没有 LUT 或失败时回退全刷。"""
    if PARTIAL_LUT is not None:
        try:
            c.show_lut(PARTIAL_LUT)
            return
        except Exception as e:
            print("局刷失败, 回退全刷:", e)
    c.show()


def refresh_screen(c, count, prev):
    """按计数决定刷新方式: 每 FULL_EVERY 次(跨过整数倍)插一次全刷, 其余局刷。"""
    if PARTIAL_LUT is None or count // FULL_EVERY != prev // FULL_EVERY:
        c.show()
    else:
        show_partial(c)


def apply_settings(cfg):
    """把设置应用到运行期: 更新 FULL_EVERY, 并按新的局刷深度重裁 LUT。"""
    global FULL_EVERY, PARTIAL_REP, PARTIAL_LUT
    FULL_EVERY = cfg["full_every"]
    PARTIAL_REP = cfg["partial_rep"]
    if PARTIAL_OTP is not None:
        PARTIAL_LUT = epdlut.make_partial_lut(PARTIAL_OTP, PARTIAL_REP)
    return cfg


# --------------------------------------------------------------------------- #
# 主界面 / 文件列表
# --------------------------------------------------------------------------- #
def build_hints():
    return [fn() for _, fn in MENU]


def draw_main(c, index, hints):
    c.fb.fill(0)
    canvas.title_bar(c, "MPReader")
    canvas.draw_list(c, [t for t, _ in MENU], index, LIST_TOP, ROW_H, hints)
    canvas.draw_footer(c, FOOT_HINT)


def draw_files(c, books, index, scroll):
    c.fb.fill(0)
    canvas.title_bar(c, "浏览文件", "%d 本" % len(books))
    if books:
        vis = books[scroll:scroll + FILE_ROWS]
        canvas.draw_list(c, [n.rsplit("/", 1)[-1] for n, _ in vis], index - scroll,
                         LIST_TOP, ROW_H, [sysinfo.fmt_size(s) for _, s in vis])
    else:
        lh = c.font.line_height
        canvas.text_center(c, "没有找到 .txt 文件", 120)
        canvas.text_center(c, "把小说放到 /books/ 目录", 120 + lh + 4)
    canvas.draw_footer(c, FILE_HINT)


def show_toast(c, left, right=None):
    canvas.draw_footer(c, left, right)
    show_partial(c)


def open_about(c):
    """进入"关于本机"。"""
    about.draw(c)
    return c.show()


# --------------------------------------------------------------------------- #
# 打开书籍
# --------------------------------------------------------------------------- #
def open_book(c, name):
    """打开一本书并显示第一屏。失败返回 None。"""
    try:
        book = reader.Book(name, c)
    except Exception as e:
        print("打开失败:", name, e)
        show_toast(c, "打开失败", str(e)[:20])
        return None
    reader.draw(c, book)
    c.show()
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
    # 注意: PARTIAL_OTP 也必须声明 global —— 否则 main() 里对它的赋值会变成
    #       局部变量, 而 apply_settings() 读的是全局 None, 导致改“局刷深度”
    #       必须重启才生效。
    global PARTIAL_OTP, PARTIAL_LUT

    epd, c = setup()
    enc = Rotary(ENC_A, ENC_B, ENC_KEY,
                 steps_per_detent=ENC_STEPS_PER_DETENT, long_ms=ENC_LONG_MS)

    # 挂载 TF 卡(没有也不影响; 卡里的 /books/*.txt 会被阅读器自动扫到)
    if sdcard.mount():
        u = sdcard.usage()
        print("TF 卡: 已挂载 %s (%s, 后端 %s)"
              % (sdcard.mount_point(),
                 sysinfo.fmt_size(u[0]) if u else "?", sdcard.backend()))
    else:
        print("TF 卡: 未挂载")

    # 读设置 + 读一次面板 OTP 波形, 裁成局刷 LUT(失败则全程退化为全刷)
    cfg = apply_settings(settings.load())
    PARTIAL_OTP = epdlut.read_otp_lut(epd)
    if PARTIAL_OTP is not None:
        PARTIAL_LUT = epdlut.make_partial_lut(PARTIAL_OTP, PARTIAL_REP)
    print("设置: 全刷间隔=%d, 局刷深度=%d" % (FULL_EVERY, PARTIAL_REP))
    print("局刷 LUT: %s" % ("就绪" if PARTIAL_LUT else "不可用, 将使用全刷"))

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
    set_index = 0
    set_edit = False
    set_moves = 0
    toast_until = 0

    draw_main(c, index, hints)
    print("主界面就绪(首屏 %d ms)。旋转=选择, 按下=确认。" % c.show())

    try:
        while True:
            enc.update()
            d = enc.take_steps()
            ev = enc.take_events()

            try:
                if screen == "menu":
                    # ---- 旋转: 移动光标 ----
                    if d:
                        prev = menu_moves
                        menu_moves += 1
                        index = (index + d) % len(MENU)
                        toast_until = 0
                        draw_main(c, index, hints)
                        refresh_screen(c, menu_moves, prev)

                    # ---- 按键 ----
                    if ev & CLICK:
                        if index == IDX_FILES:
                            books = reader.list_books()
                            book_i = 0
                            book_scroll = 0
                            draw_files(c, books, book_i, book_scroll)
                            c.show()
                            screen = "files"
                        elif index == IDX_CONTINUE:
                            b = open_continue(c)
                            if b is not None:
                                book = b
                                page_turns = 0
                                screen = "reader"
                            else:
                                toast_until = time.ticks_add(time.ticks_ms(), TOAST_MS)
                        elif index == IDX_ABOUT:
                            open_about(c)
                            screen = "about"
                        elif index == IDX_SETTINGS:
                            cfg = settings.load()
                            apply_settings(cfg)
                            set_index = 0
                            set_edit = False
                            set_moves = 0
                            settings.draw(c, cfg, set_index, set_edit)
                            c.show()
                            screen = "settings"
                        else:
                            show_toast(c, "已选择：%s" % MENU[index][0],
                                       "子页面待实现")
                            toast_until = time.ticks_add(time.ticks_ms(), TOAST_MS)
                    elif ev & LONG:
                        show_toast(c, "长按(暂未使用)", "返回")
                        toast_until = time.ticks_add(time.ticks_ms(), TOAST_MS)

                    # ---- 提示超时后恢复 ----
                    if toast_until and time.ticks_diff(time.ticks_ms(), toast_until) >= 0:
                        draw_main(c, index, hints)
                        show_partial(c)
                        toast_until = 0

                elif screen == "files":
                    # ---- 旋转: 移动文件选择 ----
                    if d and books:
                        prev = file_moves
                        file_moves += 1
                        book_i = (book_i + d) % len(books)
                        if book_i < book_scroll:
                            book_scroll = book_i
                        elif book_i >= book_scroll + FILE_ROWS:
                            book_scroll = book_i - FILE_ROWS + 1
                        draw_files(c, books, book_i, book_scroll)
                        refresh_screen(c, file_moves, prev)

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
                        c.show()

                elif screen == "reader" and book is not None:
                    # ---- 旋转: 翻页(向前/向后); 每翻一页都会存进度 ----
                    if d:
                        turned = 0
                        for _ in range(min(abs(d), 5)):
                            if d > 0:
                                if not book.next_page():
                                    break
                            elif not book.prev_page():
                                break
                            turned += 1
                        if turned:
                            prev = page_turns
                            page_turns += turned
                            reader.draw(c, book)
                            refresh_screen(c, page_turns, prev)

                    # ---- 按下: 保存进度并回到主界面 ----
                    if ev & (CLICK | LONG):
                        book.save()
                        book = None
                        screen = "menu"
                        hints = build_hints()
                        draw_main(c, index, hints)
                        c.show()

                elif screen == "settings":
                    # ---- 旋转: 选择项目 / 调整数值 ----
                    if d:
                        prev = set_moves
                        set_moves += 1
                        if set_edit:
                            settings.adjust(cfg, settings.ITEMS[set_index][0], d)
                            apply_settings(cfg)
                        else:
                            set_index = (set_index + d) % len(settings.ITEMS)
                        settings.draw(c, cfg, set_index, set_edit)
                        refresh_screen(c, set_moves, prev)

                    # ---- 按下: 进入/退出调整; 长按: 保存并返回 ----
                    if ev & CLICK:
                        set_edit = not set_edit
                        if not set_edit:
                            settings.save(cfg)
                        settings.draw(c, cfg, set_index, set_edit)
                        show_partial(c)
                    elif ev & LONG:
                        settings.save(cfg)
                        set_edit = False
                        screen = "menu"
                        hints = build_hints()      # 全刷间隔可能刚改过
                        draw_main(c, index, hints)
                        c.show()

                else:
                    # ---- 关于本机: 按一下或长按都返回主界面 ----
                    if ev & (CLICK | LONG):
                        screen = "menu"
                        toast_until = 0
                        hints = build_hints()        # 插件数量可能刚变化
                        draw_main(c, index, hints)
                        c.show()
            except Exception as e:
                # 任何未预期异常(例如 TF 卡偶发 EIO)都不打死界面:
                # 打印后回主界面, 编码器继续可用。
                print("!! 界面异常:", e)
                try:
                    sys.print_exception(e)
                except Exception:
                    pass
                screen = "menu"
                book = None
                toast_until = 0
                hints = build_hints()
                draw_main(c, index, hints)
                try:
                    c.show()
                except Exception:
                    pass

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
