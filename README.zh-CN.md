# 新疆数字人项目

这是新疆数字人项目的清理版源码包。

Wav2Lip 源码已经保存在 GitHub 仓库中。大模型权重、TensorRT engine、数字人形象资源等大文件不放入 GitHub。运行后端前，需要先从百度网盘下载运行资源，并恢复到指定目录。

[English README](README.md)

## 运行资源

| 文件 | 百度网盘链接 | 提取码 | 恢复路径 |
| --- | --- | --- | --- |
| `wav2lip.pth` | https://pan.baidu.com/s/1Sm5NpQOa9Ue_No4gm_pVeA?pwd=pfq1 | `pfq1` | `realtime-digital-human/wav2lip256/wav2lip.pth` |
| `data.zip` | https://pan.baidu.com/s/1FtGG3WoNOXHZdwBWKc-yJw?pwd=fhnq | `fhnq` | 解压到 `realtime-digital-human/`，确保存在 `realtime-digital-human/data/` |

资源恢复完成后，后端目录中应至少包含：

- `realtime-digital-human/wav2lip256/audio.py`
- `realtime-digital-human/wav2lip256/models/wav2lip.py`
- `realtime-digital-human/wav2lip256/wav2lip.pth`
- `realtime-digital-human/data/avatars/wav2lip_avatar11/`
- `realtime-digital-human/data/ref_audios/`
- `realtime-digital-human/data/customimage/`

更多资源说明见 `ASSETS.md`。

## 项目结构

- `realtime-digital-human/`：后端服务和 Wav2Lip 运行时。
- `digitalhuman-frontend/`：前端项目和 Docker 部署文件。
- `start.sh`：本地后端启动脚本。运行凭证需要通过环境变量或 `.env` 文件提供。

## 基础启动流程

1. 恢复上面列出的运行资源。
2. 通过环境变量或本地 `.env` 文件配置后端凭证，`.env` 不提交到 GitHub。
3. 进入 `realtime-digital-human/`，执行 `uv sync` 安装后端依赖。
4. 在项目根目录执行 `./start.sh` 启动后端。
5. 进入 `digitalhuman-frontend/` 构建或启动前端。

## XJDploy 近期修改记录

本节记录 `XJDploy` 分支在首个智能体部署版本之后的主要修改内容。

当前参考点：

- 智能体部署基线版本：`aa6b035`（`新疆项目部署版本，更换了新的智能体`）
- 记录本文档时的最新打包版本：`7927930`（`接入智能体历史上下文`）
- 如果本地包已经是 `digitalhuman-Xinjiang-XJDploy-7927930.zip`，记录本文档时 `origin/XJDploy` 上没有更新的已提交代码。

从 `aa6b035` 到 `7927930` 的修改摘要：

| 提交 | 模块 | 目的 |
| --- | --- | --- |
| `2a070d3` | 智能体 LLM 请求 | 修复智能体请求 payload 字段，避免 `406 Not Acceptable`。 |
| `84b5ce2` | 前端 WebRTC | 增加长时间运行 WebRTC watchdog 和自动重连逻辑。 |
| `13f6bda` | 前端和诊断 | 降低浏览器长时间运行崩溃风险，并增加前端、后端、系统诊断日志。 |
| `71df69d` | ASR | 增加警亿问通流式 ASR 重连、失败熔断、buffered fallback 和详细诊断。 |
| `7927930` | 智能体 history | 增加 `getChatInfo` 历史查询，并把最近历史传入 `agentChat/query`。 |

### 智能体请求和 history

警亿问通智能体 provider 实现在：

```text
realtime-digital-human/llm/providers/gongan.py
```

智能体请求接口：

```text
POST /agentService/agentChat/query
```

请求 payload 的关键字段：

```json
{
  "modelId": "<GONGAN_AGENT_MODEL_ID or GONGAN_MODEL_ID>",
  "friendId": "<GONGAN_AGENT_FRIEND_ID>",
  "history": [],
  "query": "<指令 + 用户问题>",
  "stream": true,
  "startFlag": 0,
  "useTmp": 0,
  "exact_match": false,
  "file_names": [],
  "isBoot": "1"
}
```

如果配置了 `GONGAN_AGENT_PROCESS_ID`，provider 会按照上游接口字段拼写发送为 `prrocessId`。

history 支持流程：

