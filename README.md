# uPyReader — MicroPython 墨水屏阅读器（ESP32-S3-N16R8 + SSD1619 4.2"）

```
uPyReader/
├── README.md                   # 本文档
├── ESP32_GENERIC_S3-...bin     # MicroPython 固件（已刷入；*.bin 不入库）
├── src/                        # 只放 MicroPython 源码 → 设备根目录
│   ├── main.py                 # ★ 主界面（开机自动运行）
│   ├── driver/                 # 硬件层：配置 + 驱动
│   │   ├── hwconfig.py         # ★ 引脚/硬件参数的唯一配置源
│   │   ├── epd_ssd1619.py      # 驱动：HINK-E042A13-A0 / SSD1619 4.2" 400x300
│   │   ├── epdlut.py           # 从面板 OTP 读波形并裁成不闪的局刷 LUT
│   │   ├── rotary.py           # 旋转编码器（正交）+ 按键驱动
│   │   ├── sysinfo.py          # 系统信息：芯片/Flash/PSRAM/MAC
│   │   └── sdcard.py           # 挂载 TF 卡到 /sd（原生 SDMMC）
│   └── ui/                     # 绘制层：画布 + 页面
│       ├── canvas.py           # 画布 + 文本对齐 + 列表菜单 + 信息页
│       ├── unifont.py          # UFB1 位图字库读取 + 渲染
│       ├── about.py            # “关于本机”页面
│       ├── settings.py         # “固件设置”页面 + 配置持久化
│       └── reader.py           # 小说浏览 / 分页 / 阅读进度
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
├── driver/                   # 硬件层（Python 包）
│   ├── hwconfig.py
│   ├── epd_ssd1619.py
│   ├── epdlut.py
│   ├── rotary.py
│   ├── sysinfo.py
│   └── sdcard.py
├── ui/                       # 绘制层（Python 包）
│   ├── canvas.py
│   ├── unifont.py
│   ├── about.py
│   ├── settings.py
│   └── reader.py
└── fonts/
    └── unifont16.bin
```

- `driver/`、`ui/` 是 Python 包（各含一个 `__init__.py`）；导入写作
  `from driver import epdlut`、`from ui import canvas`。

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

**所有引脚都集中在 `src/driver/hwconfig.py`** —— 改接线只改那一个文件，
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
cd /home/ygbs/下载/uPyReader
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
`src/driver/epd_ssd1619.py` → `/driver/epd_ssd1619.py`，
`assets/fonts/unifont16.bin` → `/fonts/unifont16.bin`。

> 实现细节：脚本用 `mpremote cp -r ... :.`（远端当前目录）而不是 `:`。
> 因为 `mpremote` 对 `:` 是否“已存在”的判断依赖 `os.stat("")`，行为不稳；
> `:.` 语义明确，且反复执行不会产生 `driver/driver` 这种嵌套。

### 手动命令（等价做法）

