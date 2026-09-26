# 墨水屏测试 Demo（ESP32-S3-N16R8 + SSD1619 4.2"）

```
阅读器/
├── README.md                   # 本文档
├── ESP32_GENERIC_S3-...bin     # MicroPython 固件（已刷入；*.bin 不入库）
├── src/                        # 只放 MicroPython 源码 → 设备根目录
│   ├── epd_test.py             # 测试 Demo
│   └── library/
│       ├── epd_ssd1619.py      # 驱动：HINK-E042A13-A0 / SSD1619 4.2" 400x300
│       └── unifont.py          # UFB1 位图字库读取 + 渲染
├── assets/                     # 资源 → 设备根目录
│   └── fonts/
│       └── unifont16.bin       # 生成物，不入库（由 tools/build_font.py 生成）
└── tools/                      # PC 侧工具
    ├── upload.sh               # 一键同步 src/ + assets/ 到设备
    └── build_font.py           # Unifont .hex → UFB1 二进制字库
```

对应到设备上的布局：

```
/                 (设备根目录)
├── epd_test.py
├── library/
│   ├── epd_ssd1619.py
│   └── unifont.py
└── fonts/
    └── unifont16.bin
```

- 屏幕：HINK-E042A13-A0 4.2" 400×300 黑白，控制芯片 SSD1619（或 UC8151D，指令同族）
- 主控：ESP32-S3-N16R8，固件 `ESP32_GENERIC_S3-SPIRAM_OCT-...bin`（已刷好）
- 文件系统约 14 MB，库和脚本可以放心放

---

## 1. 接线

你的屏幕丝印是 `BUSY CS D/C RES SDI SCLK 3V3 GND`，与常见 `DIN/CLK/DC/RST`
只是叫法不同，信号完全一样：

| 屏幕丝印 | 含义 | 默认接到 | 变量 |
|---|---|---|---|
| `3V3` | 3.3 V 电源 | 3V3 | — |
| `GND` | 地 | GND | — |
| `SCLK` | SPI 时钟 (CLK) | GPIO **12** | `PIN_SCK` |
| `SDI` | SPI 数据 (MOSI/DIN) | GPIO **11** | `PIN_MOSI` |
| `CS` | 片选 | GPIO **10** | `PIN_CS` |
| `D/C` | 数据/命令 (DC) | GPIO **9** | `PIN_DC` |
| `RES` | 复位 (RST) | GPIO **8** | `PIN_RST` |
| `BUSY` | 忙信号 | GPIO **7** | `PIN_BUSY` |

默认引脚定义在 `epd_test.py` 顶部的“接线配置”区，**请按实际接线修改**。

注意：
- `SDI` = MOSI（ESP32 输出数据给屏幕），`SCLK` = 时钟。屏是只写设备，
  **没有 MISO / 回读引脚**，SPI 只初始化 `sck` + `mosi` 即可（代码已如此）。
- 屏幕是 3.3 V 供电，**不要接 5 V**。
- ESP32-S3-N16R8 上 **GPIO 26–32 被内部 Flash / Octal PSRAM 占用，不要用**；GPIO 19/20 是 USB，43/44 是 UART0，也尽量避开。上面这组引脚都是安全的。
- BUSY 需要能读到高电平；如果一直“busy timeout”，见下面排错。

---

## 2. 上传到板子

板子已刷好 MicroPython，串口一般是 `/dev/ttyACM0`。装好 `mpremote`：

```bash
uv tool install mpremote
# 或 python3 -m pip install --user mpremote
```

### 一键上传（推荐）

`tools/upload.sh` 会把 `src/`（源码）和 `assets/`（资源）下的**所有**顶层条目
同步到设备根目录，默认按 sha256 跳过未改动文件：

```bash
cd /home/ygbs/下载/阅读器
chmod +x tools/upload.sh

tools/upload.sh                 # 默认 /dev/ttyACM0
tools/upload.sh /dev/ttyUSB0     # 指定串口
```

可选环境变量：

| 变量 | 作用 |
|---|---|
| `FORCE=1` | 强制重传（不跳过内容相同的文件） |
| `CLEAN=1` | 上传前先删掉对应的远端目录（本地删了文件时用它清理） |
| `RUN=1` | 上传后执行 `epd_test.run_all()` |
| `RUN='import xxx; xxx.main()'` | 上传后执行任意 Python 片段 |
| `MPREMOTE=/path/to/mpremote` | 指定 mpremote 可执行文件 |
| `CHMOD=0` | 跳过上传前自动执行的 `sudo chmod 777 <PORT>` |

> 默认每次上传前会先 `sudo chmod 777 <端口>`（重新插拔后串口权限常被重置），
> 可能会提示输入 sudo 密码。若你已把账号加入 `dialout` 组、无需此步，可加 `CHMOD=0`。

示例：

