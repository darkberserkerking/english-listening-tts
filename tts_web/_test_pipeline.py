#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""后端链路冒烟测试：分句 -> 合成 -> 单句音频可取 -> 整段拼接"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as A

TEXT = """C: 请仔细听，每题听两遍。(🔔=1)
W: I like playing football. I like playing football. (⏱️=3s)
M: He wants to join the Robot Club. (⏱️=2s)
Q: What does he want to join? (🔔=2)
"""

payload = {"mode": "dialogue", "text": TEXT,
           "roles": {"C": "zh-CN-XiaoxiaoNeural",
                     "W": "en-US-AvaNeural",
                     "M": "en-US-AndrewNeural",
                     "Q": "en-US-AvaNeural"},
           "roleRates": {"W": -20}, "rate": 0, "linePause": 0.6}

segs = A.build_segments(payload)
print("分句数: %d" % len(segs))
for s in segs:
    print("  role=%-2s voice=%-22s after=%s | %s"
          % (s.get("role"), s["voice"], s.get("after"), s["text"][:44]))

c = A.app.test_client()
r = c.post("/api/synthesize", json=payload)
assert r.status_code == 200, r.get_data(as_text=True)
d = r.get_json()
job = d["job_id"]
print("\njob=%s total=%d  返回 meta 条数=%d" % (job, d["total"], len(d["segs"])))
assert len(d["segs"]) == len(segs)

t0 = time.time()
first_ready_at = None
while True:
    j = c.get("/api/job/" + job).get_json()
    if first_ready_at is None and j["segs_ready"]:
        first_ready_at = time.time() - t0
    if j["status"] in ("done", "error"):
        break
    time.sleep(0.15)

print("首句可播: %.2fs   全部完成: %.2fs   状态=%s"
      % (first_ready_at or -1, time.time() - t0, j["status"]))
assert j["status"] == "done", j

print("就绪句数: %d / %d" % (len(j["segs_ready"]), j["total"]))
assert len(j["segs_ready"]) == j["total"], "有句子没标记就绪"

# 逐句取音频
ok = 0
for i in range(1, j["total"] + 1):
    rs = c.get("/api/seg/%s/%d" % (job, i))
    if rs.status_code != 200:
        print("  第 %d 句取不到: %s" % (i, rs.status_code))
        continue
    body = rs.get_data()
    assert len(body) > 800, "第 %d 句太小" % i
    assert body[:2] in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), "第 %d 句不是 mp3" % i
    ok += 1
print("可单独播放的句子: %d / %d" % (ok, j["total"]))
assert ok == j["total"]

# 整段文件
full = c.get("/files/" + j["file"])
print("整段 MP3: %d 字节  时长 %.2fs" % (len(full.get_data()), j["duration"]))
assert len(full.get_data()) > 10000

# 越界与不存在的任务
print("越界请求 ->", c.get("/api/seg/%s/999" % job).status_code)
print("无效任务 ->", c.get("/api/seg/nope/1").status_code)

# 缓存命中：同样内容再跑一次应该很快
t1 = time.time()
r2 = c.post("/api/synthesize", json=payload).get_json()
job2 = r2["job_id"]
while True:
    j2 = c.get("/api/job/" + job2).get_json()
    if j2["status"] in ("done", "error"):
        break
    time.sleep(0.1)
print("同内容二次生成: %.2fs  状态=%s  就绪=%d" %
      (time.time() - t1, j2["status"], len(j2["segs_ready"])))
assert j2["status"] == "done" and len(j2["segs_ready"]) == j2["total"]

print("\n全部通过")
