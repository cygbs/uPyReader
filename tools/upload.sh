#!/usr/bin/env bash
#
# upload.sh — 把 src/ 下的全部 MicroPython 代码同步到开发板根目录
#
# 用法:
#   ./upload.sh                     # 默认端口 /dev/ttyACM0，上传 src/ 下全部代码
#   ./upload.sh /dev/ttyUSB0        # 指定串口
#   FORCE=1 ./upload.sh             # 强制重传（默认按 sha256 跳过未改动文件）
#   CLEAN=1 ./upload.sh             # 上传前先删除对应的远端目录（用于删除本地已移除的文件）
#   RUN=1 ./upload.sh               # 上传后执行 epd_test.run_all()
#   RUN='import xxx; xxx.main()' ./upload.sh   # 上传后执行任意 Python 片段
#   CHMOD=0 ./upload.sh             # 跳过上传前的 sudo chmod 777 <PORT>
#
# 目录约定:
#   仓库根/
#     ├── src/           ← 只放 MicroPython 源码；其下的顶层条目会原样映射到设备根
#     ├── tools/         ← 本脚本等 PC 侧工具
#     └── README.md
#
#   例: src/library/epd_ssd1619.py  ->  设备 /library/epd_ssd1619.py
#       src/epd_test.py             ->  设备 /epd_test.py
#
# 依赖: mpremote  (uv tool install mpremote  或  python3 -m pip install --user mpremote)
#
set -euo pipefail

PORT="${1:-/dev/ttyACM0}"
MP="${MPREMOTE:-mpremote}"
FORCE="${FORCE:-0}"
CLEAN="${CLEAN:-0}"
RUN="${RUN:-}"
CHMOD="${CHMOD:-1}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/src"
DEST=":."          # 远端当前目录（设备根）。注意用 ":.",不要用 ":",原因见下方注释

# ----------------------------------------------------------------------------
# 说明：为什么目标是 ":.",而不是 ":"
#   mpremote 的 `cp -r` 目标若不存在，会把源目录的内容直接铺到目标；
#   而 ":" 是否被判定为"已存在"依赖 os.stat("")，行为不稳。
#   ":.（当前目录）"必定存在，且语义是"复制进该目录"，因此可反复执行不会
#   产生 library/library 这种嵌套。
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

# ---- 收集 src/ 下的顶层条目（文件 + 目录）----------------------------------
ENTRIES=()
while IFS= read -r -d '' e; do
    base="$(basename "$e")"
    case "$base" in
        .DS_Store|Thumbs.db|*.pyc) continue ;;
    esac
    ENTRIES+=("$e")
done < <(find "$SRC" -mindepth 1 -maxdepth 1 -print0 | sort -z)

[ "${#ENTRIES[@]}" -gt 0 ] || die "src/ 是空的，没有可上传的代码"

echo ">> 仓库   : $REPO"
echo ">> 源目录 : $SRC"
echo ">> 目标   : $PORT  (设备根目录 /)"
echo ">> 待上传 :"
for e in "${ENTRIES[@]}"; do
    echo "     ${e#"$SRC"/}"
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

# ---- 可选：运行 -------------------------------------------------------------
if [ "$RUN" = "1" ]; then
    RUN='import epd_test; epd_test.run_all()'
fi
if [ -n "$RUN" ]; then
    echo
    echo ">> 运行: $RUN"
    "$MP" connect "$PORT" exec "$RUN"
fi

echo ">> 完成"
