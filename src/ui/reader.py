# -*- coding: utf-8 -*-
# reader.py — 小说阅读: Flash 内 .txt 文件浏览 / 分页 / 阅读进度持久化
#
# 设计:
#   * 书籍放在设备内部 Flash 里(默认 /books/ 目录, 也递归扫描根目录下其它 .txt)。
#   * 分页按【字节偏移】做: 每页从上次记录的偏移 seek 出去读一小块, 逐字排版,
#     记录下一页的字节起点。不需要把整本书读进内存。
#   * 进度保存到 /books/.state/progress.json:
#       {"last": "books/小说.txt",
#        "books": {"books/小说.txt": {"off": 123456, "o": [.., 123456], "i": 127}}}
#     off = 当前页的字节起点(续读用), o/i = 最近 HIST 页的起点(供向前回翻),
#     只保留有限条, 所以 JSON 不会无限变大。每次翻页都会写盘, 断电/重启后仍从原处继续。
#
# 用法:
#   from ui import reader
#   books = reader.list_books()              # [(相对路径, 字节大小), ...]
#   b = reader.Book(books[0][0], canvas)     # 打开(自动定位到上次位置)
#   b.next_page(); reader.draw(canvas, b, "20:46")   # 翻页 + 渲染(可带时钟文字)

import os
import json
from ui import canvas, settings

BOOKS_DIR = "/books"
STATE_DIR = "/books/.state"
STATE_FILE = STATE_DIR + "/progress.json"

READ_CHUNK = 4096          # 每次从文件读取的字节数
TXT_EXT = ".txt"
HIST = 128                 # 每条进度只保留最近 N 页的起点(限制写盘开销/寿命)
_SKIP_DIRS = ("driver", "ui", "fonts", "tools", "assets", ".state")


# --------------------------------------------------------------------------- #
# 目录 / 文件列表
# --------------------------------------------------------------------------- #
def ensure_dirs():
    for d in (BOOKS_DIR, STATE_DIR):
        try:
            os.mkdir(d)
        except OSError:
            pass


def _name_of(entry):
    n = entry[0]
    if isinstance(n, bytes):
        n = n.decode("utf-8", "replace")
    return n


def list_books():
    """递归列出设备根目录下所有 .txt, 返回 [(相对路径, 大小字节), ...]。"""
    ensure_dirs()
    out = []

    def walk(rel):
        base = "/" + rel if rel else "/"
        # 注意: MicroPython 的 os.ilistdir 返回迭代器, 真正读盘发生在迭代时,
        # 所以 try 必须包住整个 for 循环 —— 否则卡/总线一出错, OSError 会冒出
        # list_books() 把整个主界面打挂(表现为"点浏览文件后卡死")。
        try:
            for e in os.ilistdir(base):
                name = _name_of(e)
                if not name or name.startswith("."):
                    continue
                isdir = len(e) > 1 and (e[1] & 0x4000)
                child = (rel + "/" + name) if rel else name
                if isdir:
                    if name in _SKIP_DIRS:
                        continue
                    walk(child)
                elif name.lower().endswith(TXT_EXT):
                    size = e[3] if len(e) > 3 else 0
                    out.append((child, size))
        except OSError as e:
            print("扫描目录失败:", base, e)

    walk("")
    out.sort(key=lambda x: x[0])
    return out


# --------------------------------------------------------------------------- #
# 进度读写
# --------------------------------------------------------------------------- #
def _load_all():
    try:
        with open(STATE_FILE) as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _save_all(d):
    ensure_dirs()
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(d, f)
    except Exception as e:
        print("保存阅读进度失败:", e)


def last_book():
    return _load_all().get("last")


def load_progress(name):
    d = _load_all().get("books", {})
    rec = d.get(name) if isinstance(d, dict) else None
    if not rec:
        return [0], 0
    off = rec.get("off", 0)
    if not isinstance(off, int) or off < 0:
        off = 0
    tail = rec.get("o")
    if not isinstance(tail, list) or not tail or tail[-1] != off:
        tail = [off]
    return tail, len(tail) - 1


def save_progress(name, starts, idx):
    """只保留当前页起点 + 最近 HIST 页的起点, 避免 JSON 无限膨胀。"""
    off = starts[idx] if starts else 0
    lo = max(0, idx - HIST + 1)
    tail = starts[lo:idx + 1]
    d = _load_all()
    books = d.get("books")
    if not isinstance(books, dict):
        books = {}
        d["books"] = books
    books[name] = {"o": tail, "i": len(tail) - 1, "off": off}
    d["last"] = name
    _save_all(d)


# --------------------------------------------------------------------------- #
# 分页(按字节偏移)
# --------------------------------------------------------------------------- #
def _u8len(cp):
    if cp < 0x80:
        return 1
    if cp < 0x800:
        return 2
    if cp < 0x10000:
        return 3
    return 4


def _trim_incomplete(buf):
    """返回 buf 中完整 UTF-8 序列的字节数(去掉结尾可能被截断的那个字)。"""
    n = len(buf)
    if n == 0:
        return 0
    i = n - 1
    while i >= 0 and (buf[i] & 0xC0) == 0x80:
        i -= 1
    if i < 0:
        return 0
    lead = buf[i]
    if lead < 0x80:
        need = 1
    elif lead < 0xE0:
        need = 2
    elif lead < 0xF0:
        need = 3
    else:
        need = 4
    if n - i >= need:
        return n
    return i


