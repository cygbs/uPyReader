# 生成的位图字库（不入库）

本目录存放 `tools/build_font.py` 生成的 UFB1 字库。生成的 `*.bin` 已被
`.gitignore` 忽略，克隆仓库后需要自己生成一次：

```bash
python3 tools/build_font.py -o assets/fonts/unifont16.bin --preview /tmp/preview.bmp
```

生成后 `tools/upload.sh` 会自动把它同步到设备的 `/fonts/` 目录。

字库来源：GNU Unifont（SIL OFL 1.1 / GPL-2.0+ 带字体嵌入例外），
详见仓库根目录的 `NOTICE` 与 `LICENSES/OFL-1.1.txt`。