```bash
cd /home/ygbs/下载/uPyReader
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
`src/driver/epd_ssd1619.py` 上传到设备的 `/driver`，把 `src/main.py` 上传到设备根目录，
然后点运行。

> Demo 里的导入逻辑会把 `src/` 根（设备上即 `/`）加入 `sys.path`，因此
> `driver/`、`ui/` 两个包无论从哪运行都能被找到。

---

## 3. 运行与主界面

### 主界面（开机自动运行）

`src/main.py` 上传到设备根目录后，MicroPython **开机自动执行 `main.py`**，
上电即进主菜单：

```
┌ uPyReader ────────────────────────────┐
│ ▶ 继续阅读                小说.txt   │  ← 选中项画方框 + ▶
│   浏览文件                    1 本   │  ← Flash 里的 .txt 数量
│   关于本机                ESP32-S3   │
│   固件设置                     8-12-0│
│   网络                            关 │
├─────────────────────────────────────┤
│ 旋转选择   按下确认                  │
└─────────────────────────────────────┘
```

菜单共 6 项（「插件」在「网络」下方），本机一屏 5 行；超过一屏时列表可滚动，
右侧会画一条**滚动条**表示当前位置。

> 「固件设置」右侧的提示是 `全刷-局刷深度-字符间距` 的紧凑格式，
> 例如 `N-16-2`（`N` = 不全刷；即 全刷间隔=N、局刷深度=16、字符间距=2px）。

操作：

| 动作 | 效果 |
|---|---|
| 旋转编码器 | 上下移动选中项（循环，首尾相接） |
| 按下「继续阅读」 | 直接打开上次读到的那本书、那个位置 |
| 按下「浏览文件」 | 列出 Flash 里所有 `.txt`，进入后旋转选择、按下阅读 |
| 按下「关于本机」 | 进入信息页 |
| 按下「固件设置」 | 进入设置页（全刷间隔 / 局刷深度 / 字符间距） |
| 按下「网络」 | 进入网络页（WLAN 开关 / 扫描 Wi-Fi） |
| 按下「插件」 | 底部提示「子页面待实现」，1.5 s 后恢复 |
| 长按 | 主界面暂未使用；子页面/文件列表里是「返回」 |

### 「关于本机」页面

```
┌ 关于本机 ──────────────────────────┐
│ 屏幕    HINK-E042A13-A0 SYX1802     │
│ 温度    22 °C                       │  ← 面板内置传感器, 读一次约 2ms
│ 模块    Generic ESP32S3 module      │
│         with Octal-SPIRAM           │
│ 固件    v1.29.0  ESP32_GENERIC_S3-  │
│         SPIRAM_OCT-20260824-v1.29.0 │
│ 主频    240 MHz                     │
│ Flash   16 MB                       │
│ PSRAM   8 MB                        │
│ TF 卡   SDMMC 4-bit · 939 MB        │
│ MAC     7C:DF:A1:12:34:56           │
├─────────────────────────────────────┤
│ 按下或长按返回                       │
└─────────────────────────────────────┘
```

数据来源见 `driver/sysinfo.py`：**Flash** 由自动创建的 `vfs` 分区末端推断，
**PSRAM** 取 IDF 堆区里最大的一块。

- 光标移动/翻页统一走**自裁局刷 LUT**送显：**不闪**，约 1.8s；**每 8 次**
  （「固件设置」里的“全刷间隔”）插一次 OTP 全刷清残影。把全刷间隔设为
  **「不全刷」**后软件不再自动全刷，改由阅读界面**短按**手动全刷。原理见下面「不闪的翻页（局刷 LUT）」。
- 选中项画一圈方框 + `▶`，行间用虚线 —— 比整行反白黑块像素变化更少，更适合局刷。
- 列表超过一屏时可滚动（主菜单 / 文件列表 / 网络热点），右侧画滚动条表示当前位置。
- **子页面**：「关于本机」「固件设置」「网络」已实现；文件列表/阅读界面见下。
- `main.py` 是死循环；要回 REPL 按 `Ctrl-C`，脚本会优雅退出并让屏休眠。

### 「固件设置」页面

主界面旋转到「固件设置」→ 按下进入。这里能调三项（默认全刷间隔 8 / 局刷深度 12 / 字符间距 0）：

| 设置 | 默认 | 范围 | 说明 |
|---|---|---|---|
| 全刷间隔 | 8 | 1~16 / 不全刷 | 每多少次局刷后做一次 OTP 全刷，清除残影；越小越干净但越闪越慢。滚到 **16 再往上滚一格**即设为「不全刷」 |
| 局刷深度 | 12 | 0~16 | 局刷波形的重复次数-1：0=最快（~0.36s，残影重），越大字越黑实、越慢 |
| 字符间距 | 0 | 0~20 | 阅读界面书籍文字**每行之间的额外间距**（像素）：0=最紧凑（字库自带行距），越大行距越宽、每屏行数越少 |

操作：**旋转**选择项目 → **按下**进入调整（数值变成 `< 8 >`）→ **旋转**改数值
（「全刷间隔」滚到 16 后再滚一格显示 `< 不全刷 >`）→ 再**按下**确认；
**长按**随时保存并返回主界面。

设置保存在设备根目录 `/settings.json`：

```json
{"full_every": 8, "partial_rep": 12, "line_gap": 0}
```

改完立即生效（局刷深度会即时重裁 LUT；字符间距在**下次打开书籍**时套用），
重开机也保持，不必改代码。

### 「网络」页面

主界面旋转到「网络」→ 按下进入。页面第一行是 **WLAN** 开关（左 `WLAN`、右 `关/开`，
下方为**实线**分隔符），其后是扫描到的热点（左 SSID、右信号强度 `dBm`，按信号从强到弱）。

- 在 `WLAN` 行**按下** → 打开 WLAN 并扫描一次（显示「正在扫描 Wi-Fi…」）；再按一下关闭。
- 旋转在 `WLAN` 与各热点之间选择；热点多于一屏时可滚动并有滚动条。
- 主界面「网络」右侧显示 `关` / `开`。

扫描逻辑在 `src/ui/network.py`；用 MicroPython 的 `network.WLAN(STA_IF)` 实现。

### 用 TF 卡放书（microSD，可选）

除了设备内部 Flash，也可以把书放 TF 卡（**FAT32 + MBR 分区表**）。
卡上的书会被「浏览文件」自动列出来，路径形如 `/sd/books/xxx.txt`。

驱动用 ESP32-S3 **原生 SDMMC**（`machine.SDCard(slot=1)`，经 GPIO matrix 任意
布线）：先 4-bit，失败自动降 1-bit（只用 DAT0）。引脚见 `driver/hwconfig.py`：

| 模块丝印 | 含义 | GPIO | `hwconfig` |
|---|---|---|---|
| CLK | 时钟 | 13 | `SD_CLK` |
| CMD | 命令 | 14 | `SD_CMD` |
| DAT0 | 数据 0 | 15 | `SD_D0` |
| DAT1 | 数据 1 | 16 | `SD_D1` |
| DAT2 | 数据 2 | 17 | `SD_D2` |
| DAT3 | 数据 3 | 18 | `SD_D3` |
| SD-CD | 卡检测（可选） | 21 | `SD_CD` |

> ⚠️ 带 AMS1117/电平转换的模块 **VCC 接 5V** 才能稳住 3.3V（压差大）；
> 裸 3.3V 模块接 3V3。信号脚一律 3.3V。

> 注：屏幕走 `SPI(1)=SPI2_HOST`，SDMMC 不使用 SPI 主机，两者互不干扰。
> 正因如此，`epdlut.make_spi()` 仍显式传 `miso=None`：ESP32-S3 的 `SPI(1)` 默认
> MISO 是 GPIO13，而 GPIO13 现在是 SDMMC 的 CLK，不能让墨水屏那路 SPI 抢走。

> 📉 **关于速度**：本板 N16R8 的 8MB Octal-PSRAM 与 SDMMC 的 DMA 存在带宽争用，
> MicroPython 的堆又在 PSRAM 上，因此顺序读实测只有约 **0.9 MB/s**（与
> [esp-idf#11628](https://github.com/espressif/esp-idf/issues/11628) 的现象一致，
> 并非卡或模块的问题）。阅读器每页只读 4KB，实测约 **7 ms**，完全够用。
> 想提速需要重编固件（把 SD 缓冲区放进内部 RAM / 调大 `FATFS_VFS_FSTAT_BLKSIZE`）。

启动时自动挂到 `/sd`，日志会打印 `TF 卡: 已挂载 … (SDMMC 4-bit)`；没插卡也不影响使用。
阅读进度仍存在**设备内部**的 `/books/.state/progress.json`，所以拔卡/换卡进度不丢。

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
| 短按 | 默认：保存进度并返回主界面；**「不全刷」模式：手动全刷一次（不退出）** |
| 长按 | 保存进度并返回主界面 |

分页与进度由 `ui/reader.py` 负责：

- 按**字节偏移**分页：每页从上次位置 `seek` 读一小块（4 KB），逐字排版，
  记下下一页的字节起点；**不把整本书读进内存**。
- 进度存在 `/books/.state/progress.json`：当前页偏移 + 最近 128 页的起点，
  **每翻一页都会写盘**，所以断电/重启后「继续阅读」仍从原处开始。
- 只保留有限条历史（`HIST=128`），JSON 恒定 ~1 KB，写盘约几十毫秒，
  既快又省 Flash 寿命。

### 不闪的翻页（局刷 LUT）

这块屏的 OTP 里只烧了「全刷」波形（实测无论用 `0xF7/0xC7/0xFF` 哪个模式都要
~3.5s 且整屏闪），所以普通模式翻页一定会闪。真正的无闪翻页是这样做的：

1. 启动时用 **bit-bang** 在单线 `SDI` 上把面板 OTP 的波形表（`0x33`）读回来
   （SSD1619 的 4 线 SPI 是半双工，同一根线可读，不用额外接线）；
2. 把它裁成「单阶段」短波形：只留第 4 组（`gi=4`，对应 `vs=00 02 14 66 48`，
   实测画质最干净）的阶段时间 `(2,2,2,0)`，`repeat` 由「局刷深度」决定
   （默认 12，速度与残影最平衡）；
3. 翻页时用 `0x32` 写回这张 LUT，再用 **`0x22=0xCF`**（`MODE1|MODE2`，
   **不带 `LOAD_LUT`**，否则会被 OTP 覆盖）触发。

效果：翻页 **~1.8s、不闪**（= 240ms 控制器固定开销 + 20.4ms × 6 相位单位 ×
(12+1)，SPI 也从 4MHz 提到 20MHz），只有文字本身在轻微变化。把「局刷深度」调到
最低 0 可到 **~0.36s**，但残影明显。普通次用局刷，
**每「全刷间隔」次（默认 8）移动/翻页**用 OTP 全刷一次清残影；把全刷间隔设为
「不全刷」则完全由用户掌控：阅读界面**短按**手动全刷，**长按**退出。相关代码：
`epdlut.read_otp_lut() / epdlut.make_partial_lut()`、`epd.display_lut()`、
`Canvas.show_lut()`。

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
from ui.unifont import Unifont

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

**局刷发虚 / 残影很重 / 仍然整屏闪**
- 局刷确实会累积残影，进「固件设置」把**全刷间隔**调小（更频繁全刷）即可；
  若想要「不自动闪」，把它滚到 16 再滚一格设为**「不全刷」**，阅读时按需短按全刷。
- 字发虚说明局刷波形驱动不足，把**局刷深度**调大（更“实”、更慢）。
- 不同批次模组的 OTP 波形可能不同，必要时试 `epd.init_min()` 重新初始化。

**报 `ImportError: can't import driver.epd_ssd1619` / `ui.unifont`**
- 驱动/字库模块没上传成功。用 `mpremote connect PORT fs tree :` 看一下，
  应存在 `/driver/epd_ssd1619.py` 与 `/ui/unifont.py`。

