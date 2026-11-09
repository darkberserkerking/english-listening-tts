#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真实听力卷规模测试：分句 / 冷启动首句时延 / 总耗时 / 逐句可取"""
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import app as A

text = open(os.path.join(os.path.dirname(BASE), "listen_hobbies.txt"), encoding="utf-8").read()

payload = {"mode": "dialogue", "text": text, "rate": 0, "linePause": 0.6,
           "roleRates": {"W": -20, "M": -20, "Q": -20}}

segs = A.build_segments(payload)
print("原始文本: %d 字" % len(text))
print("分句数: %d" % len(segs))
from collections import Counter
print("角色分布:", dict(Counter(s.get("role") for s in segs)))
print("有提示音的句子:", sum(1 for s in segs if any(a[0] == "ding" for a in s["after"])))
print("最长停顿: %.1fs" % max([a[1] for s in segs for a in s["after"] if a[0] == "pause"] or [0]))

c = A.app.test_client()
t0 = time.time()
d = c.post("/api/synthesize", json=payload).get_json()
if "error" in d:
    print("失败:", d); sys.exit(1)
job = d["job_id"]
first = None
while True:
    j = c.get("/api/job/" + job).get_json()
    if first is None and j["segs_ready"]:
        first = time.time() - t0
    if j["status"] in ("done", "error"):
        break
    time.sleep(0.1)

total = time.time() - t0
print("\n首句可播: %.2fs" % (first or -1))
print("全部完成: %.2fs   状态=%s   时长=%.1fs 音频" % (total, j["status"], j["duration"]))
assert j["status"] == "done", j
assert len(j["segs_ready"]) == j["total"]

ok = sum(1 for i in range(1, j["total"] + 1)
         if c.get("/api/seg/%s/%d" % (job, i)).status_code == 200)
print("可单独取到的句子: %d / %d" % (ok, j["total"]))
assert ok == j["total"]

print("整段文件: %.2f MB" % (os.path.getsize(os.path.join(A.OUT_DIR, j["file"])) / 1048576))

# 历史回看接口
r = c.get("/api/segs/" + job)
print("历史回看: %s  条数=%d" % (r.status_code, len(r.get_json().get("segs", []))))
assert r.status_code == 200

# 单句平均大小
import statistics
sizes = [len(c.get("/api/seg/%s/%d" % (job, i)).get_data()) for i in (1, 2, 3)]
print("单句音频平均 %.0f KB" % (statistics.mean(sizes) / 1024))
print("\n通过")
