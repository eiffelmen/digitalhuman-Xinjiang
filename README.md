# Digital Human Xinjiang

This is the cleaned source package for the Xinjiang digital human project.

The Wav2Lip source code is stored in GitHub. Large model weights and avatar assets are not stored in GitHub. Download the runtime assets from Baidu Netdisk and restore them before running the backend.

## Runtime Assets

| File | Baidu Netdisk link | Code | Restore path |
| --- | --- | --- | --- |
| `wav2lip.pth` | https://pan.baidu.com/s/1Sm5NpQOa9Ue_No4gm_pVeA?pwd=pfq1 | `pfq1` | `realtime-digital-human/wav2lip256/wav2lip.pth` |
| `data.zip` | https://pan.baidu.com/s/1FtGG3WoNOXHZdwBWKc-yJw?pwd=fhnq | `fhnq` | unzip into `realtime-digital-human/`, so `realtime-digital-human/data/` exists |

After restoring the assets, the backend should contain:

- `realtime-digital-human/wav2lip256/audio.py`
- `realtime-digital-human/wav2lip256/models/wav2lip.py`
- `realtime-digital-human/wav2lip256/wav2lip.pth`
- `realtime-digital-human/data/avatars/wav2lip_avatar11/`
- `realtime-digital-human/data/ref_audios/`
- `realtime-digital-human/data/customimage/`

See `ASSETS.md` for more details.

## Layout

- `realtime-digital-human/`: backend service and Wav2Lip runtime.
- `digitalhuman-frontend/`: frontend project and Docker deployment files.
- `start.sh`: local backend startup wrapper. Runtime credentials must be supplied through environment variables.

## Basic startup

1. Restore the runtime assets listed above.
2. Configure backend credentials with environment variables or a local `.env` file that is not committed.
3. Install backend dependencies in `realtime-digital-human/` with `uv sync`.
4. Start the backend with `./start.sh`.
5. Build or run the frontend from `digitalhuman-frontend/`.

## First Deployment Checklist

These steps are intended for a fresh Ubuntu GPU server.

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human

# Install Python dependencies. This prevents "No module named 'torch'".
uv sync

# Optional but required when using WAV2LIP_BACKEND=tensorrt.
uv pip install onnx tensorrt-cu12

# Verify the runtime.
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
uv run python -c "import tensorrt as trt; print(trt.__version__)"

# Run deployment preflight checks.
bash scripts/check_deploy_ready.sh
```

If TensorRT is enabled, generate the engine on the target server:

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

Then set the backend `.env`:

```bash
WAV2LIP_BACKEND=tensorrt
WAV2LIP_ENGINE_PATH=./wav2lip256/wav2lip_server_fp16.engine
```

Start from the project root:

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang
./start.sh
```

Useful fallback: if the engine has not been generated yet, run with PyTorch first:

```bash
WAV2LIP_BACKEND=pytorch ./start.sh
```

## Long-running Playback Diagnostics

The project includes browser and backend diagnostics for investigating the issue where the digital human becomes choppy after running for 20-30 minutes and recovers after refreshing the browser.

Enable the diagnostics in the backend `.env`:

```bash
SERVER_METRICS_ENABLED=1
SERVER_METRICS_INTERVAL_S=10
CLIENT_METRICS_MAX_BYTES=120000
CLIENT_METRICS_MAX_TEXT=3000
```

Enable the diagnostics in the frontend `.env` before rebuilding the frontend image:

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

Start the machine-level monitor in a separate terminal before the overnight test:

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human
mkdir -p logs
nohup bash scripts/monitor_system.sh 10 logs > logs/system_monitor.nohup 2>&1 &
```

After rebuilding and restarting the frontend/backend, reproduce the problem in the browser until playback becomes choppy or the Chrome tab crashes. Then collect the backend logs:

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human
latest_log=$(ls -t logs/file_*.log | head -1)

grep -E '\[CLIENT_METRICS\]|\[CLIENT_METRICS_EVENT\]|\[CLIENT_EVENT\]|\[SERVER_METRICS\]|actual avg final fps|queue dropped|interrupt request|audio_ws_|video_|webrtc_' "$latest_log" \
  > /tmp/digitalhuman-stall-diagnostics.log
```

Send these files for analysis:

- `/tmp/digitalhuman-stall-diagnostics.log`
- the full latest backend log under `realtime-digital-human/logs/`
- the latest `realtime-digital-human/logs/system_monitor_*.log`
- `realtime-digital-human/logs/system_monitor.nohup` if the monitor stopped unexpectedly

