# -*- coding: utf-8 -*-
"""driver — 硬件层: 引脚配置与设备驱动。

    hwconfig.py       引脚/尺寸/字库路径等硬件配置
    epd_ssd1619.py    SSD1619 墨水屏驱动(初始化/全刷/局刷/睡眠)
    epdlut.py         从面板 OTP 读波形并裁成不闪的局刷 LUT
    rotary.py         增量式旋转编码器(含按键)驱动
    sysinfo.py        芯片/Flash/PSRAM/MAC 等系统信息
    sdspi.py          纯 Python SPI 模式 SD/TF 卡驱动(micropython-lib)
    sdcard.py         把 TF 卡(FAT32/MBR) 挂到 /sd + 诊断
"""
