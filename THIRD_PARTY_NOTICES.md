# 第三方组件与许可声明

本仓库**原创代码**采用 [MIT License](LICENSE)。运行时与构建过程中用到的第三方组件，各自遵循其原始许可证；MIT 授权不覆盖这些组件。

## 运行时依赖

| 组件 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| edge-tts | 7.3.1 | LGPL-3.0 | 语音合成 |
| Flask | 3.1.3 | BSD-3-Clause | Web 后端 |
| aiohttp（含传递依赖） | 3.14.5 | Apache-2.0 AND MIT | HTTP / WebSocket |
| imageio-ffmpeg | 0.8.1 | BSD-2-Clause | 便携版 ffmpeg |
| certifi | 2026.10.23 | MPL-2.0 | TLS 根证书 |
| PyInstaller | 6.19.0 | GPL-2.0-or-later + bootloader exception | 仅构建期使用 |

版本以 `requirements.txt` 与 `tts.spec` 实际安装为准，许可证信息取自各包的 PyPI 元数据。

## Windows exe 分发说明

Release 中的 `EnglishListeningTTS-*.exe` 由 PyInstaller 打包，内部包含 Python 运行时、上述依赖的字节码，以及 ffmpeg 可执行文件。

- **edge-tts 为 LGPL-3.0**：分发包含该组件的二进制时，应向接收者提供该组件的源代码或等价获取方式，并允许其替换该组件。本项目已在 GitHub 公开全部原创源码，并在 `requirements.txt` 中声明依赖版本；接收者可执行 `pip download edge-tts==7.3.1` 取得对应源码，也可直接从源码重新构建 exe（构建命令见 README）。
- **PyInstaller bootloader** 采用 GPLv2 加 bootloader exception，明确允许用它构建并分发非 GPL（含商业）程序。
- **ffmpeg** 便携版由 imageio-ffmpeg 提供，本项目未修改其二进制，按其随附许可分发。
- **certifi** 随附 Mozilla 根证书，遵循 MPL-2.0。

各组件名称、商标与版权归各自所有者所有。

## 在线服务不受本许可约束

语音合成实际调用 Microsoft Edge「大声朗读」功能背后的在线接口。该服务不是本仓库的一部分，其可用性与使用条款由微软决定；本仓库的任何许可证均不授予对该服务的使用权。商用前请先评估该服务的授权风险，或改用 [Azure AI Speech](https://azure.microsoft.com/pricing/details/cognitive-services/speech-services/) 官方接口。详见 README「注意」章节。
