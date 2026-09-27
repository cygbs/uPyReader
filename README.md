# 墨水屏阅读器（ESP32-S3-N16R8 + SSD1619 4.2"）

```
阅读器/
├── README.md                   # 本文档
├── ESP32_GENERIC_S3-...bin     # MicroPython 固件（已刷入；*.bin 不入库）
├── src/                        # 只放 MicroPython 源码 → 设备根目录
│   ├── main.py                 # ★ 主界面（开机自动运行）
│   └── library/
│       ├── hwconfig.py         # ★ 引脚/硬件参数的唯一配置源
│       ├── ui.py               # 画布 + 文本对齐 + 列表菜单 + 信息页
│       ├── rotary.py           # 旋转编码器（正交）+ 按键驱动
│       ├── sysinfo.py          # 系统信息：芯片/Flash/PSRAM/MAC
│       ├── about.py            # “关于本机”页面
│       ├── reader.py           # 小说浏览 / 分页 / 阅读进度
│       ├── epd_ssd1619.py      # 驱动：HINK-E042A13-A0 / SSD1619 4.2" 400x300
│       └── unifont.py          # UFB1 位图字库读取 + 渲染
├── assets/                     # 资源 → 设备根目录
│   └── fonts/
│       └── unifont16.bin       # 生成物，不入库（由 tools/build_font.py 生成）
├── books/                      # 本地小说（*.txt 不入库），上传到设备 /books/
└── tools/                      # PC 侧工具
    ├── upload.sh               # 一键同步 src/ + assets/ + books/ 到设备
    └── build_font.py           # Unifont .hex → UFB1 二进制字库
```

对应到设备上的布局：