1. 请求 `agentChat/query` 前，后端先调用：

   ```text
   POST /agentService/agentChat/getChatInfo
   ```

2. 根据 `GONGAN_AGENT_FRIEND_ID` 获取最近对话记录。
3. 把每条历史转换为类 OpenAI history 格式：

   ```json
   [
     {"role": "user", "content": "<上一轮用户问题>"},
     {"role": "assistant", "content": "<上一轮模型回复>"}
   ]
   ```

4. 将转换后的 history 放入下一次 `agentChat/query` 请求。

推荐后端 `.env` 配置：

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

注意：

- `GONGAN_AGENT_FRIEND_ID` 是 history 查询所需字段。只配置 `GONGAN_AGENT_ID` 时，智能体对话可以工作，但 history 查询会返回空。
- `GONGAN_AGENT_HISTORY_ROWS=1` 是保守配置，只关联上一轮回复，避免带入过多旧上下文。
- 如果多个浏览器会话共用同一个 `GONGAN_AGENT_FRIEND_ID`，上游服务侧的对话历史也可能被共用。

### 内网 ASR 接入

内网 Qwen ASR provider 实现在：

```text
realtime-digital-human/asr/innerasr.py
```

它与原有警亿问通 ASR 相互独立。只切换 ASR，LLM 和 TTS 仍可继续使用
`gongan` / `gongantts`。内网环境的 `.env` 配置示例：

```bash
ASR_PROVIDER=innerasr
LLM_PROVIDER=gongan
TTS_PROVIDER=gongantts

INNER_ASR_WS_URL=wss://<内网ASR地址>:<端口>/api/ws/asr
INNER_ASR_ORIGIN=https://<内网ASR地址>:<端口>
INNER_ASR_INSECURE=1
INNER_ASR_CONNECT_TIMEOUT=10
INNER_ASR_READY_TIMEOUT=10
INNER_ASR_FINAL_TIMEOUT=30
INNER_ASR_CHUNK_BYTES=12800
```

协议固定为：连接后等待 `ready`，发送 16kHz、单声道、PCM16LE
二进制音频，结束时发送 `{"event":"commit"}`。流式文本使用
`partial.delta` 和 `replace_from` 合并，最终文本读取 `final.full_text`。

回退到原 ASR 时只需修改：

```bash
ASR_PROVIDER=gongan
```

### ASR 流式自恢复

警亿问通 ASR provider 实现在：

```text
realtime-digital-human/asr/gongan.py
```

近期增加的能力：

- WebSocket ASR 连接诊断。
- 流式 ASR socket 异常关闭时尝试重连一次。
- 重连后回放已缓存音频。
- 流式 ASR 多次失败时进入熔断，临时回退到 buffered ASR。
- 增加 token 来源、连接状态、已发送音频字节数、关闭码、关闭原因、fallback 路径等日志。

使用流式 ASR 时推荐配置：

```bash
GONGAN_ASR_STREAMING=1
GONGAN_ASR_STREAM_RETRY_LIMIT=1
GONGAN_ASR_STREAM_FAILURE_THRESHOLD=2
GONGAN_ASR_STREAM_CIRCUIT_COOLDOWN=300
GONGAN_ASR_STREAM_REPLAY_CHUNK_BYTES=4096
GONGAN_ASR_STREAM_REPLAY_INTERVAL=0
```

如果配置 `GONGAN_ASR_STREAMING=0`，项目会使用 buffered ASR。该模式下，流式重连和熔断逻辑会被绕过。

### 前端 WebRTC 自恢复

浏览器端 WebRTC 自恢复逻辑主要在：

```text
digitalhuman-frontend/src/components/VideoDiv.vue
digitalhuman-frontend/src/utils/clientDiagnostics.js
digitalhuman-frontend/src/composables/useAudioStream.js
```

近期增加的能力：

- 视频帧 watchdog。
- WebRTC 异常状态检测。
- 长时间无视频帧时自动重连。
- 多次重连失败后自动刷新页面。
- 重连前清理旧 peer 的事件监听器。
- 前端全局诊断：`window_error`、`unhandled_rejection`、页面可见性、online/offline 状态、页面生命周期事件。
- 限制 WebRTC stats 历史缓存大小，减少浏览器长时间运行内存压力。

前端 Docker 镜像重建前，推荐配置 `digitalhuman-frontend/.env`：

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

