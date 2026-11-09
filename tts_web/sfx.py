#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
7 种提示音（纯 Python 合成，无需外部素材）
1 叮咚 / 2 风铃 / 3 嘟嘟 / 4 哒喃 / 5 当~ / 6 咚~ / 7 叮~
生成结果缓存到 assets/sfx_N.mp3
"""
import math
import os
import random
import struct
import subprocess
import wave

import imageio_ffmpeg

RATE = 24000
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
NAMES = {1: "叮咚", 2: "风铃", 3: "嘟嘟", 4: "哒喃", 5: "当~", 6: "咚~", 7: "叮~"}
DESCS = {1: "双音下行，最常用的门铃", 2: "多音错落，清脆悠长",
         3: "短促两声，像电子提示", 4: "木质敲击，短而干脆",
         5: "低频钟声，余音很长", 6: "低沉重击，鼓点感", 7: "高频单音，像三角铁"}


def _env(t, decay, attack):
    a = min(1.0, t / attack) if attack > 0 else 1.0
    return a * math.exp(-decay * t)


def _tone(freq, dur, amp=0.5, decay=6.0, attack=0.004, harm=((1, 1.0),),
          vib=0.0, vib_hz=5.0):
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        f = freq * (1 + vib * math.sin(2 * math.pi * vib_hz * t))
        s = 0.0
        for h, a in harm:
            s += a * math.sin(2 * math.pi * f * h * t)
        out.append(amp * _env(t, decay, attack) * s)
    return out


def _noise(dur, amp, decay):
    n = int(RATE * dur)
    rnd = random.Random(20261103)
    return [amp * rnd.uniform(-1, 1) * math.exp(-decay * i / RATE) for i in range(n)]


def _mix(*parts):
    n = max(len(p) for p in parts)
    buf = [0.0] * n
    for p in parts:
        for i, v in enumerate(p):
            buf[i] += v
    return buf


def _at(buf, seg, start_sec):
    s = int(RATE * start_sec)
    for i, v in enumerate(seg):
        if s + i < len(buf):
            buf[s + i] += v


# ---------------------------------------------------------------- 7 种音效
def sfx_1():   # 叮咚
    return _tone(1318.5, 0.45, .5, 6.0, harm=((1, 1.), (2, .3), (3, .12))) + \
        [0.0] * int(RATE * 0.03) + \
        _tone(1046.5, 0.65, .5, 5.5, harm=((1, 1.), (2, .3), (3, .12)))


def sfx_2():   # 风铃
    freqs = [2093.0, 2349.3, 2637.0, 3136.0, 2793.8]
    buf = [0.0] * int(RATE * 1.6)
    for k, f in enumerate(freqs):
        seg = _tone(f, 1.5 - 0.07 * k, .15, 2.2, attack=.002,
                    harm=((1, 1.), (2.4, .25), (3.8, .12)))
        _at(buf, seg, 0.02 + 0.07 * k)
    return buf


def sfx_3():   # 嘟嘟
    beep = _tone(880, 0.11, .45, 7, attack=.006,
                 harm=((1, 1.), (3, .35), (5, .18)))
    return beep + [0.0] * int(RATE * 0.09) + beep


def sfx_4():   # 哒喃（木质敲击两声）
    def hit(f, dur, amp):
        s = _tone(f, dur, amp, 28, attack=.001,
                  harm=((1, 1.), (2.7, .5), (4.1, .25)))
        nz = _noise(0.012, amp * .45, 70)
        for i, v in enumerate(nz):
            s[i] += v
        return s
    return hit(520, 0.13, .5) + [0.0] * int(RATE * 0.05) + hit(390, 0.16, .45)


def sfx_5():   # 当~（钟）
    return _tone(233.1, 1.7, .42, 1.9, attack=.003,
                 harm=((1, 1.), (2, .45), (3, .28), (4.16, .18), (5.4, .10)),
                 vib=.004, vib_hz=4.5)


def sfx_6():   # 咚~（鼓）
    body = _tone(98, 0.55, .6, 9, attack=.002, harm=((1, 1.), (1.8, .3)))
    nz = _noise(0.03, .22, 45)
    for i, v in enumerate(nz):
        body[i] += v
    return body


def sfx_7():   # 叮~（三角铁）
    return _tone(1567.98, 1.3, .40, 3.0, attack=.002,
                 harm=((1, 1.), (2.76, .3), (5.4, .15)))


FUNCS = {1: sfx_1, 2: sfx_2, 3: sfx_3, 4: sfx_4, 5: sfx_5, 6: sfx_6, 7: sfx_7}


def _ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


def get(index):
    """返回第 index 种提示音的 mp3 路径（1~7，越界回退到 1）"""
    idx = index if index in FUNCS else 1
    os.makedirs(ASSETS, exist_ok=True)
    mp3 = os.path.join(ASSETS, "sfx_%d.mp3" % idx)
    if os.path.exists(mp3) and os.path.getsize(mp3) > 500:
        return mp3

    samples = FUNCS[idx]()
    peak = max(abs(x) for x in samples) or 1.0
    scale = 0.85 / peak
    data = b"".join(struct.pack("<h", max(-32767, min(32767, int(x * scale * 32767))))
                    for x in samples)
    wav = os.path.join(ASSETS, "sfx_%d.wav" % idx)
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", wav,
                    "-ar", str(RATE), "-ac", "1", "-b:a", "64k", mp3], check=True)
    if os.path.exists(wav):
        os.remove(wav)
    return mp3


if __name__ == "__main__":
    for i in range(1, 8):
        p = get(i)
        print(i, NAMES[i], p, "%.1f KB" % (os.path.getsize(p) / 1024))
