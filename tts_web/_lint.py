#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""静态一致性检查：JS 里用到的元素 id / 接口 是否都在 HTML / 后端里存在"""
import re
import os

BASE = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(BASE, "templates", "index.html"), encoding="utf-8").read()
js = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
body = html.split("<body>")[1].split("<script>")[0]

ids = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', body))
used = set(re.findall(r"""\$\('#([A-Za-z0-9_\-]+)'\)""", js))
used |= set(re.findall(r"""getElementById\('([A-Za-z0-9_\-]+)'\)""", js))

miss = sorted(used - ids)
print("HTML 里的 id 数: %d" % len(ids))
print("JS 引用的 id 数: %d" % len(used))
print("  缺失(会崩): %s" % (miss if miss else "无"))
print("  未被 JS 使用: %s" % (sorted(ids - used) or "无"))

# 前端调用的接口 vs 后端定义
app_src = open(os.path.join(BASE, "app.py"), encoding="utf-8").read()
routes = set(re.findall(r'@app\.route\("(/[^"<]*)', app_src))
routes |= set(re.findall(r'@app\.route\("(/[^"]*)"', app_src))
called = set()
for m in re.findall(r"""fetch\(\s*['"]([^'"?]+)""", js):
    called.add(m)
for m in re.findall(r"""(?:src|href)\s*=\s*['"`](/[^'"`?$]+)""", js):
    called.add(m)
called = {c for c in called if c.startswith("/")}
print("\n后端路由: %s" % sorted(routes))
print("前端调用: %s" % sorted(called))


def match(c):
    for r in routes:
        rr = re.sub(r"<[^>]+>", "", r).rstrip("/")
        if c == r or c.rstrip("/") == rr or c.startswith(rr + "/") or (rr and c.startswith(rr)):
            return True
    return False


bad = sorted(c for c in called if not match(c) and not c.startswith("/api/seg"))
print("  对不上的调用: %s" % (bad if bad else "无"))
assert not miss, "有缺失的元素 id"
