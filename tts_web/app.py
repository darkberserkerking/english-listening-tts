#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
文字转语音 Web 工具 — Flask 后端
启动: python app.py  （默认 http://127.0.0.1:5000）
"""
import hashlib
import io
import json
import os
import shutil
import socket
import sys
import threading
import time
import uuid
import webbrowser

from flask import Flask, jsonify, request, send_file, send_from_directory

import engine
import sfx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "output")
CACHE_DIR = os.path.join(BASE, "cache")
HIST_FILE = os.path.join(BASE, "history.json")
VOICE_CACHE = os.path.join(BASE, "voices_cache.json")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)


def cache_key(segs):
    """内容 + 所有合成参数完全一致才算命中"""
    raw = json.dumps(segs, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def trim_cache(limit=400):
    try:
        items = []
        for f in os.listdir(CACHE_DIR):
            p = os.path.join(CACHE_DIR, f)
            if os.path.isfile(p):
                items.append((os.path.getmtime(p), p))
        items.sort()
        for _, p in items[:-limit]:
            os.remove(p)
    except Exception:  # noqa: BLE001
        pass


def trim_seg_cache(limit=6000):
    """单句缓存按最久未用淘汰"""
    try:
        items = []
        for d in os.listdir(engine.SEG_CACHE):
            dp = os.path.join(engine.SEG_CACHE, d)
            if not os.path.isdir(dp):
                continue
            for f in os.listdir(dp):
                p = os.path.join(dp, f)
                items.append((os.path.getmtime(p), p))
        items.sort()
        for _, p in items[:-limit]:
            os.remove(p)
    except Exception:  # noqa: BLE001
        pass

app = Flask(__name__, static_folder=None)
JOBS = {}
HIST_LOCK = threading.Lock()

LANG_NAMES = {
    "zh-CN": "中文（普通话）", "zh-HK": "中文（粤语）", "zh-TW": "中文（台湾）",
    "en-US": "英语（美式）", "en-GB": "英语（英式）", "en-AU": "英语（澳洲）",
    "en-CA": "英语（加拿大）", "en-IN": "英语（印度）", "en-IE": "英语（爱尔兰）",
    "en-NZ": "英语（新西兰）", "en-ZA": "英语（南非）", "en-SG": "英语（新加坡）",
    "ja-JP": "日语", "ko-KR": "韩语", "fr-FR": "法语", "de-DE": "德语",
    "es-ES": "西班牙语", "es-MX": "西班牙语（墨西哥）", "ru-RU": "俄语",
    "pt-BR": "葡萄牙语（巴西）", "pt-PT": "葡萄牙语", "it-IT": "意大利语",
    "ar-SA": "阿拉伯语", "hi-IN": "印地语", "th-TH": "泰语", "vi-VN": "越南语",
    "id-ID": "印尼语", "ms-MY": "马来语", "tr-TR": "土耳其语", "nl-NL": "荷兰语",
}


# 只保留：普通话 / 英式 / 美式（英式排在前面，选音色时更顺手）
ALLOWED_LOCALES = ("zh-CN", "en-GB", "en-US")

VOICE_NOTES = {
    # 普通话
    "zh-CN-XiaoxiaoNeural": "亲切温和，标准播音腔，听力旁白首选",
    "zh-CN-XiaoyiNeural": "活泼俏皮，语气轻快，适合口语对话",
    "zh-CN-YunxiNeural": "温和阳光，年轻男声，对话自然",
    "zh-CN-YunjianNeural": "浑厚有力，适合解说与宣传",
    "zh-CN-YunxiaNeural": "少年音偏童声，适合儿童内容",
    "zh-CN-YunyangNeural": "沉稳专业，新闻播报风格",
    # 美式
    "en-US-AvaNeural": "清晰自然，中性美音，听力标准音",
    "en-US-EmmaNeural": "明亮亲切，节奏轻快",
    "en-US-AriaNeural": "专业播音，节奏感强，略正式",
    "en-US-JennyNeural": "柔和友好，日常对话感",
    "en-US-MichelleNeural": "温暖知性，娓娓道来",
    "en-US-AnaNeural": "童声，适合少儿材料",
    "en-US-AvaMultilingualNeural": "多语种通用，中性美音",
    "en-US-EmmaMultilingualNeural": "多语种通用，明亮清透",
    "en-US-AndrewNeural": "沉稳自然，中性美音男声",
    "en-US-BrianNeural": "浑厚低沉，讲故事感强",
    "en-US-ChristopherNeural": "成熟稳重，播报风格",
    "en-US-EricNeural": "清亮年轻，偏轻快",
    "en-US-GuyNeural": "标准新闻男声，字正腔圆",
    "en-US-RogerNeural": "低沉厚重，有磁性",
    "en-US-SteffanNeural": "温和叙述，平实自然",
    "en-US-AndrewMultilingualNeural": "多语种通用，沉稳",
    "en-US-BrianMultilingualNeural": "多语种通用，浑厚",
    # 英式
    "en-GB-SoniaNeural": "标准英音，优雅清晰",
    "en-GB-LibbyNeural": "温柔英音，亲和力强",
    "en-GB-MaisieNeural": "少女英音，轻快明亮",
    "en-GB-RyanNeural": "标准英音男声，BBC 播音感",
    "en-GB-ThomasNeural": "温和英音，叙述感强",
}


ZH_VOICE_NAMES = {
    "Xiaoxiao": "晓晓", "Xiaoyi": "晓伊", "Yunjian": "云健",
    "Yunxi": "云希", "Yunxia": "云夏", "Yunyang": "云扬",
}


def short_name(full):
    """zh-CN-XiaoxiaoNeural -> 晓晓；en-US-AvaNeural -> Ava"""
    base = full.split("-")[-1].replace("Neural", "")
    return ZH_VOICE_NAMES.get(base, base)


def load_voices():
    if os.path.exists(VOICE_CACHE):
        with open(VOICE_CACHE, encoding="utf-8") as f:
            data = json.load(f)
    else:
        import asyncio
        import edge_tts
        raw = asyncio.run(edge_tts.list_voices())
        data = [{"name": x["ShortName"], "locale": x["Locale"], "gender": x["Gender"],
                 "friendly": x.get("FriendlyName", ""), "tags": x.get("VoiceTag", {})}
                for x in raw]
        with open(VOICE_CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    data = [v for v in data
            if v["locale"] in ALLOWED_LOCALES and "Multilingual" not in v["name"]]
    order = list(ALLOWED_LOCALES)
    for v in data:
        v["lang"] = LANG_NAMES.get(v["locale"], v["locale"])
        v["short"] = short_name(v["name"])
        v["note"] = VOICE_NOTES.get(v["name"], "")
        v["label"] = "%s · %s" % (v["lang"], "女声" if v["gender"] == "Female" else "男声")
    data.sort(key=lambda v: (order.index(v["locale"]),
                             v["gender"] != "Female", v["name"]))
    return data


VOICES = load_voices()
VGENDER = {v["name"]: v["gender"] for v in VOICES}


def voice_gender(name):
    """"Female" / "Male" / "" """
    return VGENDER.get(name, "")


def pct(v, default="+0%"):
    """把 -20 / '-20%' 统一成 edge-tts 需要的格式"""
    if v is None or v == "":
        return default
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("%"):
            return s
        try:
            return "%+d%%" % int(float(s))
        except ValueError:
            return default
    return "%+d%%" % int(v)


def hz(v):
    if v is None or v == "":
        return "+0Hz"
    if isinstance(v, str):
        s = v.strip()
        return s if s.endswith("Hz") else "%+dHz" % int(float(s))
    return "%+dHz" % int(v)


import re  # noqa: E402

# ---------------------------------------------------------------- 角色自动识别
ROLE_LINE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9_\-]{0,11}|[\u4e00-\u9fa5]{1,8})\s*[:：](?!//)\s*")

VOICE_POOL = {
    "zh": [("zh-CN-XiaoxiaoNeural", "F"), ("zh-CN-YunxiNeural", "M"),
           ("zh-CN-XiaoyiNeural", "F"), ("zh-CN-YunjianNeural", "M"),
           ("zh-CN-YunyangNeural", "M"), ("zh-CN-YunxiaNeural", "M")],
    # 英文默认走英音（可再手动切美音）
    "en": [("en-GB-SoniaNeural", "F"), ("en-GB-RyanNeural", "M"),
           ("en-GB-LibbyNeural", "F"), ("en-GB-ThomasNeural", "M"),
           ("en-GB-MaisieNeural", "F")],
}
FEMALE_WORDS = ("女", "妈", "姐", "妹", "姨", "奶", "婆", "妻", "娘")
MALE_WORDS = ("男", "爸", "哥", "弟", "叔", "爷", "公", "夫", "爹")


def detect_lang(text):
    body = re.sub(r"\s", "", text)
    if not body:
        return "en"
    cn = sum(1 for ch in body if "\u4e00" <= ch <= "\u9fff")
    return "zh" if cn / len(body) > 0.2 else "en"


# 听力卷常用角色 → 默认音色（C 中文旁白 / W、Q 英式女声 / M 英式男声）
DEFAULT_ROLE_VOICE = {
    "C": "zh-CN-XiaoxiaoNeural",
    "W": "en-GB-SoniaNeural",
    "Q": "en-GB-SoniaNeural",
    "M": "en-GB-RyanNeural",
}


def assign_voices(names, lang, roles_map=None):
    """按角色顺序分配音色：指定 > 内置默认 > 按性别推断"""
    pool = VOICE_POOL.get(lang, VOICE_POOL["en"])
    fem = [v for v, g in pool if g == "F"]
    mal = [v for v, g in pool if g == "M"]
    allv = [v for v, _ in pool]
    used, out = set(), {}

    def take(cands, i):
        for v in cands:
            if v not in used:
                used.add(v)
                return v
        return cands[i % len(cands)]

    for i, n in enumerate(names):
        preset = (roles_map or {}).get(n)
        builtin = DEFAULT_ROLE_VOICE.get(n.strip().upper())
        if preset:
            out[n] = preset
            used.add(preset)
        elif builtin:
            out[n] = builtin
            used.add(builtin)
        elif any(k in n for k in FEMALE_WORDS):
            out[n] = take(fem, i)
        elif any(k in n for k in MALE_WORDS):
            out[n] = take(mal, i)
        else:
            out[n] = take(allv, i)
    return out


def parse_roles(text):
    """按出现顺序扫描角色名"""
    names, seen = [], set()
    for raw in text.split("\n"):
        m = ROLE_LINE_RE.match(raw)
        if not m:
            continue
        name = m.group(1).strip()
        if name.lower() in ("http", "https", "note", "tip"):
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def build_segments(payload):
    mode = payload.get("mode", "single")
    text = (payload.get("text") or "").replace("\r\n", "\n").strip()
    if not text:
        raise ValueError("请先输入要朗读的文字")

    rate = pct(payload.get("rate"))
    pitch = hz(payload.get("pitch"))
    volume = pct(payload.get("volume"))
    line_pause = float(payload.get("linePause") or 0.6)

    def base(voice):
        return {"voice": voice, "role": "", "rate": rate, "pitch": pitch, "volume": volume}

    segs = []

    if mode == "dialogue":
        lang = detect_lang(text)
        names = parse_roles(text)
        if not names:
            raise ValueError("没有识别到角色。请用「角色名: 台词」格式，每行一句，如 A: Hello")

        roles_map = payload.get("roles") or {}
        if not roles_map and payload.get("voiceA"):
            roles_map = {"A": payload["voiceA"],
                         "B": payload.get("voiceB") or payload["voiceA"]}
        assign = assign_voices(names, lang, roles_map)

        role_rates = payload.get("roleRates") or {}
        cur_name = names[0]
        cur = assign[cur_name]
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            m = ROLE_LINE_RE.match(line)
            if m:
                nm = m.group(1).strip()
                line = line[m.end():].strip()
                cur = assign.get(nm, cur)
                cur_name = nm
            if not line:
                continue
            for chunk, acts in engine.split_marks(line):
                s = base(cur)
                s["text"] = chunk
                s["role"] = cur_name
                s["rate"] = pct(role_rates.get(cur_name), rate)
                s["after"] = acts + [["pause", line_pause]]
                segs.append(s)
        return segs

    voice = payload.get("voice") or "zh-CN-XiaoxiaoNeural"

    if mode == "dictation":
        repeat = max(1, min(int(payload.get("repeat") or 2), 5))
        word_gap = float(payload.get("wordGap") or 2.0)
        spell = bool(payload.get("spell"))
        for raw in text.split("\n"):
            w = raw.strip()
            if not w:
                continue
            s = base(voice)
            if spell:
                core = "".join(ch for ch in w.upper() if ch.isalpha() and ch.isascii())
                if core:
                    s["text"] = ", ".join(core)
                    s["after"] = [["pause", 1.0]]
                    segs.append(s)
            for k in range(repeat):
                s = base(voice)
                s["text"] = w
                s["after"] = [["pause", word_gap]]
                segs.append(s)
        if not segs:
            raise ValueError("听写模式没有解析到单词")
        return segs

    # 单人朗读：整段合成，按标记切分
    for chunk, acts in engine.split_marks(text):
        for piece in engine.split_sentences(chunk):
            s = base(voice)
            s["text"] = piece
            s["after"] = []
            segs.append(s)
        if segs and acts:
            segs[-1]["after"].extend(acts)
    return segs


def load_history():
    if os.path.exists(HIST_FILE):
        try:
            with open(HIST_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return []
    return []


def save_history(items):
    with HIST_LOCK:
        with open(HIST_FILE, "w", encoding="utf-8") as f:
            json.dump(items[:60], f, ensure_ascii=False, indent=1)


@app.route("/")
def index():
    return send_from_directory(os.path.join(BASE, "templates"), "index.html")


@app.route("/api/voices")
def api_voices():
    return jsonify({"count": len(VOICES), "voices": VOICES})


@app.route("/api/roles", methods=["POST"])
def api_roles():
    payload = request.get_json(force=True, silent=True) or {}
    text = (payload.get("text") or "").replace("\r\n", "\n")
    lang = detect_lang(text)
    names = parse_roles(text)
    voices = assign_voices(names, lang)
    out = []
    for n in names:
        if any(k in n for k in FEMALE_WORDS):
            g = "女"
        elif any(k in n for k in MALE_WORDS):
            g = "男"
        else:
            g = ""
        out.append({"name": n, "voice": voices.get(n), "gender": g,
                    "preset": n.strip().upper() in DEFAULT_ROLE_VOICE})
    return jsonify({"lang": lang, "count": len(out), "roles": out})


@app.route("/api/sfx/<int:n>")
def api_sfx(n):
    return send_file(sfx.get(n), mimetype="audio/mpeg")


@app.route("/api/sfx-list")
def api_sfx_list():
    return jsonify([{"id": i, "name": sfx.NAMES[i], "desc": sfx.DESCS[i]}
                    for i in sorted(sfx.NAMES)])


@app.route("/api/preview")
def api_preview():
    voice = request.args.get("voice", "zh-CN-XiaoxiaoNeural")
    text = request.args.get("text") or ("你好，这是语音试听。" if voice.startswith("zh")
                                        else "Hello, this is a voice preview.")
    tmp = os.path.join(OUT_DIR, "_preview_%s.mp3" % uuid.uuid4().hex[:8])
    try:
        import asyncio
        asyncio.run(engine._synth(text, voice, "+0%", "+0Hz", "+0%", tmp))
        with open(tmp, "rb") as f:
            data = f.read()
        return send_file(io.BytesIO(data), mimetype="audio/mpeg")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


@app.route("/api/synthesize", methods=["POST"])
def api_synthesize():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        segs = build_segments(payload)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    job_id = uuid.uuid4().hex[:12]
    out_name = "tts_%s_%s.mp3" % (time.strftime("%Y%m%d_%H%M%S"), job_id[:4])
    out_path = os.path.join(OUT_DIR, out_name)

    # 前端逐句试听需要的元数据（音色、角色、文本、句后停顿/提示音）
    meta = [{"i": i,
             "role": s.get("role") or "",
             "voice": s["voice"],
             "vlabel": short_name(s["voice"]),
             "glabel": "女" if voice_gender(s["voice"]) == "Female" else "男",
             "text": s["text"],
             "after": s.get("after") or [],
             "ready": False}
            for i, s in enumerate(segs, 1)]

    JOBS[job_id] = {"status": "running", "done": 0, "total": len(segs),
                    "msg": "正在合成…", "file": None, "error": None,
                    "duration": 0, "stage": "synth",
                    "segs": meta, "raw": segs,
                    "title": (payload.get("text") or "")[:40].replace("\n", " ")}

    def mark_ready(i, path=None):
        if 0 < i <= len(meta):
            meta[i - 1]["ready"] = True

    def worker():
        try:
            key = cache_key(segs)
            cached = os.path.join(CACHE_DIR, key + ".mp3")
            all_seg_cached = all(engine.seg_exists(s) for s in segs)

            if os.path.exists(cached) and all_seg_cached:
                JOBS[job_id].update(done=len(segs), msg="命中缓存，直接输出")
                for m in meta:
                    m["ready"] = True
                shutil.copyfile(cached, out_path)
                dur = engine.duration(out_path)
            else:
                def cb(i, n, txt):
                    JOBS[job_id].update(done=i, msg="%d/%d %s" % (i, n, txt[:26]))

                dur, _ = engine.render(segs, out_path, cb, mark_ready)
                try:
                    shutil.copyfile(out_path, cached)
                    trim_cache()
                    trim_seg_cache()
                except Exception:  # noqa: BLE001
                    pass

            for m in meta:
                m["ready"] = True
            JOBS[job_id].update(status="done", file=out_name,
                                duration=round(dur, 2), msg="完成", stage="done")
            item = {"id": job_id, "file": out_name, "name": out_name,
                    "title": JOBS[job_id]["title"] or out_name,
                    "mode": payload.get("mode", "single"),
                    "voice": payload.get("voice") or payload.get("voiceA") or "",
                    "duration": round(dur, 2),
                    "chars": len(payload.get("text") or ""),
                    "time": time.strftime("%m-%d %H:%M")}
            with HIST_LOCK:
                h = load_history()
                h.insert(0, item)
                save_history(h)
        except Exception as e:  # noqa: BLE001
            JOBS[job_id].update(status="error", error=str(e), msg="失败", stage="error")

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"job_id": job_id, "total": len(segs), "segs": meta})


@app.route("/api/job/<job_id>")
def api_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify({
        "status": job["status"], "done": job["done"], "total": job["total"],
        "msg": job["msg"], "file": job.get("file"),
        "duration": job.get("duration") or 0, "error": job.get("error"),
        "stage": job.get("stage"),
        "segs_ready": [m["i"] for m in job.get("segs", []) if m["ready"]],
    })


@app.route("/api/seg/<job_id>/<int:i>")
def api_seg(job_id, i):
    """单独取第 i 句的音频，供网页逐句试听 / 边生成边播放"""
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "任务已过期，请重新生成"}), 404
    segs = job.get("raw") or []
    if i < 1 or i > len(segs):
        return jsonify({"error": "序号超出范围"}), 404
    p = engine.seg_path(segs[i - 1])
    if not os.path.exists(p):
        return jsonify({"error": "该句还没合成完"}), 404
    return send_file(p, mimetype="audio/mpeg", conditional=True, max_age=3600)


@app.route("/api/segs/<job_id>")
def api_segs(job_id):
    """取回某次任务的分段清单（历史记录回看用）"""
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "任务已过期，请重新生成"}), 404
    raw = job.get("raw") or []
    out = []
    for m in job.get("segs", []):
        d = dict(m)
        d["ready"] = os.path.exists(engine.seg_path(raw[m["i"] - 1]))
        out.append(d)
    return jsonify({"job_id": job_id, "segs": out, "file": job.get("file"),
                    "duration": job.get("duration") or 0})


@app.route("/files/<path:name>")
def files(name):
    return send_from_directory(OUT_DIR, name, as_attachment=False)


@app.route("/download/<path:name>")
def download(name):
    return send_from_directory(OUT_DIR, name, as_attachment=True)


@app.route("/api/history", methods=["GET", "DELETE"])
def api_history():
    if request.method == "DELETE":
        save_history([])
        return jsonify({"ok": True})
    items = [x for x in load_history()
             if os.path.exists(os.path.join(OUT_DIR, x.get("file", "")))]
    return jsonify(items)


@app.route("/health")
def health():
    return jsonify({"ok": True, "voices": len(VOICES)})


def free_port(start=5000):
    for p in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


if __name__ == "__main__":
    port = int(os.environ.get("TTS_PORT") or free_port())
    url = "http://127.0.0.1:%d" % port
    print("=" * 52)
    print("  文字转语音工具已启动")
    print("  地址: %s" % url)
    print("  音色: %d 个 · 关闭此窗口即停止服务" % len(VOICES))
    print("=" * 52)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