def layout_page(path, offset, rows, max_x, font):
    """从 offset 开始排一页文字。

    返回 (lines, next_offset)。lines 是 rows 行以内的字符串列表。
    max_x 为行右边界像素(x 坐标, 不含), 行从 x=0 起算。
    """
    lines = []
    cur = ""
    curw = 0
    read_pos = 0            # 已处理字符占用的字节数(相对 offset)
    cur_start = 0           # cur 首字符相对 offset 的字节位置
    eof = False
    try:
        f = open(path, "rb")
    except OSError:
        return (["(无法打开文件)"], offset)

    try:
        f.seek(offset)
        buf = b""
        while len(lines) < rows and not eof:
            chunk = f.read(READ_CHUNK)
            if not chunk:
                eof = True
                break
            buf += chunk
            valid = _trim_incomplete(buf)
            if valid <= 0:
                continue
            text = buf[:valid].decode("utf-8", "ignore")
            buf = buf[valid:]
            for ch in text:
                cp = ord(ch)
                L = _u8len(cp)
                if ch == "\r":
                    read_pos += L
                    continue
                if ch == "\ufeff":          # BOM
                    read_pos += L
                    continue
                if ch == "\n":
                    lines.append(cur)
                    cur = ""
                    curw = 0
                    read_pos += L
                    cur_start = read_pos
                    if len(lines) >= rows:
                        break
                    continue
                adv = font.advance(cp)
                if cur and curw + adv > max_x:
                    lines.append(cur)
                    cur = ""
                    curw = 0
                    cur_start = read_pos
                    if len(lines) >= rows:
                        break
                cur += ch
                curw += adv
                read_pos += L

        if len(lines) < rows:
            # 到文件结尾, 提交最后未满的一行
            if cur or not lines:
                lines.append(cur)
            next_off = offset + read_pos
        else:
            next_off = offset + cur_start
    finally:
        f.close()

    while len(lines) < rows:
        lines.append("")
    return (lines, next_off)


# --------------------------------------------------------------------------- #
# 一本书
# --------------------------------------------------------------------------- #
class Book:
    def __init__(self, name, canvas):
        self.name = name
        self.path = "/" + name
        self.font = canvas.font
        # 行距 = 字库自带行高 + 用户在「固件设置」里设的额外间距(像素)
        # (line_gap 缺省/读盘失败时回落到 settings.DEFAULTS)
        self.line_gap = settings.load().get(
            "line_gap", settings.DEFAULTS["line_gap"])
        self.line_height = self.font.line_height + self.line_gap
        lh = self.line_height
        self.body_top = lh + 8
        self.max_x = canvas.width - 24            # 左右各 12px 边距
        self.rows = max(1, (canvas.height - 14 - self.body_top) // lh)

        try:
            self.size = os.stat(self.path)[6]
        except OSError:
            self.size = 0
        starts, idx = load_progress(name)
        self.starts = starts
        self.idx = idx
        self.lines = [""] * self.rows
        self.next_off = 0
        self._render()

    # ------------------------------------------------------------------ 渲染
    def _render(self):
        lines, next_off = layout_page(
            self.path, self.starts[self.idx], self.rows, self.max_x, self.font)
        self.lines = lines
        self.next_off = next_off

    # ------------------------------------------------------------------ 状态
    def progress(self):
        if not self.size:
            return 100
        p = int(self.starts[self.idx] * 100 // self.size)
        return 0 if p < 0 else (100 if p > 100 else p)

    def page_no(self):
        return self.idx + 1

    # ------------------------------------------------------------------ 翻页
    def next_page(self):
        cur = self.starts[self.idx]
        if self.next_off <= cur or self.next_off >= self.size:
            return False
        if self.idx + 1 < len(self.starts):
            self.idx += 1
        else:
            self.starts.append(self.next_off)
            self.idx = len(self.starts) - 1
        self._render()
        self.save()
        return True

    def prev_page(self):
        if self.idx <= 0:
            return False
        self.idx -= 1
        self._render()
        self.save()
        return True

    def save(self):
        save_progress(self.name, self.starts, self.idx)


# --------------------------------------------------------------------------- #
# 阅读界面绘制
# --------------------------------------------------------------------------- #
def draw(c, book, clock_text=""):
    """渲染当前页。clock_text 非空时接在标题栏右侧的「第X页 Y%」后面。

    只在本函数被调用时取显示值, 所以时间只在【翻页/打开/重画】时更新 ——
    由调用方(main.py)从 DS3231 读好传进来, reader 本身不碰 I2C, 也不做 NTP。
    """
    c.fb.fill(0)
    lh = book.line_height
    right = "第%d页 %d%%" % (book.page_no(), book.progress())
    if clock_text:
        right += "  " + clock_text
    title = book.name.rsplit("/", 1)[-1]
    # 书名过长时截断, 给右边的页码/时间腾位置(字库没有裁剪功能, 否则会叠字)
    avail = c.width - 16 - c.font.text_width(right) - 10
    while title and c.font.text_width(title) > avail:
        title = title[:-1]
    canvas.title_bar(c, title, right)

    y = book.body_top
    for line in book.lines:
        if line:
            c.font.draw(c.fb, line, 12, y)
        y += lh

    # 底部进度条
    bw = c.width - 24
    by = c.height - 12
    c.fb.rect(12, by, bw, 7, 1)
    fw = int((bw - 2) * book.progress() // 100)
    if fw > 0:
        c.fb.fill_rect(13, by + 1, fw, 5, 1)