前端代码修改后，需要重新构建并重建容器：

```bash
cd digitalhuman-frontend
sudo docker compose build --no-cache frontend
sudo docker compose up -d --force-recreate frontend
```

### 长时间运行机器诊断

机器级监控脚本：

```text
realtime-digital-human/scripts/monitor_system.sh
```

长时间或过夜测试前启动：

```bash
cd realtime-digital-human
mkdir -p logs
nohup bash scripts/monitor_system.sh 10 logs > logs/system_monitor.nohup 2>&1 &
```

脚本会记录 CPU、内存、磁盘、Docker、后端 Python 进程、Chrome 进程、GPU 利用率、GPU 显存等快照。配合 `[CLIENT_METRICS]` 和 `[SERVER_METRICS]`，可以判断崩溃更可能来自浏览器、后端、GPU、WebRTC 还是整机资源压力。

## 首次部署检查清单

以下步骤适用于新的 Ubuntu GPU 服务器。

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human

# 安装 Python 依赖，避免 "No module named 'torch'"。
uv sync

# 如果使用 WAV2LIP_BACKEND=tensorrt，需要额外安装。
uv pip install onnx tensorrt-cu12

# 验证运行环境。
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
uv run python -c "import tensorrt as trt; print(trt.__version__)"

# 执行部署前检查。
bash scripts/check_deploy_ready.sh
```

如果启用 TensorRT，需要在目标服务器上生成 engine：

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human

uv run python scripts/export_wav2lip_onnx.py \
  --checkpoint ./wav2lip256/wav2lip.pth \
  --output ./wav2lip256/wav2lip_256.onnx

PRECISION=fp16 \
ONNX_PATH=./wav2lip256/wav2lip_256.onnx \
ENGINE_PATH=./wav2lip256/wav2lip_server_fp16.engine \
MODEL_SIZE=256 \
MIN_BATCH=1 \
OPT_BATCH=16 \
MAX_BATCH=16 \
WORKSPACE_MIB=2048 \
bash scripts/build_wav2lip_tensorrt.sh
```

然后在后端 `.env` 中设置：

```bash
WAV2LIP_BACKEND=tensorrt
WAV2LIP_ENGINE_PATH=./wav2lip256/wav2lip_server_fp16.engine
```

从项目根目录启动：

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang
./start.sh
```

如果 engine 还没有生成，可以先用 PyTorch 后端启动：

```bash
WAV2LIP_BACKEND=pytorch ./start.sh
```

## 长时间播放诊断

项目中包含前端和后端诊断日志，用于定位数字人运行 20-30 分钟后变卡、刷新浏览器后恢复的问题。

后端 `.env` 中开启诊断：

```bash
SERVER_METRICS_ENABLED=1
SERVER_METRICS_INTERVAL_S=10
CLIENT_METRICS_MAX_BYTES=120000
CLIENT_METRICS_MAX_TEXT=3000
```

前端 `.env` 中开启诊断，开启后需要重新构建前端镜像：

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

过夜测试前，在单独终端启动机器级监控：

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human
mkdir -p logs
nohup bash scripts/monitor_system.sh 10 logs > logs/system_monitor.nohup 2>&1 &
```

重建并重启前后端后，在浏览器中复现问题，直到播放变卡或 Chrome 标签页崩溃。然后收集后端日志：

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human
latest_log=$(ls -t logs/file_*.log | head -1)

grep -E '\[CLIENT_METRICS\]|\[CLIENT_METRICS_EVENT\]|\[CLIENT_EVENT\]|\[SERVER_METRICS\]|actual avg final fps|queue dropped|interrupt request|audio_ws_|video_|webrtc_' "$latest_log" \
  > /tmp/digitalhuman-stall-diagnostics.log
