#!/usr/bin/env bash
#
# upload.sh — 把 src/ 下的 MicroPython 代码同步到开发板根目录, 并把 books/ 下的
#             小说同步到设备 /books/
#
# 用法:
#   ./upload.sh                     # 默认端口 /dev/ttyACM0，上传 src/ 下全部代码
#   ./upload.sh /dev/ttyUSB0        # 指定串口
#   FORCE=1 ./upload.sh             # 强制重传（默认按 sha256 跳过未改动文件）
#   CLEAN=1 ./upload.sh             # 上传前先删除对应的远端目录（用于删除本地已移除的文件）
#   RUN=1 ./upload.sh               # 上传后执行 main.main()
#   SYNC_BOOKS=1 ./upload.sh        # 同时把 books/*.txt 传到设备 /books/
#   RUN='import xxx; xxx.main()' ./upload.sh   # 上传后执行任意 Python 片段
#   CHMOD=0 ./upload.sh             # 跳过上传前的 sudo chmod 777 <PORT>
#
# 目录约定:
#   仓库根/
#     ├── src/           ← 只放 MicroPython 源码；其下顶层条目原样映射到设备根
#     ├── assets/        ← 资源文件(可选)；其下顶层条目也映射到设备根
#     ├── books/         ← 小说(可选)；其下 *.txt 同步到设备 /books/
#     ├── tools/         ← 本脚本等 PC 侧工具
#     └── README.md
#
#   例: src/driver/epd_ssd1619.py  ->  设备 /driver/epd_ssd1619.py
#       src/main.py                 ->  设备 /main.py
#       assets/fonts/unifont16.bin  ->  设备 /fonts/unifont16.bin
#
# 依赖: mpremote  (uv tool install mpremote  或  python3 -m pip install --user mpremote)
#
set -euo pipefail

PORT="${1:-/dev/ttyACM0}"
MP="${MPREMOTE:-mpremote}"
FORCE="${FORCE:-0}"
CLEAN="${CLEAN:-0}"
SYNC_BOOKS="${SYNC_BOOKS:-0}"     # =1 时把 books/*.txt 同步到设备 /books/(小说较大, 默认不传)
RUN="${RUN:-}"
CHMOD="${CHMOD:-1}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/src"
ASSETS="$REPO/assets"
BOOKS="$REPO/books"
DEST=":."          # 远端当前目录（设备根）。注意用 ":.",不要用 ":",原因见下方注释

# ----------------------------------------------------------------------------
# 说明：为什么目标是 ":.",而不是 ":"
#   mpremote 的 `cp -r` 目标若不存在，会把源目录的内容直接铺到目标；
#   而 ":" 是否被判定为"已存在"依赖 os.stat("")，行为不稳。
#   ":.（当前目录）"必定存在，且语义是"复制进该目录"，因此可反复执行不会
#   产生 driver/driver 这种嵌套。
# ----------------------------------------------------------------------------

die() { echo "错误: $*" >&2; exit 1; }

# ---- 前置检查 ---------------------------------------------------------------
command -v "$MP" >/dev/null 2>&1 || die "找不到 mpremote。安装: uv tool install mpremote"
[ -d "$SRC" ] || die "找不到源码目录: $SRC"
[ -e "$PORT" ] || echo "警告: $PORT 不存在，请确认板子已插好 (ls /dev/ttyACM* /dev/ttyUSB*)"

# ---- 串口权限：每次重新插拔后 /dev/ttyACM* 或 /dev/ttyUSB* 的权限都可能重置 ----
# 先给当前端口放开权限，避免上传时报 Permission denied。
# 若不需要（例如你已在 dialout 组）可用 CHMOD=0 跳过。
if [ "$CHMOD" = "1" ] && [ -e "$PORT" ]; then
    echo ">> 设置串口权限: sudo chmod 777 $PORT"
    if ! sudo chmod 777 "$PORT"; then
        echo "警告: chmod 失败；若上传报 Permission denied，请检查串口权限或加入 dialout 组"
    fi
fi

# ---- 清理本地 Python 缓存,避免把 __pycache__ 传上去 -------------------------
find "$SRC" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$SRC" -type f -name '*.pyc' -delete 2>/dev/null || true

# ---- 收集上传条目 -----------------------------------------------------------
#   src/    -> 设备根目录（源码）
#   assets/ -> 设备根目录（资源，如 assets/fonts/unifont16.bin -> /fonts/unifont16.bin）
ROOTS=("$SRC")
if [ -d "$ASSETS" ]; then
    ROOTS+=("$ASSETS")
fi

ENTRIES=()
for root in "${ROOTS[@]}"; do
    while IFS= read -r -d '' e; do
        base="$(basename "$e")"
        case "$base" in
            .*|*.md|Thumbs.db|*.pyc|__pycache__) continue ;;
        esac
        ENTRIES+=("$e")
    done < <(find "$root" -mindepth 1 -maxdepth 1 -print0 | sort -z)
done

[ "${#ENTRIES[@]}" -gt 0 ] || die "src/ 和 assets/ 都是空的，没有可上传的内容"

echo ">> 仓库   : $REPO"
echo ">> 目标   : $PORT  (设备根目录 /)"
echo ">> 待上传 :"
for e in "${ENTRIES[@]}"; do
    echo "     ${e#"$REPO"/}"
done

# ---- 可选：先清理远端对应目录 ----------------------------------------------
if [ "$CLEAN" = "1" ]; then
    echo ">> CLEAN=1：清理远端对应目录"
    for e in "${ENTRIES[@]}"; do
        if [ -d "$e" ]; then
            base="$(basename "$e")"
            echo "     rm -r :$base"
            "$MP" connect "$PORT" fs rm -r ":$base" || true
        fi
    done
fi

# ---- 上传（单次连接；默认按 sha256 跳过未改动文件）-------------------------
CP_FLAGS=(-r)
if [ "$FORCE" = "1" ]; then
    CP_FLAGS+=(-f)
fi

echo ">> 上传中 ..."
"$MP" connect "$PORT" cp "${CP_FLAGS[@]}" "${ENTRIES[@]}" "$DEST"

# ---- 核对设备上的文件树 -----------------------------------------------------
echo
echo ">> 设备文件树 (/):"
"$MP" connect "$PORT" fs tree : || true

# ---- 可选：同步小说到设备 /books -------------------------------------------
#   books/ 下的 .txt 只上传到开发板，不进仓库（.gitignore 已忽略 *.txt）。
#   小说体积大、串口传输慢，所以默认不传；需要时用 SYNC_BOOKS=1 显式开启。
if [ "$SYNC_BOOKS" = "1" ] && [ -d "$BOOKS" ]; then
    BENTRIES=()
    while IFS= read -r -d '' e; do
        BENTRIES+=("$e")
    done < <(find "$BOOKS" -mindepth 1 -maxdepth 1 -type f ! -name '.*' -print0 | sort -z)
    if [ "${#BENTRIES[@]}" -gt 0 ]; then
        echo
        echo ">> 同步小说到设备 /books ..."
        "$MP" connect "$PORT" fs mkdir :books 2>/dev/null || true
        "$MP" connect "$PORT" cp -f "${BENTRIES[@]}" :books/
    fi
fi

# ---- 可选：运行 -------------------------------------------------------------
if [ "$RUN" = "1" ]; then
    RUN='import main; main.main()'
fi
if [ -n "$RUN" ]; then
    echo
    echo ">> 运行: $RUN"
    "$MP" connect "$PORT" exec "$RUN"
fi

echo ">> 完成"