**报 `OSError: 找不到字库 unifont16.bin`**
- 字库还没生成或没上传。先在 PC 上：`python3 tools/build_font.py`，
  再 `tools/upload.sh`，设备上应存在 `/fonts/unifont16.bin`。

**TF 卡读不到 / 挂载失败**
- 最常见的是 **CLK/CMD/DAT0 接错**（模块常标 `CLK` / `CMD` / `DAT0..DAT3`），或某根
  杜邦线/焊点**接触不良** —— 卡会完全无应答。
- 带 AMS1117/电平转换的模块 **VCC 接 5V**；只有电阻的 3.3V 模块接 3V3。
- 卡可能锁在 SD 模式：整板断电一次再上电。
- 卡要是 **FAT32 + MBR**（PC 上“格式化为 FAT32”即可），启动日志会有
  `TF 卡: 已挂载 /sd …`，卡上的 `books/` 会被「浏览文件」自动列出。

**想省电**
- 显示完调 `epd.sleep()`，再次显示时 `c.show()` 会自动重新初始化。

---

## 6. 已知问题

### 6.1 SDMMC 顺序读写只有 ~0.9 MB/s（PSRAM ↔ SDMMC DMA 争用）

**现象**：TF 卡挂载、读取都正确，但连续大块读只有约 0.9 MB/s（写更慢），
而同一张卡用读卡器在 PC 上有 3~4 MB/s。

