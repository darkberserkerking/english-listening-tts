# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件 Windows exe。

用法（在仓库根目录）：
    .buildenv/Scripts/python.exe -m PyInstaller --noconfirm --clean tts.spec
"""
import os

import imageio_ffmpeg
from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(SPECPATH)
WEB = os.path.join(ROOT, "tts_web")

datas = [
    (os.path.join(WEB, "templates"), "templates"),
    (os.path.join(WEB, "assets"), "assets"),
    (os.path.join(WEB, "voices_cache.json"), "."),
    (imageio_ffmpeg.get_ffmpeg_exe(), "ffmpeg.exe"),
]

# edge-tts 走 wss，Windows 下需要 certifi 的根证书
try:
    datas += collect_data_files("certifi")
except Exception:
    pass

hiddenimports = [
    "engine", "sfx", "runtime_paths",
    "edge_tts", "aiohttp", "flask", "jinja2", "werkzeug",
    "imageio_ffmpeg", "certifi", "ssl", "asyncio",
]

a = Analysis(
    [os.path.join(WEB, "app.py")],
    pathex=[WEB],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(WEB, "pyi_rth_ssl.py")],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="EnglishListeningTTS",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
