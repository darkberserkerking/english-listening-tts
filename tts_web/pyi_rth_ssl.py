#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PyInstaller runtime hook：绕开 Windows 根证书存储。

aiohttp 在 import 阶段会调用 ssl.create_default_context()，在部分 Windows
机器上读取系统根证书存储时遇到畸形证书会抛
`ssl.SSLError: [ASN1: NOT_ENOUGH_DATA]`，导致整个程序启动失败。
这里把默认 CA 换成随包附带的 certifi，既避开系统存储，也不依赖目标机器
预装证书。仅在打包运行时生效，源码运行不受影响。
"""
import ssl

try:
    import certifi

    _cafile = certifi.where()
    _orig_create = ssl.create_default_context

    def _create_with_certifi(*args, **kwargs):
        kwargs.setdefault("cafile", _cafile)
        return _orig_create(*args, **kwargs)

    ssl.create_default_context = _create_with_certifi
except Exception:  # certifi 缺失时保持原行为，由后续冒烟测试暴露
    pass