What the diagnostics contain:

- `[CLIENT_METRICS]`: browser-side video/audio element state, WebRTC ICE/connection state, inbound RTP stats, decoded/dropped video frame deltas, JS heap usage, page visibility, viewport, and audio capture/send counters.
- `[CLIENT_METRICS_EVENT]` / `[CLIENT_EVENT]`: browser lifecycle and error events, including `window_error`, `unhandled_rejection`, `pagehide`, `pageshow`, `visibilitychange`, video `waiting/stalled/error`, WebRTC reconnect scheduling, and watchdog-triggered reloads.
- `[SERVER_METRICS]`: backend process RSS/thread/file-descriptor snapshot, CUDA memory snapshot, active sessions, WebRTC peer connection states, per-session render queues, audio queues, TTS state, Wav2Lip frame queue, and track output queues.
- `system_monitor_*.log`: machine-level CPU, memory, disk, Docker, Python backend process, Chrome renderer/GPU process, GPU utilization and GPU memory snapshots.
- Event logs: WebRTC offer/answer timing, track arrival, video `playing/waiting/stalled/error`, audio WebSocket lifecycle, microphone recorder lifecycle, and interrupt requests.

Initial diagnosis guide:

- Chrome renderer RSS keeps growing while backend RSS is stable: browser/WebRTC/video decode leak or tab-level crash.
- Backend Python RSS or open file descriptors keep growing: backend session, queue, cache, or resource cleanup issue.
- GPU memory keeps growing: CUDA/TensorRT or Chrome GPU process resource leak.
- Resource usage is stable but WebRTC changes to `failed`/`disconnected` or video decoded frame delta becomes zero: connection or media pipeline stall.
- `[CLIENT_EVENT] window_error` or `unhandled_rejection` appears shortly before crash: frontend runtime exception should be investigated first.

## Response Latency And Lip-sync Diagnostics

The backend also emits trace-level logs for each user request. Every request has a `trace_id`, which is carried through VAD, ASR, LLM, TTS, Wav2Lip, and WebRTC output.

By default, focused pipeline diagnostics are written to:

```bash
realtime-digital-human/logs/pipeline_diagnostics.log
```

The path can be changed in backend `.env`:

```bash
PIPELINE_DIAG_LOG_ENABLED=1
PIPELINE_DIAG_LOG_PATH=./logs/pipeline_diagnostics.log
PIPELINE_DIAG_LOG_LEVEL=DEBUG
PIPELINE_DIAG_LOG_ROTATION=200 MB
PIPELINE_DIAG_LOG_RETENTION=7 days
```

Use this when investigating:

- Slow digital human response.
- TTS audio being cut off or incomplete.
- TTS audio and mouth movement not matching.

After reproducing the issue, send this focused log file:

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human
ls -lh logs/pipeline_diagnostics.log
```

If the focused file is unavailable, collect the same information from the full backend log:

```bash
cd /home/dsd/wz/digitalhuman-Xinjiang/realtime-digital-human
latest_log=$(ls -t logs/file_*.log | head -1)

grep -E '\[PERF\]|\[时间点\]|\[AUDIO_DIAG\]|\[SYNC_DIAG\]|GonganTTS|Gongan LLM|ASR|VAD|queue dropped|track_recv' "$latest_log" \
  > /tmp/digitalhuman-pipeline-diagnostics.log
```

Send `logs/pipeline_diagnostics.log` plus the full latest backend log if possible.

Important actions to compare by `trace_id`:

- `vad speech_segment`: VAD speaking duration and trailing wait.
- `asr provider_end_session`: ASR service latency and recognized text length.
- `trace llm_first_token` / `trace llm_done`: LLM first-token and full-stream latency.
- `trace tts_segment_dispatch`: LLM text segment entering TTS.
- `trace tts_first_audio_packet` / `trace tts_first_audio_frame`: TTS first audio packet and first playable audio frame latency.
- `tts stream_finish_wait`: whether streamed TTS finished normally or timed out before all audio arrived.
- `tts pcm_flush`: total PCM packets, generated audio frames, padded tail frame, and audio duration.
- `tts audio_frames_to_wav2lip`: number of 20 ms audio frames pushed into Wav2Lip.
- `trace wav2lip_first_output_frame`: first mouth-frame output.
- `webrtc track_recv_wait_slow` / `webrtc track_queue_drop`: WebRTC output wait or dropped frames.
