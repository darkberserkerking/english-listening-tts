#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
英语听力音频生成器 (edge-tts + ffmpeg)
------------------------------------------------
文本标记规则（行首，大小写不敏感）：
    [C] 或 C:   中文女声 (zh-CN-XiaoxiaoNeural)
    [W] 或 W:   美音女声 (en-US-AvaNeural)
    [M] 或 M:   美音男声 (en-US-AndrewNeural)
    无标记      沿用上一个角色（首行默认 W）

空行 = 段落停顿（para_gap 秒），普通换行 = 句间停顿（gap 秒）

用法:
    python tts_make.py input.txt -o listening.mp3
    python tts_make.py input.txt -o listening.mp3 --gap 1.2 --para-gap 2.0 --rate +0%
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile

import edge_tts
import imageio_ffmpeg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

VOICES = {
    "C": ("zh-CN-XiaoxiaoNeural", "中文女声"),
    "W": ("en-US-AvaNeural", "美音女声"),
    "M": ("en-US-AndrewNeural", "美音男声"),
}

TAG_RE = re.compile(r"^\s*(?:\[([CWM])\]|([CWM])\s*[:：])\s*", re.I)


def parse_script(path):
    """把脚本解析成 [(role, text, gap_after_sec)]"""
    with open(path, encoding="utf-8-sig") as f:
        raw = f.read().replace("\r\n", "\n").replace("\r", "\n")

    blocks, cur = [], []
    for line in raw.split("\n"):
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append(cur)

    items, role = [], "W"
    for bi, block in enumerate(blocks):
        for line in block:
            m = TAG_RE.match(line)
            if m:
                role = (m.group(1) or m.group(2)).upper()
                line = line[m.end():]
            text = line.strip()
            if text:
                items.append({"role": role, "text": text})
        # 段落末尾加长停顿
        if items and bi != len(blocks) - 1:
            items[-1]["para"] = True
    return items


def mp3_duration(path, ffmpeg):
    out = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path],
        capture_output=True, text=True, errors="ignore",
    ).stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    if not m:
        raise RuntimeError(f"无法读取时长: {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


async def synth_one(text, voice, rate, path, retries=2):
    last = None
    for _ in range(retries):
        try:
            kw = {"rate": rate}
            c = edge_tts.Communicate(text, voice, **kw)
            await c.save(path)
            if os.path.getsize(path) > 1000:
                return
            last = RuntimeError("输出过小")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"合成失败[{voice}]: {last} :: {text[:40]}")


async def build(args):
    items = parse_script(args.input)
    if not items:
        sys.exit("脚本为空，检查 input.txt")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    workdir = tempfile.mkdtemp(prefix="tts_")
    seg_files, timestamps, cursor = [], [], 0.0

    print(f"共 {len(items)} 句，开始合成…")
    for i, it in enumerate(items, 1):
        voice, vname = VOICES[it["role"]]
        seg = os.path.join(workdir, f"seg_{i:03d}.mp3")
        await synth_one(it["text"], voice, args.rate, seg)
        dur = mp3_duration(seg, ffmpeg)
        seg_files.append(seg)
        timestamps.append({
            "index": i,
            "role": it["role"],
            "voice": voice,
            "text": it["text"],
            "start_sec": round(cursor, 2),
            "end_sec": round(cursor + dur, 2),
        })
        cursor += dur + (args.para_gap if it.get("para") else args.gap)
        print(f"  [{i:03d}] {vname} {dur:5.2f}s  {it['text'][:50]}")

    # 生成拼接清单（句间/段间插入静音）
    silence_cache = {}

    def silence(sec):
        key = round(sec, 2)
        if key not in silence_cache:
            p = os.path.join(workdir, f"sil_{key}.mp3")
            subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
                 "-t", str(key), "-q:a", "9", p],
                check=True,
            )
            silence_cache[key] = p
        return silence_cache[key]

    listfile = os.path.join(workdir, "concat.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for i, (seg, it) in enumerate(zip(seg_files, items)):
            f.write(f"file '{seg.replace(chr(92), '/')}'\n")
            if i != len(seg_files) - 1:
                gap = args.para_gap if it.get("para") else args.gap
                if gap > 0:
                    f.write(f"file '{silence(gap).replace(chr(92), '/')}'\n")

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", listfile,
         "-ar", "24000", "-ac", "1", "-b:a", "64k", out],
        check=True,
    )

    total = mp3_duration(out, ffmpeg)
    meta = {
        "audio": {"path": out, "duration_sec": round(total, 2),
                  "sample_rate": 24000, "channel": "edge-tts"},
        "timestamps": timestamps,
    }
    with open(os.path.splitext(out)[0] + ".timestamps.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成: {out}")
    print(f"   时长 {total:.2f}s，大小 {os.path.getsize(out)/1024:.0f} KB")
    print(f"   时间戳: {os.path.splitext(out)[0]}.timestamps.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="脚本文本文件 (UTF-8)")
    ap.add_argument("-o", "--out", default="listening.mp3")
    ap.add_argument("--gap", type=float, default=0.8, help="句间停顿秒")
    ap.add_argument("--para-gap", type=float, default=1.8, help="段间停顿秒")
    ap.add_argument("--rate", default="+0%", help="语速，如 +10%% / -10%%")
    args = ap.parse_args()
    asyncio.run(build(args))


if __name__ == "__main__":
    main()
