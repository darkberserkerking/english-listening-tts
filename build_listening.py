#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
英语听力卷 → 单条 mp3
------------------------------------------------------------
标记语法（来自听力稿）：
    C: / W: / M: / Q:    角色（C 中文女声, W 美音女声, M 美音男声, Q 问题用女声）
    (⏱️=3s)              静音 3 秒
    (🔔=1)               叮咚铃声 1 次
规则：
    - 行首题号 1. → "Number one."；question1: → "Question one."
    - 同一行出现多个角色（如 "... What about you? W: ..."）自动拆段
    - 题组若为 A+A 重复（两遍播放），两遍之间自动空 repeat_gap 秒
"""
import argparse
import asyncio
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import wave

import edge_tts
import imageio_ffmpeg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

VOICES = {
    "C": ("zh-CN-XiaoxiaoNeural", "中文女声"),
    "W": ("en-US-AvaNeural", "美音女声"),
    "M": ("en-US-AndrewNeural", "美音男声"),
    "Q": ("en-US-AvaNeural", "问题女声"),
}

NUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
       7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
       12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen"}

ROLE_SPLIT = re.compile(r"(?:^|\s)([CWMQ])\s*[:：]")
MARK_RE = re.compile(r"[（(]?\s*(?:⏱️\s*=\s*([\d.]+)\s*s|🔔\s*=\s*(\d+))\s*[)）]?")


def num2en(n):
    try:
        return NUM[int(n)]
    except Exception:  # noqa: BLE001
        return str(n)


def norm(s):
    return re.sub(r"[^\w\s]", "", s).lower().strip()


def clean_en(t):
    t = re.sub(r"^question\s*(\d+)\s*[:：.]\s*",
               lambda m: f"Question {num2en(m.group(1))}. ", t, flags=re.I)
    t = re.sub(r"^(\d{1,2})\s*[.、]\s*",
               lambda m: f"Number {num2en(m.group(1))}. ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_script(path):
    with open(path, encoding="utf-8-sig") as f:
        raw = f.read().replace("\r\n", "\n").replace("\r", "\n")

    blocks, cur_role = [], "C"
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 跳过末尾说明行
        if ("代表停顿" in line or "代表提示音" in line) and len(line) < 80:
            continue

        acts = []
        for m in MARK_RE.finditer(line):
            if m.group(1):
                acts.append(["pause", float(m.group(1))])
            elif m.group(2):
                acts.append(["ding", int(m.group(2))])
        line = MARK_RE.sub(" ", line).strip()

        if not line:                        # 纯标记行 → 挂到上一块
            if blocks and acts:
                blocks[-1]["after"].extend(acts)
            continue

        tokens = ROLE_SPLIT.split(line)
        segs = []
        if tokens[0].strip():
            segs.append((cur_role, tokens[0].strip()))
        for i in range(1, len(tokens), 2):
            r = tokens[i]
            t = tokens[i + 1].strip() if i + 1 < len(tokens) else ""
            if t:
                segs.append((r, t))
        if not segs:
            continue

        for r, t in segs:
            cur_role = r
            text = t if r == "C" else clean_en(t)
            if text:
                blocks.append({"role": r, "text": text, "after": [], "gap_before": None})
        if acts:
            blocks[-1]["after"].extend(acts)
    return blocks


def split_single_dup(text):
    """单块内部 A+A 重复检测（题号前缀只留在第一遍）"""
    m = re.match(r"^(Number\s+[A-Za-z]+\.)\s*(.*)$", text)
    prefix, body = (m.group(1), m.group(2)) if m else ("", text)
    sents = re.split(r"(?<=[.!?])\s+", body.strip())
    n = len(sents)
    if n >= 2 and n % 2 == 0:
        h = n // 2
        if [norm(x) for x in sents[:h]] == [norm(x) for x in sents[h:]]:
            first = " ".join(sents[:h])
            return (f"{prefix} {first}" if prefix else first), " ".join(sents[h:])
    return None


def apply_repeats(blocks, repeat_gap):
    """1) 块内 A+A 拆分  2) 相邻段重复（对话题）自动加两遍之间的停顿"""
    out = []
    for b in blocks:
        if b["role"] != "C":
            sp = split_single_dup(b["text"])
            if sp:
                a, c = sp
                out.append({**b, "text": a, "after": []})
                out.append({"role": b["role"], "text": c,
                            "after": b["after"], "gap_before": repeat_gap})
                continue
        out.append(b)
    blocks = out

    def has_pause(x):
        return any(k == "pause" for k, _ in x["after"])

    i, hits = 0, 0
    while i < len(blocks):
        best = 0
        limit = min(12, (len(blocks) - i) // 2)
        for L in range(2, limit + 1):
            a = [norm(x["text"]) for x in blocks[i:i + L]]
            b = [norm(x["text"]) for x in blocks[i + L:i + 2 * L]]
            # 重复体内部不允许跨停顿边界
            if a == b and not any(has_pause(x) for x in blocks[i:i + 2 * L - 1]):
                best = L
        if best:
            blocks[i + best]["gap_before"] = repeat_gap
            hits += 1
            print(f"  ↺ 两遍重复（{best} 句）：{blocks[i]['text'][:38]}…")
            i += 2 * best
        else:
            i += 1
    return blocks


def make_ding(path, sr=24000):
    """合成 '叮咚' 门铃音"""
    def tone(freq, dur, amp):
        n = int(sr * dur)
        buf = []
        for i in range(n):
            t = i / sr
            env = math.exp(-6.0 * t)
            atk = min(1.0, t / 0.005)
            s = (math.sin(2 * math.pi * freq * t)
                 + 0.35 * math.sin(4 * math.pi * freq * t)
                 + 0.12 * math.sin(6 * math.pi * freq * t)) / 1.4
            buf.append(amp * env * atk * s)
        return buf

    samples = tone(1567.98, 0.42, 0.62) + [0.0] * int(sr * 0.04) \
        + tone(1046.50, 0.62, 0.55)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples))


def dur_of(path, ffmpeg):
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                         capture_output=True, text=True, errors="ignore").stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    if not m:
        raise RuntimeError(f"读不到时长: {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


async def synth(text, voice, rate, path, retries=3):
    last = None
    for attempt in range(retries):
        try:
            await edge_tts.Communicate(text, voice, rate=rate).save(path)
            if os.path.getsize(path) > 1200:
                return
            last = RuntimeError("输出过小")
        except Exception as e:  # noqa: BLE001
            last = e
            await asyncio.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"合成失败 [{voice}] {last} :: {text[:50]}")


PART_RE = re.compile(r"第([一二三四五六])部分")
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}


async def build(args):
    blocks = apply_repeats(parse_script(args.input), args.repeat_gap)

    part = 0
    for b in blocks:
        if b["role"] == "C":
            m = PART_RE.search(b["text"])
            if m:
                part = CN_NUM.get(m.group(1), part)
        b["part"] = part

    prev = None
    for b in blocks:
        if b["gap_before"] is None:
            g = args.line_gap
            if prev is None:
                g = 0.0
            elif (b["role"] == "Q" and prev["role"] == "Q"
                  and args.q_gap_part and b["part"] == args.q_gap_part):
                g = args.q_gap
            elif b["role"] == "Q":
                g = max(g, 0.9)
            elif prev["role"] == "C":
                g = max(g, 1.3)
            b["gap_before"] = g
        prev = b

    print(f"\n共 {len(blocks)} 个语音块，开始合成…\n")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    wd = tempfile.mkdtemp(prefix="listen_")

    ding_wav = os.path.join(wd, "ding.wav")
    make_ding(ding_wav)
    ding_mp3 = os.path.join(wd, "ding.mp3")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", ding_wav,
                    "-ar", "24000", "-ac", "1", "-b:a", "64k", ding_mp3], check=True)

    sil_cache = {}

    def silence(sec):
        key = round(sec, 2)
        if key <= 0:
            return None
        if key not in sil_cache:
            p = os.path.join(wd, f"sil_{key}.mp3")
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                            "-t", str(key), "-q:a", "9", p], check=True)
            sil_cache[key] = p
        return sil_cache[key]

    seq, stamps, cursor, warns = [], [], 0.0, 0
    for i, b in enumerate(blocks, 1):
        voice, vname = VOICES[b["role"]]
        rate = args.rate_zh if b["role"] == "C" else args.rate_en
        seg = os.path.join(wd, f"seg_{i:04d}.mp3")
        for attempt in range(3):
            try:
                await synth(b["text"], voice, rate, seg)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    warns += 1
                    print(f"  ⚠️ 跳过：{e}")
                    seg = None
        if i > 1:
            s = silence(b["gap_before"])
            if s:
                seq.append(s)
                cursor += b["gap_before"]
        if seg and os.path.exists(seg):
            d = dur_of(seg, ffmpeg)
            seq.append(seg)
            stamps.append({"index": i, "role": b["role"], "voice": voice,
                           "text": b["text"], "start_sec": round(cursor, 2),
                           "end_sec": round(cursor + d, 2)})
            cursor += d
            mark = "  " if b["role"] != "C" else "◆ "
            print(f" {mark}[{i:03d}] {vname} {d:5.2f}s  {b['text'][:56]}")

        for kind, val in b["after"]:
            if kind == "pause":
                seq.append(silence(val))
                cursor += val
            else:
                for _ in range(val):
                    seq.append(silence(0.12))
                    seq.append(ding_mp3)
                    seq.append(silence(0.28))
                    cursor += 0.12 + dur_of(ding_mp3, ffmpeg) + 0.28

    listfile = os.path.join(wd, "concat.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for p in seq:
            if p:
                f.write("file '%s'\n" % p.replace("\\", "/"))

    out = os.path.abspath(args.out)
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", listfile,
                    "-ar", "24000", "-ac", "1", "-b:a", "64k", out], check=True)

    total = dur_of(out, ffmpeg)
    meta = {"audio": {"path": out, "duration_sec": round(total, 2),
                      "sample_rate": 24000, "channel": "edge-tts (Xiaoxiao/Ava/Andrew)"},
            "timestamps": stamps}
    with open(os.path.splitext(out)[0] + ".timestamps.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    mm, ss = divmod(total, 60)
    print(f"\n✅ 完成: {out}")
    print(f"   总时长 {int(mm)}分{ss:04.1f}秒 | {os.path.getsize(out)/1024/1024:.2f} MB")
    print(f"   语音块 {len(stamps)} 个 | 失败 {warns} 个")
    print(f"   时间戳 {os.path.splitext(out)[0]}.timestamps.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--out", default="listening.mp3")
    ap.add_argument("--line-gap", type=float, default=0.40, help="句/行间停顿时长")
    ap.add_argument("--repeat-gap", type=float, default=1.70, help="两遍朗诵之间的停顿")
    ap.add_argument("--rate-en", default="-20%", help="英文语速（-20%% ≈ ×0.8）")
    ap.add_argument("--rate-zh", default="+0%", help="中文旁白语速")
    ap.add_argument("--q-gap", type=float, default=0.0, help="指定部分内相邻 Q 之间的作答停顿")
    ap.add_argument("--q-gap-part", type=int, default=0, help="在哪个部分应用 q-gap（0=关闭）")
    asyncio.run(build(ap.parse_args()))


if __name__ == "__main__":
    main()
