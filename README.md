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
