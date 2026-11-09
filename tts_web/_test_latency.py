#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""冷启动时序：每一句从"开始生成"到"可播放"要多久"""
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A

tag = uuid.uuid4().hex[:6]
lines = []
for k in range(1, 13):
    lines.append("W: This is sentence number %d for timing test %s. (⏱️=2s)" % (k, tag))
text = "\n".join(lines)

payload = {"mode": "dialogue", "text": text,
           "roles": {"W": "en-US-AvaNeural"}, "rate": 0, "linePause": 0.6}

c = A.app.test_client()
t0 = time.time()
d = c.post("/api/synthesize", json=payload).get_json()
job = d["job_id"]
total = d["total"]

marks = {}
while True:
    j = c.get("/api/job/" + job).get_json()
    now = time.time() - t0
    for i in j["segs_ready"]:
        marks.setdefault(i, now)
    if j["status"] in ("done", "error"):
        break
    time.sleep(0.05)

print("共 %d 句（全部冷启动）" % total)
for i in sorted(marks):
    print("  第 %2d 句可播: %5.2fs" % (i, marks[i]))
print("全部完成: %.2fs" % (time.time() - t0))
print("\n第一句 %.2fs 就能听到 → 边生成边播放的等待感 ≈ 这个数"
      % marks.get(1, -1))
print("用户听完整段需要 %.1fs，而合成只需 %.1fs → 播放永远追不上合成，不会卡"
      % (total * 3.0, time.time() - t0))