```

分析时请提供这些文件：

- `/tmp/digitalhuman-stall-diagnostics.log`
- `realtime-digital-human/logs/` 下最新完整后端日志
- 最新的 `realtime-digital-human/logs/system_monitor_*.log`
- 如果监控脚本异常停止，也提供 `realtime-digital-human/logs/system_monitor.nohup`

诊断日志内容说明：

- `[CLIENT_METRICS]`：浏览器端视频/音频元素状态、WebRTC ICE/connection 状态、RTP 入站统计、视频解码/丢帧增量、JS heap、页面可见性、窗口尺寸、音频采集和发送计数。
- `[CLIENT_METRICS_EVENT]` / `[CLIENT_EVENT]`：浏览器生命周期和错误事件，包括 `window_error`、`unhandled_rejection`、`pagehide`、`pageshow`、`visibilitychange`、视频 `waiting/stalled/error`、WebRTC 重连调度、watchdog 触发刷新。
- `[SERVER_METRICS]`：后端进程 RSS、线程数、文件描述符、CUDA 显存、活跃会话、WebRTC peer connection 状态、渲染队列、音频队列、TTS 状态、Wav2Lip 帧队列、track 输出队列。
- `system_monitor_*.log`：机器级 CPU、内存、磁盘、Docker、后端 Python 进程、Chrome renderer/GPU 进程、GPU 利用率和显存快照。
- 事件日志：WebRTC offer/answer 耗时、track 到达、video `playing/waiting/stalled/error`、音频 WebSocket 生命周期、麦克风 recorder 生命周期、interrupt 请求。

初步判断方法：

- Chrome renderer RSS 持续增长，而后端 RSS 稳定：优先怀疑浏览器、WebRTC 或视频解码泄漏。
- 后端 Python RSS 或文件描述符持续增长：优先检查后端 session、队列、缓存或资源清理。
- GPU 显存持续增长：优先检查 CUDA/TensorRT 或 Chrome GPU 进程资源泄漏。
- 资源稳定，但 WebRTC 变成 `failed`/`disconnected`，或视频 decoded frame delta 变为 0：优先检查连接或媒体管线卡死。
- 崩溃前出现 `[CLIENT_EVENT] window_error` 或 `unhandled_rejection`：优先排查前端运行时异常。

## 响应延迟和唇音同步诊断

后端会为每次用户请求输出 trace 级日志。每个请求都有 `trace_id`，贯穿 VAD、ASR、LLM、TTS、Wav2Lip 和 WebRTC 输出。

默认情况下，聚焦的 pipeline 诊断日志写入：

```bash
realtime-digital-human/logs/pipeline_diagnostics.log
```

可以在后端 `.env` 中修改路径和日志策略：

```bash
PIPELINE_DIAG_LOG_ENABLED=1
PIPELINE_DIAG_LOG_PATH=./logs/pipeline_diagnostics.log
PIPELINE_DIAG_LOG_LEVEL=DEBUG
PIPELINE_DIAG_LOG_ROTATION=200 MB
PIPELINE_DIAG_LOG_RETENTION=7 days
```

以下问题建议使用该日志分析：

- 数字人响应速度慢。
- TTS 语音被截断或播报不完整。
- TTS 语音和数字人口型不匹配。

复现问题后，优先提供这个聚焦日志：

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human
ls -lh logs/pipeline_diagnostics.log
```

如果聚焦日志不可用，可以从完整后端日志中提取同类信息：

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human
latest_log=$(ls -t logs/file_*.log | head -1)

grep -E '\[PERF\]|\[时间点\]|\[AUDIO_DIAG\]|\[SYNC_DIAG\]|GonganTTS|Gongan LLM|ASR|VAD|queue dropped|track_recv' "$latest_log" \
  > /tmp/digitalhuman-pipeline-diagnostics.log
```

分析时请尽量同时提供 `logs/pipeline_diagnostics.log` 和最新完整后端日志。

按 `trace_id` 对比这些关键事件：

- `vad speech_segment`：VAD 说话时长和尾部等待。
- `asr provider_end_session`：ASR 服务耗时和识别文本长度。
- `trace llm_first_token` / `trace llm_done`：LLM 首 token 和完整流式输出耗时。
- `trace tts_segment_dispatch`：LLM 文本片段进入 TTS 的时间。
- `trace tts_first_audio_packet` / `trace tts_first_audio_frame`：TTS 首包音频和首个可播放音频帧耗时。
- `tts stream_finish_wait`：流式 TTS 是否正常结束或在音频未全部到达前超时。
- `tts pcm_flush`：PCM 包数量、生成的音频帧数量、尾部补齐帧、音频时长。
- `tts audio_frames_to_wav2lip`：推入 Wav2Lip 的 20ms 音频帧数量。
- `trace wav2lip_first_output_frame`：第一帧口型输出。
- `webrtc track_recv_wait_slow` / `webrtc track_queue_drop`：WebRTC 输出等待或丢帧情况。