```
/                 (设备根目录)
├── main.py                   ← 开机自动运行：主界面
├── library/
│   ├── hwconfig.py
│   ├── ui.py
│   ├── rotary.py
│   ├── sysinfo.py
│   ├── about.py
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

**所有引脚都集中在 `src/library/hwconfig.py`** —— 改接线只改那一个文件，
`main.py` 从它读。

### 旋转编码器（增量式，带按键）

模块丝印 `GND S1 S2 KEY 5V`，接法：

| 编码器丝印 | 含义 | 默认接到 | 变量 |
|---|---|---|---|
| `5V` | 电源（**接 3V3 即可**） | 3V3 | — |
| `GND` | 地 | GND | — |
| `S1` | 正交 A 相 | GPIO **4** | `ENC_A` |
| `S2` | 正交 B 相 | GPIO **5** | `ENC_B` |
| `KEY` | 按下时与 GND 接通（低有效） | GPIO **6** | `ENC_KEY` |

- 三个脚都启用**内部上拉**；模块自带 10k 上拉也没影响。
- 手感不对（转一格跳太多/太少）→ 用 `main.encoder_debug()` 校准 `ENC_STEPS_PER_DETENT`。

注意：
- `SDI` = MOSI（ESP32 输出数据给屏幕），`SCLK` = 时钟。屏是只写设备，
  **没有 MISO / 回读引脚**，SPI 只初始化 `sck` + `mosi` 即可（代码已如此）。
- 屏幕是 3.3 V 供电，**不要接 5 V**。
- 这些 GPIO 要避开：**7–12**（墨水屏）、**19/20**（USB）、**26–37**（内部 Flash /
  Octal-PSRAM，N16R8 的 R8 用掉 33–37）、**39–42**（JTAG）、**43/44**（UART0）、
  **0/3/45/46**（strapping）。上面默认用到的引脚都是安全的。
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
同步到设备根目录，并把 `books/` 下的 `.txt` 同步到设备 `/books/`；默认按 sha256
跳过未改动文件：

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
| `SYNC_BOOKS=1` | 把 `books/*.txt` 同步到设备 `/books/`（小说大，默认不传） |
| `RUN=1` | 上传后执行 `main.main()` |
| `RUN='import xxx; xxx.main()'` | 上传后执行任意 Python 片段 |
| `MPREMOTE=/path/to/mpremote` | 指定 mpremote 可执行文件 |
| `CHMOD=0` | 跳过上传前自动执行的 `sudo chmod 777 <PORT>` |

> 默认每次上传前会先 `sudo chmod 777 <端口>`（重新插拔后串口权限常被重置），
> 可能会提示输入 sudo 密码。若你已把账号加入 `dialout` 组、无需此步，可加 `CHMOD=0`。

示例：

```bash
FORCE=1 tools/upload.sh                      # 全量重传
RUN=1 tools/upload.sh                        # 传完就进主界面
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
mpremote connect $PORT exec "import main; main.main()"
```

### Thonny

打开 Thonny → 右下角解释器选 `MicroPython (ESP32)` + 端口 → 在“文件”面板把
`src/library/epd_ssd1619.py` 上传到设备的 `/library`，把 `src/main.py` 上传到设备根目录，
然后点运行。

> Demo 里的导入逻辑会依次尝试：当前目录 → `library/` → `/library` → `/lib`，放哪都能找到。

---

## 3. 运行与主界面

### 主界面（开机自动运行）

`src/main.py` 上传到设备根目录后，MicroPython **开机自动执行 `main.py`**，
上电即进主菜单：

```
┌ 阅读器主菜单 ─────────────────── v0.2 ┐
│ ▶ 继续阅读                小说.txt   │  ← 选中项整行反白 + ▶
│   浏览文件                    1 本   │  ← Flash 里的 .txt 数量
│   关于本机                ESP32-S3   │
│   固件设置              MicroPython  │
│   插件                        0 个   │
├─────────────────────────────────────┤
│ 旋转选择   按下确认                  │
└─────────────────────────────────────┘
```

操作：

| 动作 | 效果 |
|---|---|
| 旋转编码器 | 上下移动选中项（循环，首尾相接） |
| 按下「继续阅读」 | 直接打开上次读到的那本书、那个位置 |
| 按下「浏览文件」 | 列出 Flash 里所有 `.txt`，进入后旋转选择、按下阅读 |
| 按下「关于本机」 | 进入子页面 |
| 按下其它项 | 底部提示「已选择：xxx · 子页面待实现」，1.5 s 后恢复 |
| 长按 | 主界面暂未使用；子页面/文件列表里是「返回」 |

### 「关于本机」页面

```
┌ 关于本机 ──────────────────────────┐
│ 芯片    ESP32-S3                    │
│ 模块    Generic ESP32S3 module      │
│         with Octal-SPIRAM           │
│ 固件    v1.29.0  ESP32_GENERIC_S3-  │
│         SPIRAM_OCT-20260824-v1.29.0 │
│ 主频    240 MHz                     │
│ Flash   16 MB                       │
│ PSRAM   8 MB                        │
│ MAC     7C:DF:A1:12:34:56           │
├─────────────────────────────────────┤
│ 按下或长按返回                       │
└─────────────────────────────────────┘
```

数据来源见 `library/sysinfo.py`：**Flash** 由自动创建的 `vfs` 分区末端推断，
**PSRAM** 取 IDF 堆区里最大的一块。

- 光标移动走**窗口局部刷新**（`epd.display_partial_rect()`）：只写、只驱动受影响的那两行
  （约 92/300 行），其余像素完全不动。连续移动 15 次后自动插一次全刷清残影。
- 底部提示保持**静态**（不放会变化的计数）—— 否则每次移动都要多刷一条底部区域。
- 局部刷新用的是 `0x3C=0x80` + `0x21=0x00 0x00` 快刷序列（Waveshare 4.2" V2 官方做法）：
  不复位、不重新加载波形，直接复用面板里已有的 LUT。少了这两步，局部刷新会退化成
  “整屏重画”，又慢又闪。
- 回绕（最后一项 → 第一项）时脏区分散，会合并成一个窗口**一次激活**（比两次激活快）。
- **子页面**：「关于本机」已实现；文件列表/阅读界面见下。
- `main.py` 是死循环；要回 REPL 按 `Ctrl-C`，脚本会优雅退出并让屏休眠。

### 阅读小说（浏览文件 / 继续阅读）

把 `.txt` 小说放进设备的 `/books/` 目录（`tools/upload.sh` 会自动把仓库
`books/*.txt` 同步到 `/books/`；`.gitignore` 已忽略 `*.txt`，不会入库）：

```bash
cp /path/to/小说.txt books/     # 放到仓库 books/ 目录
SYNC_BOOKS=1 CHMOD=0 tools/upload.sh   # 上传代码 + 小说(小说大, 传输较慢)
```

主界面 ↓「浏览文件」→ 按下，列出 Flash 里所有 `.txt`：

```
┌ 浏览文件 ────────────────────── 1 本 ┐
│ ▶ 小说.txt                  2.6 MB   │
│                                      │
├─────────────────────────────────────┤
│ 旋转选择   按下阅读   长按返回        │
└─────────────────────────────────────┘
```

进入阅读界面后：

```
┌ 小说.txt              第1页 0% ─────┐
│ 写在“基石”之前                       │
│                                      │
│ ■ 姚海军                             │
│ …                                    │
│ ██████░░░░░░░░░░░░░░░░░░░░░░░░░░░   │  ← 进度条
└─────────────────────────────────────┘
```

| 动作 | 效果 |
|---|---|
| 旋转编码器 | 上一页 / 下一页（每转一档翻一页） |
| 按下 | 保存进度并返回主界面 |
| 长按 | 同上（返回主界面） |

分页与进度由 `library/reader.py` 负责：

- 按**字节偏移**分页：每页从上次位置 `seek` 读一小块（4 KB），逐字排版，
  记下下一页的字节起点；**不把整本书读进内存**。
- 进度存在 `/books/.state/progress.json`：当前页偏移 + 最近 128 页的起点，
  **每翻一页都会写盘**，所以断电/重启后「继续阅读」仍从原处开始。
- 只保留有限条历史（`HIST=128`），JSON 恒定 ~1 KB，写盘约几十毫秒，
  既快又省 Flash 寿命。

REPL 辅助：

```python
import main
main.main()             # 重新进入主界面
main.encoder_debug()    # 编码器自检：校准 ENC_STEPS_PER_DETENT / 确认接线
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

## 5. 排错

**一直 `e-Paper busy timeout`**
- 检查 BUSY 接线和 GPIO 号。SSD1619 是 **高电平=忙**；个别 UC8151D 模块是低电平忙，若你的模块是反的，把驱动 `_wait_busy()` 里的判断改成 `== 0`。
- 检查 RST/DC/CS 是否接错，SPI 是否被别的设备占用。

**花屏 / 雪花 / 只显示噪点**
- 确认屏幕是 400×300 的 SSD1619/UC8151D 4.2"；分辨率不对会错位。
- 在 REPL 里换另一种初始化试试：`epd.init_min()` 然后 `c.show()`。
- 降低 `SPI_BAUD`（4 MHz→2 MHz），杜邦线太长/接触不良时很有效。

**整屏纯白或纯黑不动**
- 确认 `VCC=3.3V`、`GND` 共地。
- 启动时看 `setup()` 的打印：卡在 `init e-paper ...` 多半是 BUSY 或 RST 问题；
  卡在 `load font` 则是字库没上传。

**画面上下/左右颠倒**
- 驱动里的 Data Entry Mode / X、Y 窗口是按 400×300 整帧写的。若需要翻转，在 `display()` 前把 `buf` 旋转 180°（可用 `framebuf` 的 `fb.scroll` 变通或自己做映射）。

**局部刷新残影很重 / 仍然整屏闪**
- 主界面已按官方序列做窗口局刷。若仍异常，可在 `main.py` 里把 `refresh_bands()` 换成
  `c.show("partial")`（整屏局部波形）对比试试，或把 `PARTIAL_LIMIT` 调小（更频繁全刷）。
- 不同批次模组的波形表可能不同，必要时试 `epd.init_min()` 做初始化。

**报 `ImportError: can't import epd_ssd1619` / `unifont`**
- 驱动/字库模块没上传成功。用 `mpremote connect PORT fs tree :` 看一下，
  应存在 `/library/epd_ssd1619.py` 与 `/library/unifont.py`。

**报 `OSError: 找不到字库 unifont16.bin`**
- 字库还没生成或没上传。先在 PC 上：`python3 tools/build_font.py`，
  再 `tools/upload.sh`，设备上应存在 `/fonts/unifont16.bin`。

**想省电**
- 显示完调 `epd.sleep()`，再次显示时 `c.show(...)` 会自动重新初始化。

---

## 6. 后续做更强的阅读器

现在已经能浏览 /books 下的 `.txt`、逐页阅读并记忆进度。还可以继续加：

- **整页缓存**：把渲染好的整页（15 KB）存进 PSRAM，翻页只做一次取反 + 送显，
  渲染成本几乎为零，瓶颈只剩墨水屏刷新本身。
- **分页索引 / 目录**：章节识别、跳章、书签。
- **快刷翻页**：用 `epd.init_fast()` + `c.show("fast")` 把每页 3.5s 降到 ~1s，
  每 N 页插一次全刷清残影。
- **插件接口**：`/plugins/<name>/main.py` + `register(api)`；插件商店走 MicroPython 自带 `mip`。