```bash
FORCE=1 tools/upload.sh                      # 全量重传
RUN=1 tools/upload.sh                        # 传完就跑测试 Demo
CLEAN=1 RUN=1 tools/upload.sh                # 清干净再传再跑
```

路径映射规则：`src/` 和 `assets/` 的每个顶层条目都原样落到设备根，例如
`src/library/epd_ssd1619.py` → `/library/epd_ssd1619.py`，
`assets/fonts/unifont16.bin` → `/fonts/unifont16.bin`。

> 实现细节：脚本用 `mpremote cp -r ... :.`（远端当前目录）而不是 `:`。
> 因为 `mpremote` 对 `:` 是否“已存在”的判断依赖 `os.stat("")`，行为不稳；
> `:.` 语义明确，且反复执行不会产生 `library/library` 这种嵌套。

### 手动命令（等价做法）

```bash
cd /home/ygbs/下载/阅读器
PORT=/dev/ttyACM0

# 一次连接，把 src/ 下所有顶层条目复制到设备根目录
mpremote connect $PORT cp -r src/* :.

# 查看结果
mpremote connect $PORT fs tree :

# 运行
mpremote connect $PORT exec "import epd_test; epd_test.run_all()"
```

### Thonny

打开 Thonny → 右下角解释器选 `MicroPython (ESP32)` + 端口 → 在“文件”面板把
`src/library/epd_ssd1619.py` 上传到设备的 `/library`，把 `src/epd_test.py` 上传到设备根目录，
然后点运行。

> Demo 里的导入逻辑会依次尝试：当前目录 → `library/` → `/library` → `/lib`，放哪都能找到。

---

## 3. 运行

在 REPL 里：

```python
import epd_test

epd_test.run_all()          # 依次跑完所有测试（约 40 秒）
epd_test.run_all(do_sleep=True)   # 跑完让屏幕休眠省电

epd_test.menu()             # 交互菜单，逐项测试
```

直接跑文件（跑完自动执行 `run_all()`）：

```bash
mpremote connect /dev/ttyACM0 run epd_test.py
```

单项测试也可以手动调：

```python
epd, spi, c = epd_test.setup()
epd_test.t_shapes(c, epd)
epd_test.t_partial(c, epd, seconds=20)
```

---

## 4. 字库方案：Unifont 16×16 → UFB1 二进制

### 为什么这么选

- **Unifont 本身就是 1-bit 位图**（ASCII 8×16、CJK 16×16），`.hex` 源里一个 bit 就是
  一个像素 → **PC 侧零光栅化、像素零误差**，也不需要任何字体库依赖。
- **完整覆盖 BMP**，含全部 CJK 基本区（U+4E00–U+9FFF，20992 字）。
- **授权友好**：自 13.0.04 起双许可 = **SIL OFL 1.1** 与 **GPL-2.0+（字体嵌入例外）**，
  嵌入进固件没问题（走 OFL 最省事，见 `LICENSES/`）。
- **设备侧只做“查表 + `framebuf.blit`”**，不解析 hex、不碰 TTF。

### 生成

```bash
# 首次会自动下载官方 unifont_all-18.0.01.hex.gz（1.6 MB）到 tools/.cache/
python3 tools/build_font.py -o assets/fonts/unifont16.bin --preview /tmp/preview.bmp
```

可选参数：

| 参数 | 作用 |
|---|---|
| `--charset book.txt` | 只收录该文本里出现的字符，体积可大幅减小 |
| `--ranges "0x20-0x7e,0x4e00-0x9fff"` | 自定义码点范围 |
| `--panel` | 生成反相版（1=白底），配合 panel 语义画布可兔送显取反 |
| `--preview out.bmp` | 从**生成后的文件读回**渲染预览图，顺带验证格式与偏移 |
| `--line-gap N` | 行间距（默认 2） |

默认输出（全部 BMP 常用字）：**22,630 字形 / 726 KB**

### 文件格式 UFB1

```
Header 32B: magic'UFB1' ver flags cell_h=16 baseline=14 half_adv=8 \
            full_adv=16 line_gap cjk_first cjk_count cjk_off misc_count misc_off
misc 索引表: misc_count × 12B (u32 codepoint, u32 glyph_off, u32 advance)
CJK 位图区: cjk_count × 32B   ← 索引 = cp - cjk_first，O(1)
misc 位图区: misc_count × 32B
```

每个字形定长 **16×16 = 32 字节**（MONO_HLSB，MSB=最左像素）；ASCII 左对齐、
`advance=8`，CJK `advance=16`。定长 → 直接 blit，无分支。
默认 **natural 语义（1=墨）**；`--panel` 则整体反相。

### 设备端使用

```python
import framebuf
from unifont import Unifont

font = Unifont("/fonts/unifont16.bin")
buf = bytearray(400 * 300 // 8)
fb = framebuf.FrameBuffer(buf, 400, 300, framebuf.MONO_HLSB)
fb.fill(0)                                       # 1=墨，0=底
font.draw(fb, "春眠不觉晓，处处闻啼鸟。", 8, 16)   # 默认 ink=1
font.draw(fb, "反白", 8, 60, ink=0)              # 在已填 1 的实心块上画浅字
font.draw_wrapped(fb, long_text, 8, 90, 392)      # 自动折行，返回下一行 y
print(font.text_width("你好world"), font.line_height)
```

