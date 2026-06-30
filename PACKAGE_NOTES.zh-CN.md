# XJDploy 源码包说明

本 tar 包基于 GitHub 仓库 `eiffelmen/digitalhuman-Xinjiang.git` 的 `XJDploy` 分支整理，用于新疆数字人智能体部署版本的代码交付和部署留档。

## 包内容

本包包含：

- 后端源码：`realtime-digital-human/`
- 前端源码和 Docker 部署文件：`digitalhuman-frontend/`
- 项目启动脚本：`start.sh`
- 英文 README：`README.md`
- 中文 README：`README.zh-CN.md`
- 运行资源说明：`ASSETS.md`

本包不包含：

- `.git/`
- `.env` 本地敏感配置
- Python 虚拟环境 `.venv/`
- 前端依赖 `node_modules/`
- 前端构建产物 `dist/`
- 后端运行日志 `logs/`
- 大模型权重、TensorRT engine、ONNX、视频和压缩资源等运行期大文件

## 运行资源

运行前需要按 `README.zh-CN.md` 和 `ASSETS.md` 恢复大文件资源，主要包括：

- `realtime-digital-human/wav2lip256/wav2lip.pth`
- `realtime-digital-human/data/`
- 如启用 TensorRT，还需要在目标 GPU 服务器上重新生成或放置 `wav2lip_server_fp16.engine`

TensorRT engine 与服务器上的 TensorRT/CUDA/显卡驱动版本强相关，不建议直接跨机器复用。

## 本版本重点

本版本是 `XJDploy` 智能体部署分支，主要包含以下能力：

1. 警亿问通智能体接口适配。
2. 智能体 history 上下文接入，通过 `getChatInfo` 获取上一轮问答并放入 `agentChat/query`。
3. ASR 流式自恢复和失败回退，降低长时间运行后麦克风无响应的概率。
4. 前端 WebRTC 长时间运行 watchdog、自恢复重连和多次失败后的自动刷新。
5. 前端、后端和机器级诊断日志，用于定位浏览器崩溃、卡顿、ASR/LLM/TTS 耗时和唇音同步问题。

## 推荐配置

智能体 history 推荐配置：

```bash
GONGAN_AGENT_ENABLED=1
GONGAN_AGENT_FRIEND_ID=<friend id>
GONGAN_AGENT_MODEL_ID=<model id>
GONGAN_MODEL_ID=<model id>
GONGAN_MODEL_NAME=<model name>

GONGAN_AGENT_HISTORY_ENABLED=1
GONGAN_AGENT_HISTORY_ROWS=1
GONGAN_AGENT_HISTORY_MAX_CHARS=2000
GONGAN_AGENT_HISTORY_TIMEOUT=3
```

长时间播放诊断推荐配置：

```bash
SERVER_METRICS_ENABLED=1
SERVER_METRICS_INTERVAL_S=10
CLIENT_METRICS_MAX_BYTES=120000
CLIENT_METRICS_MAX_TEXT=3000
```

前端 WebRTC 自恢复推荐配置：

```bash
VITE_CLIENT_METRICS_ENABLED=1
VITE_CLIENT_METRICS_INTERVAL_MS=10000
VITE_CLIENT_METRICS_VERBOSE=0
VITE_AUDIO_STREAM_METRICS_INTERVAL_MS=10000
VITE_WEBRTC_WATCHDOG_ENABLED=1
VITE_WEBRTC_WATCHDOG_INTERVAL_MS=5000
VITE_WEBRTC_NO_FRAME_TIMEOUT_MS=25000
VITE_WEBRTC_BAD_CONNECTION_TIMEOUT_MS=8000
VITE_WEBRTC_RECONNECT_DELAY_MS=1500
VITE_WEBRTC_MAX_RECONNECTS=8
VITE_WEBRTC_RELOAD_AFTER_RECONNECTS=1
```

更多部署步骤和诊断方法见 `README.zh-CN.md`。
