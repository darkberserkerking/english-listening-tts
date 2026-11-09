# english-listening-tts

一个本地运行的文字转语音工具，专为制作**英语听力卷**设计。

粘贴带角色标记的文本，即可生成带停顿、提示音、多角色音色的 MP3。支持边生成边播放和逐句试听，改一句不用重跑全篇。

## 功能

- **三种模式**：单人朗读 / 多人对话 / 单词听写
- **多人对话**：角色数量按文本自动识别，不限人数。默认 `C` = 中文旁白、`W` / `Q` = 英式女声、`M` = 英式男声；每个角色都能单独选音色、调语速
- **24 个音色**：普通话 / 英式 / 美式，每个带特点说明，可试听
- **标记语法**：`(⏱️=3s)` 插入停顿，`(🔔=1)` ~ `(🔔=7)` 插入 7 种提示音
- **边生成边播放**：第一句合成完就出声，不必等整卷跑完
- **逐句试听**：结果区列出每一句，标注角色与音色；可只播一句、或从任意句连续往下播，自动执行停顿与提示音
- **单句内容寻址缓存**：按「文本 + 音色 + 语速 + 音调 + 音量」哈希，重复句子直接复用，二次生成几乎瞬时

## 快速开始

需要 Python 3.9+，运行时需要联网（语音由在线服务合成）。

```bash
pip install -r requirements.txt
cd tts_web
python app.py
```

浏览器会自动打开 `http://127.0.0.1:5000`。Windows 下也可直接双击 `tts_web/start_tts.bat`。

系统未安装 ffmpeg 也没关系，`imageio-ffmpeg` 会提供便携版可执行文件。

## 文本格式

多人对话模式每行写「角色名: 台词」：

```
C: 请仔细听，每题听两遍。(🔔=1)
W: I like playing football. I like playing football. (⏱️=3s)
M: He wants to join the Robot Club. (⏱️=3s)(🔔=2)
Q: What does he want to join? (⏱️=10s)
```

| 标记 | 作用 |
| --- | --- |
| `(⏱️=3s)` | 在该句后停顿 3 秒，支持小数 |
| `(🔔=1)` | 播放 1 号提示音；1 叮咚 / 2 风铃 / 3 嘟嘟 / 4 哒喃 / 5 当~ / 6 咚~ / 7 叮~ |
| `[pause:2]`、`[ding:3]` | 等价的 ASCII 写法 |

角色名不限于 `C` / `W` / `M` / `Q`，任意名字（如 `Lily`、`妈妈`）都会自动分配不重复的音色。

## 工作原理

```text
文本 → 按角色/句子切分 → 并发调用 edge-tts → 每句 MP3（内容哈希缓存）
                                              ↓
                          ffmpeg 按顺序拼接语音 + 静音 + 提示音 → 整段 MP3
```

- 整段 MP3 由后端一次性拼接，供下载
- 网页逐句播放时，直接取每句缓存文件；停顿与提示音在前端执行，因此暂停能立刻中断、停顿还能显示倒计时
- 提示音由 `sfx.py` 用纯 Python 合成（指数衰减包络 + 泛音叠加），不依赖外部音频素材

## 项目结构

```
tts_web/
  app.py                  Flask 后端、角色识别、分段元数据、HTTP 接口
  engine.py               分句合成、内容寻址缓存、ffmpeg 拼接
  sfx.py                  7 种提示音合成
  templates/index.html    单文件前端，无 CDN 依赖
  voices_cache.json       音色清单缓存（避免每次启动时联网拉取）
  start_tts.bat           Windows 启动脚本
  _lint.py                前端元素 id / 接口一致性检查
  _test_juke.js           播放状态机测试（假 DOM，26 项断言）
  _test_pipeline.py       后端全链路冒烟测试
  _test_latency.py        冷启动时序测量
  _test_real.py           真实规模测试
  cache/                  运行时生成，不入库
  output/                 运行时生成，不入库
build_listening.py        早期命令行版：听力卷专用生成器
tts_make.py               早期命令行版：通用 TTS 生成器
```

## 测试

```bash
cd tts_web
python _lint.py             # 静态一致性检查
node _test_juke.js          # 播放状态机（需 Node.js）
python _test_pipeline.py    # 后端全链路（会实际调用在线接口）
```

## 注意

- 本项目通过 `edge-tts` 调用 Microsoft Edge「大声朗读」功能背后的在线接口。该接口**不是微软公开的官方 API**，没有文档、没有 SLA、不保证长期可用，微软在线服务条款也未明确授权第三方程序调用。接口变更或限流时，合成可能失败或变慢。
- **文本会发送到微软服务器**，请勿输入敏感、私密或含个人信息的内容。
- 本项目仅供个人学习与教学使用。用于公开分发或商业用途前，请自行评估授权风险，或改用 [Azure AI Speech](https://azure.microsoft.com/pricing/details/cognitive-services/speech-services/) 官方接口。
- 依赖许可证：`edge-tts` 为 LGPLv3、`Flask` 为 BSD-3-Clause、`imageio-ffmpeg` 为 BSD-2-Clause。本仓库目前**未指定 LICENSE**，如需授权他人使用请自行补充，并注意 LGPLv3 的兼容性要求。
