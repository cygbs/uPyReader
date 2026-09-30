#!/usr/bin/env bash
#
# upload.sh — 把仓库内容同步到开发板根目录（按 sha256 跳过未改动文件）
#
# 用法:
#   ./upload.sh
#
# 没有参数、没有开关。端口固定 /dev/ttyACM0。
#
# 目录约定（各根目录下的顶层条目原样映射到设备根 /）:
#   src/     -> /     代码     (main.py, driver/, ui/ ...)
#   assets/  -> /     资源     (fonts/unifont16.bin ...)
#   state/   -> /     设备状态 (settings.json, wifi.json, books/.state/progress.json)
#
#   例: src/main.py                 -> 设备 /main.py
#       src/driver/ds3231.py        -> 设备 /driver/ds3231.py
#       assets/fonts/unifont16.bin  -> 设备 /fonts/unifont16.bin
#       state/books/.state/*.json   -> 设备 /books/.state/*.json
#
# 为什么不做“强制重传”开关:
#   mpremote 上传是逐块写 littlefs。一旦在传大文件（例如 726KB 的字库）中途被打断
#   （Ctrl-C、拔线、超时），设备上就会留下一个写了一半的文件，甚至把 littlefs 写坏。
#   不传 -f 时 mpremote 会按 sha256 跳过内容相同的文件，所以字库这种大文件平时
#   根本不会被重写，从根上规避了反复写入造成的碎片化与损坏。
#
# 依赖: mpremote  (uv tool install mpremote)
#
set -euo pipefail

PORT="/dev/ttyACM0"
MP="mpremote"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=":."          # 远端当前目录（设备根）。用 ":.",不要用 ":"（原因见下）

# ----------------------------------------------------------------------------
# 为什么目标是 ":." 而不是 ":"：
#   mpremote 的 `cp -r` 目标若不存在，会把源目录的内容直接铺到目标；而 ":" 是否
#   被判定为“已存在”依赖 os.stat("")，行为不稳。"。." 必定存在，语义是“复制进
#   该目录”，反复执行也不会产生 driver/driver 这种嵌套。
# ----------------------------------------------------------------------------

die() { echo "错误: $*" >&2; exit 1; }

# ---- 前置检查 ---------------------------------------------------------------
command -v "$MP" >/dev/null 2>&1 || die "找不到 mpremote。安装: uv tool install mpremote"
[ -e "$PORT" ] || die "串口不存在: $PORT（板子插好了吗？ls /dev/ttyACM* /dev/ttyUSB*）"

# ---- 串口权限：每次插拔后都会变回 root:dialout，必须重新放开 -----------------
echo ">> 串口权限: sudo chmod 777 $PORT"
sudo chmod 777 "$PORT" || die "chmod 失败"

# ---- 清理本地 Python 缓存,避免把 __pycache__ 传上去 -------------------------
find "$REPO/src" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$REPO/src" -type f -name '*.pyc' -delete 2>/dev/null || true

# ---- 收集要同步的条目 -------------------------------------------------------
ROOTS=()
for d in src assets state; do
    [ -d "$REPO/$d" ] && ROOTS+=("$REPO/$d")
done
[ "${#ROOTS[@]}" -gt 0 ] || die "src/ assets/ state/ 都不存在，没有可同步的内容"

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
[ "${#ENTRIES[@]}" -gt 0 ] || die "没有可同步的内容"

echo ">> 仓库   : $REPO"
echo ">> 目标   : $PORT  (设备根目录 /)"
echo ">> 内容   :"
for e in "${ENTRIES[@]}"; do
    echo "     ${e#"$REPO"/}"
done

# ---- 同步（单次连接；mpremote 按 sha256 跳过内容相同的文件）------------------
echo ">> 同步中（未改动的文件会自动跳过） ..."
"$MP" connect "$PORT" cp -r "${ENTRIES[@]}" "$DEST"

# ---- 核对设备上的文件树 -----------------------------------------------------
echo
echo ">> 设备文件树 (/):"
"$MP" connect "$PORT" fs tree : || true

echo ">> 完成"