### 尺寸与排版参考

| 内容 | 字形数 | 体积 |
|---|---|---|
| 默认（ASCII + 拉丁 + 标点 + 全角 + CJK 基本区） | 22,630 | **726 KB** |
| 仅 CJK 基本区 | 20,992 | 656 KB |
| ASCII + 拉丁 + 标点（约） | ~1,600 | ~50 KB |

- 行高 = `cell_h + line_gap` = 16 + 2 = **18 px**；
- 400×300 屏幕：**25 个汉字/行 × 16 行**。
- 一页 800 字 ≈ 几十 ms（定长 32B + C 层 blit）；实际瓶颈是墨水屏刷新本身。
- 字库整体读进内存（726 KB，落 PSRAM），之后无文件 IO。

### 授权

GNU Unifont 双许可（SIL OFL 1.1 / GPL-2.0+ 带字体嵌入例外）。本项目按 SIL OFL 1.1 使用，
许可文本见 `LICENSES/OFL-1.1.txt`，出处 <https://unifoundry.com/unifont/>。
分发时请一并附带许可与出处。

---

## 5. 测试项说明

| 名称 | 内容 | 能看出什么问题 |
|---|---|---|
| `info` | 引脚/固件/内存信息、黑白色块、棋盘格 | 接线是否正确、SPI 是否通 |
| `shapes` | 线、矩形、实心矩形、椭圆、反白文字 | 基本绘图是否正常 |
| `font` | 全部 ASCII（8×8）、x2/x3/x4 放大、反白 | 字体渲染与放大 |
| `gray` | 4×4 Bayer 抖动的“灰度”渐变和灰阶块 | 抖动效果、对比度 |
| `align` | 边框、四角标记、中心十字、10px 网格 | 有没有 1px 偏移 / 裁切 |
| `init` | `init()` 与 `init_min()` 两种初始化对比 | 哪一种在你板子上背景更干净 |
| `refresh` | full / fast / partial 三种波形耗时对比 | 刷新速度与残影 |
| `partial` | 局部刷新计数器 + 进度条 | 局刷是否可用、残影累积速度 |
| `done` | 结束页 | — |

刷新模式用法（与驱动对应）：

```python
epd.init()                 # 全刷波形
c.show("full")             # 0xF7，对比度最好，约 1.5~2 s

epd.init_fast(1.0)         # 快刷波形
c.show("fast")             # 0xC7，约 1 s，残影略重

epd.init()                 # 局部刷新用全刷波形表
c.show("partial")          # 0xFF，只重画变化区域，约 1 s
```

长时间频繁局刷会累积残影，Demo 里每 25 帧自动全刷一次清干净。

---

## 6. 排错

**一直 `e-Paper busy timeout`**
- 检查 BUSY 接线和 GPIO 号。SSD1619 是 **高电平=忙**；个别 UC8151D 模块是低电平忙，若你的模块是反的，把驱动 `_wait_busy()` 里的判断改成 `== 0`。
- 检查 RST/DC/CS 是否接错，SPI 是否被别的设备占用。

**花屏 / 雪花 / 只显示噪点**
- 确认屏幕是 400×300 的 SSD1619/UC8151D 4.2"；分辨率不对会错位。
- 先跑 `t_init_check`，换 `init_min()` 试试。
- 降低 `SPI_BAUD`（4 MHz→2 MHz），杜邦线太长/接触不良时很有效。

**整屏纯白或纯黑不动**
- 确认 `VCC=3.3V`、`GND` 共地。
- 看 `t_info` 是否弹出，若卡在 `epd.init()` 多半是 BUSY 或 RST 问题。

**画面上下/左右颠倒**
- 驱动里的 Data Entry Mode / X、Y 窗口是按 400×300 整帧写的。若需要翻转，在 `display()` 前把 `buf` 旋转 180°（可用 `framebuf` 的 `fb.scroll` 变通或自己做映射）。

**报 `ImportError: can't import epd_ssd1619`**
- 驱动没上传成功。用 `mpremote connect PORT fs ls` 看一下，或把驱动放设备根目录。

**想省电**
- 显示完调 `epd.sleep()`，再次显示时 `c.show(...)` 会自动重新初始化。

---

## 7. 后续做阅读器

这个 Demo 的 `Canvas.draw_text / dither_rect` 可以直接复用到阅读器界面：
- 分页/翻页：全刷 `full`，翻页之间的小变化用 `partial`。
- 正文排版：先用 8×8 或自备点阵字库算好换行，再整帧送显。
- 需要中文就要加字库（例如 16×16 点阵字库，或把字模存到 PSRAM/flash 里按需取）。
