#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TTS 合成引擎 — edge-tts 分段合成 + ffmpeg 拼接
======================================================
对外入口：
  render(segments, out_path, progress=None, on_seg=None)
  seg_path(seg) / seg_exists(seg)

每一句都按「文本 + 音色 + 语速 + 音调 + 音量」做内容寻址缓存，
同一句话第二次出现直接命中，既能秒出，也让网页能逐句单独播放。

segments: [
  {"text": "...", "voice": "en-US-AvaNeural",
   "rate": "-20%", "pitch": "+0Hz", "volume": "+0%",
   "after": [["pause", 1.5], ["ding", 1]]}
]
"""
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor

import edge_tts
import imageio_ffmpeg

import sfx

FFMPEG = None
CONCURRENCY = 12    # 并发合成段数（实测 4→17.1s，12→9.1s，16→7.1s；再高易被服务端限流）

import runtime_paths as rp

BASE = rp.SRC_DIR
SEG_CACHE = os.path.join(rp.DATA_DIR, "cache", "seg")


def ffmpeg():
    global FFMPEG
    if FFMPEG is None:
        FFMPEG = rp.ffmpeg_exe()
    return FFMPEG


def duration(path):
    out = subprocess.run([ffmpeg(), "-hide_banner", "-i", path],
                         capture_output=True, text=True, errors="ignore").stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    if not m:
        raise RuntimeError("无法读取音频时长: %s" % path)
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ---------------------------------------------------------------- 单句缓存
def seg_key(seg):
    raw = json.dumps({"t": seg["text"], "v": seg["voice"],
                      "r": seg.get("rate", "+0%"),
                      "p": seg.get("pitch", "+0Hz"),
                      "o": seg.get("volume", "+0%")},
                     ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def seg_path(seg):
    """返回该句的缓存文件路径（不保证已存在）"""
    key = seg_key(seg)
    d = os.path.join(SEG_CACHE, key[:2])
    if not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    return os.path.join(d, key + ".mp3")


def seg_exists(seg):
    p = seg_path(seg)
    return os.path.exists(p) and os.path.getsize(p) > 800


def make_ding(path, sr=24000):
    """合成“叮咚”门铃音"""
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

    samples = tone(1567.98, 0.42, 0.62) + [0.0] * int(sr * 0.04) + tone(1046.50, 0.62, 0.55)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples))


async def _synth(text, voice, rate, pitch, volume, path, retries=3):
    last = None
    for i in range(retries):
        try:
            await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                                       volume=volume).save(path)
            if os.path.getsize(path) > 800:
                return
            last = RuntimeError("输出文件过小")
        except Exception as e:  # noqa: BLE001
            last = e
            await asyncio.sleep(0.8 * (i + 1))
    raise RuntimeError("合成失败(%s): %s" % (voice, last))


def _silence(sec, wd, cache):
    key = round(sec, 2)
    if key <= 0.01:
        return None
    if key not in cache:
        p = os.path.join(wd, "sil_%s.mp3" % key)
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                        "-t", str(key), "-q:a", "9", p], check=True)
        cache[key] = p
    return cache[key]


def render(segments, out_path, progress=None, on_seg=None):
    """合成并拼接，返回 (总时长, 分段时长列表)

    progress(done, total, text) —— 每完成一句回调
    on_seg(i, path)             —— 第 i 句（从 1 开始）可播放时立即回调，
                                   用于「边生成边播放」和逐句试听
    """
    if not segments:
        raise ValueError("没有可合成的内容")

    total = len(segments)
    paths = [None] * total
    wd = tempfile.mkdtemp(prefix="ttsweb_")
    os.makedirs(SEG_CACHE, exist_ok=True)

    async def run():
        sem = asyncio.Semaphore(CONCURRENCY)
        done = [0]

        async def one(i, seg):
            p = seg_path(seg)
            if not seg_exists(seg):
                async with sem:
                    if not seg_exists(seg):
                        tmp = "%s.%s.part" % (p, uuid.uuid4().hex[:8])
                        try:
                            await _synth(seg["text"], seg["voice"], seg.get("rate", "+0%"),
                                         seg.get("pitch", "+0Hz"), seg.get("volume", "+0%"), tmp)
                            os.replace(tmp, p)
                        finally:
                            if os.path.exists(tmp):
                                try:
                                    os.remove(tmp)
                                except OSError:
                                    pass
            paths[i - 1] = p
            done[0] += 1
            if progress:
                progress(done[0], total, seg["text"][:60])
            if on_seg:
                on_seg(i, p)

        await asyncio.gather(*[one(i, s) for i, s in enumerate(segments, 1)])

    try:
        asyncio.run(run())

        # 按原顺序拼接（并发完成后统一处理，保证顺序正确）
        seq, sil_cache = [], {}
        for seg, p in zip(segments, paths):
            seq.append(p)
            for kind, val in seg.get("after", []):
                if kind == "pause":
                    s = _silence(val, wd, sil_cache)
                    if s:
                        seq.append(s)
                elif kind == "ding":
                    # val 表示第几种提示音（1~7），只播放一次
                    seq.append(_silence(0.12, wd, sil_cache))
                    seq.append(sfx.get(int(val) or 1))
                    seq.append(_silence(0.22, wd, sil_cache))

        listfile = os.path.join(wd, "concat.txt")
        with open(listfile, "w", encoding="utf-8") as f:
            for p in seq:
                if p:
                    f.write("file '%s'\n" % p.replace("\\", "/"))

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", listfile,
                        "-ar", "24000", "-ac", "1", "-b:a", "64k", out_path], check=True)

        with ThreadPoolExecutor(max_workers=16) as ex:
            durs = list(ex.map(duration, paths))
        return duration(out_path), durs
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- 文本解析
# 同时支持 [pause:2] 与 (⏱️=3s) 两种写法
_PAUSE_WORDS = r"pause|停顿|停|timer|计时|时钟|⏱️?|⏲️?"
_DING_WORDS = r"ding|bell|铃声|提示音|🔔|🔕"
_OPEN = r"(?:\[|\(|（)"
_CLOSE = r"(?:\]|\)|）)"

PAUSE_RE = re.compile(
    r"^%s\s*(?:%s)\s*[:：=]?\s*([\d.]+)\s*(?:s|秒)?\s*%s$" % (_OPEN, _PAUSE_WORDS, _CLOSE), re.I)
DING_RE = re.compile(
    r"^%s\s*(?:%s)\s*(?:[:：=]\s*(\d+))?\s*%s$" % (_OPEN, _DING_WORDS, _CLOSE), re.I)

TOKEN_RE = re.compile(
    r"(%s\s*(?:%s)\s*[:：=]?\s*[\d.]+\s*(?:s|秒)?\s*%s"
    r"|%s\s*(?:%s)\s*(?:[:：=]\s*\d+)?\s*%s)" % (_OPEN, _PAUSE_WORDS, _CLOSE,
                                                _OPEN, _DING_WORDS, _CLOSE), re.I)

ROLE_RE = re.compile(r"^\s*([A-Za-z]{1,12}|[男女甲乙])\s*[:：]\s*")


def split_marks(text):
    """解析停顿/铃声标记，返回 [(纯文本, [actions])]"""
    parts, buf = [], []
    for tok in TOKEN_RE.split(text):
        if not tok:
            continue
        if TOKEN_RE.fullmatch(tok):
            acts = []
            m = PAUSE_RE.match(tok)
            if m:
                acts.append(["pause", float(m.group(1))])
            else:
                m = DING_RE.match(tok)
                acts.append(["ding", int(m.group(1)) if m and m.group(1) else 1])
            parts.append(["".join(buf).strip(), acts])
            buf = []
        else:
            buf.append(tok)
    tail = "".join(buf).strip()
    if tail:
        parts.append([tail, []])
    # 纯动作块挂到上一段落
    out = []
    for text, acts in parts:
        if text:
            out.append([text, acts])
        elif out and acts:
            out[-1][1].extend(acts)
    return out


def _cjk(ch):
    """汉字 / 中文标点 / 全角符号 —— 后面不需要补空格"""
    if not ch:
        return False
    o = ord(ch)
    return (0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF
            or 0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFFEF)


def split_sentences(text, max_len=180):
    """长文本切句，避免单次请求过长"""
    sents = re.split(r"(?<=[.!?。！？；;])\s*", text.replace("\n", " "))
    out, buf = [], ""
    for s in sents:
        if not s.strip():
            continue
        if not buf:
            buf = s
        elif len(buf) + len(s) + 1 <= max_len:
            # 英文句间要补回被 re.split 吃掉的空格，中文不需要
            buf += ("" if _cjk(buf[-1]) else " ") + s
        else:
            out.append(buf.strip())
            buf = s
    if buf.strip():
        out.append(buf.strip())
    return out or [text]