**不是卡、也不是模块的问题**。我对裸转接模块做过对照：开/关内部上拉、
20/40 MHz 几乎没差别，说明既不是信号完整性也不是时钟，而是 ESP32-S3 上
**SDMMC 的 DMA 缓冲区落在了 PSRAM 里**：

- 本板 N16R8 有 8 MB **Octal-PSRAM**；MicroPython 的 Python 堆整体在 PSRAM 上
  （`gc.mem_free ≈ 8.3 MB`），所以 FatFs 缓存和 `readblocks()` 用的 buffer 都在 PSRAM。
- SDMMC 的 DMA 访问 PSRAM 要经过 cache/PSRAM 控制器，并和 CPU 抢带宽，
  平均每个 512 B 扇区多花约 0.6 ms。
- 这是 ESP-IDF 的已知现象，见
  [esp-idf#11628](https://github.com/espressif/esp-idf/issues/11628)
  （该 issue 的结论是“把 SD 缓冲区放进内部 RAM”，而不是关掉 PSRAM）。
- 另一个叠加因素是固件的 FatFs 块大小默认 512（见
  [arduino-esp32#10785](https://github.com/espressif/arduino-esp32/issues/10785)），
  这是编译期选项，运行时改不了。

**影响**：对阅读器几乎为零 —— 每页只从卡里读 4 KB，实测约 **7 ms**。
只有整本顺序拷贝/备份大文件时才明显。**PSRAM 与 TF 速度不是二选一**：
只要把 SD 的几 KB 传输缓冲放进**内部 SRAM**，PSRAM 照用、SD 也能跑满；
当前慢只是因为固件没做这件事。

**想真正提速（需要重编固件，改 Python 文件没用）**：
1. 编译时设 `CONFIG_FATFS_VFS_FSTAT_BLKSIZE=4096`（文件 I/O 约提速 4~6 倍）；
2. 改 `ports/esp32/machine_sdcard.c`，让 `readblocks/writeblocks` 用
   `heap_caps_malloc(..., MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL)` 的临时缓冲做 bounce；
3. 或用自定义块设备自行调用 `esp_vfs_fat_sdmmc_mount`，把缓冲显式放内部 RAM。

### 6.2 `SD-CD` 卡检测在本模块上不可用

有些 TF 转接模块的 `SD-CD` 是卡座里的机械开关。本项目的裸转接模块该脚**悬空**：
实测 `PULL_UP` 读 1、`PULL_DOWN` 读 0，说明它没接地，无法判断有无卡。
因此代码不依赖卡检测（`hwconfig.SD_CD` 仅作记录），挂载失败就当成“未插卡”，
不影响使用。热插拔后想重新挂载，手动调 `sdcard.mount(force=True)` 即可。

### 6.3 为什么砍掉了 SPI 模式挂载

早期版本用 SPI（`machine.SDCard(slot=2)` + 一组 SPI 引脚）。它要额外一组引脚、
受 `SPI(1)` 默认 MISO=GPIO13 的干扰，而且比 SDMMC 更慢；现在统一走原生 SDMMC
（4-bit 失败自动降 1-bit），见 `driver/sdcard.py`。

---

## 7. 后续做更强的阅读器

现在已经能浏览 /books 下的 `.txt`、逐页阅读并记忆进度。还可以继续加：

- **整页缓存**：把渲染好的整页（15 KB）存进 PSRAM，翻页只做一次取反 + 送显，
  渲染成本几乎为零，瓶颈只剩墨水屏刷新本身。
- **分页索引 / 目录**：章节识别、跳章、书签。
- **调局刷速度/画质**：进「固件设置」调**局刷深度** / **全刷间隔**；再底层可改
  `driver/epdlut.py` 里的 `PHASES` / `KEEP_GROUP` 重新裁波形。
- **插件接口**：`/plugins/<name>/main.py` + `register(api)`；插件商店走 MicroPython 自带 `mip`。

---

## 许可证

本项目以 **GNU GPLv3-or-later**（SPDX: `GPL-3.0-or-later`）发布：你可以自由
使用、研究、修改、再分发（包括商业用途），衍生作品必须保持同样的自由、以同样
的许可证发布。完整法律条款见 [`LICENSE`](LICENSE)。

位图字库来自 **GNU Unifont**，按 **SIL OFL 1.1** 使用，见 [`NOTICE`](NOTICE)
与 [`LICENSES/OFL-1.1.txt`](LICENSES/OFL-1.1.txt)。
