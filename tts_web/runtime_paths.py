#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""区分「只读资源目录」与「可写数据目录」。

开发运行：两者都是源码目录。
PyInstaller 打包：资源在 _MEIPASS（临时解压目录，每次启动重建），
缓存、输出、历史必须落在 exe 同目录，否则重启后全部丢失。
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", SRC_DIR) or SRC_DIR
DATA_DIR = (os.path.dirname(os.path.abspath(sys.executable))
            if FROZEN else SRC_DIR)


def ffmpeg_exe():
    """优先用随包附带的 ffmpeg.exe，否则回退到 imageio_ffmpeg 内置版本。"""
    p = os.path.join(RES_DIR, "ffmpeg.exe")
    if os.path.isfile(p):
        return p
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()
