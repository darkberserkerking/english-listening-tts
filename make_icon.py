#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成应用图标（唯一真源）。

设计：品牌蓝圆角方 + 白色耳机轮廓 + 中间三根声波柱。
耳机表示「听力」，声波表示「文字转语音」。
16/20/24px 会糊，这三档改用简化帧（去掉声波柱、加粗耳机），
是 Windows 图标的常规尺寸适配做法。

产出：
    assets/icon.svg   矢量源
    assets/icon.png   512x512（README / 网页用）
    assets/icon.ico   Windows 多尺寸图标（exe 用）
并把 templates/index.html 的 favicon 同步成同一图形。

用法： .buildenv/Scripts/python.exe make_icon.py
"""
import io
import os
import re
import struct
from urllib.parse import quote

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
HTML = os.path.join(ROOT, "tts_web", "templates", "index.html")

BLUE = "#3d5afe"
WHITE = "#ffffff"
S = 1024

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
<rect width="1024" height="1024" rx="230" fill="{blue}"/>
<path d="M250 512 A262 262 0 0 1 774 512" fill="none" stroke="{white}" stroke-width="80" stroke-linecap="round"/>
<rect x="200" y="480" width="112" height="250" rx="56" fill="{white}"/>
<rect x="712" y="480" width="112" height="250" rx="56" fill="{white}"/>
<rect x="407" y="462" width="46" height="100" rx="23" fill="{white}"/>
<rect x="489" y="412" width="46" height="200" rx="23" fill="{white}"/>
<rect x="571" y="462" width="46" height="100" rx="23" fill="{white}"/>
</svg>
""".format(blue=BLUE, white=WHITE)

# Pillow 的 arc 角度从 3 点方向顺时针计；180~360 即上半圆
HEADBAND = [250, 250, 774, 774]
CUPS = [(200, 480, 312, 730), (712, 480, 824, 730)]
CUPS_COMPACT = [(188, 468, 324, 742), (700, 468, 836, 742)]
BARS = [(407, 462, 453, 562), (489, 412, 535, 612), (571, 462, 617, 562)]
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def draw(compact=False):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=230, fill=BLUE)
    d.arc(HEADBAND, start=180, end=360, fill=WHITE,
          width=104 if compact else 80)
    if not compact:
        for box in BARS:
            d.rounded_rectangle(box, radius=23, fill=WHITE)
    for box in (CUPS_COMPACT if compact else CUPS):
        d.rounded_rectangle(box, radius=56, fill=WHITE)
    return img


def write_ico(path, frames):
    """手写 ICO 容器，逐尺寸放独立 PNG 帧（Vista+ 支持）。"""
    blobs = []
    for n, im in frames:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        blobs.append(buf.getvalue())
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    for (n, _), data in zip(frames, blobs):
        dim = 0 if n >= 256 else n
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                               len(data), offset)
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + b"".join(blobs))


def sync_favicon():
    enc = quote(SVG.replace('"', "'").strip(), safe="'()=:/-")
    line = '<link rel="icon" href="data:image/svg+xml,%s">' % enc
    with open(HTML, encoding="utf-8") as f:
        html = f.read()
    pat = re.compile(r'<link rel="icon" href="[^"]*">')
    out, n = pat.subn(lambda _: line, html, count=1)
    assert n == 1, "favicon 标签没找到或被改坏"
    with open(HTML, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    return len(out) - len(html)


def main():
    os.makedirs(ASSETS, exist_ok=True)

    with open(os.path.join(ASSETS, "icon.svg"), "w", encoding="utf-8") as f:
        f.write(SVG)

    full = draw()
    compact = draw(compact=True)
    full.resize((512, 512), Image.LANCZOS).save(
        os.path.join(ASSETS, "icon.png"), "PNG")

    frames = [(n, (compact if n <= 24 else full).resize((n, n), Image.LANCZOS))
              for n in ICO_SIZES]
    ico_path = os.path.join(ASSETS, "icon.ico")
    write_ico(ico_path, frames)

    diff = sync_favicon()
    with Image.open(ico_path) as ico:
        got = sorted(ico.ico.sizes())
    print("icon.svg    %d 字节" % os.path.getsize(os.path.join(ASSETS, "icon.svg")))
    print("icon.png    512x512, %d 字节" % os.path.getsize(os.path.join(ASSETS, "icon.png")))
    print("icon.ico    %d 字节, 尺寸 %s" % (os.path.getsize(ico_path), [n for n, _ in got]))
    print("小尺寸简化帧: 16 / 20 / 24 px")
    print("favicon     已同步（HTML 变化 %+d 字节）" % diff)
    assert (16, 16) in got and (256, 256) in got
    assert full.getpixel((0, 0))[3] == 0
    assert full.getpixel((512, 512))[3] == 255
    print("透明圆角校验通过")


if __name__ == "__main__":
    main()
