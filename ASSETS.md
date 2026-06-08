# Runtime Assets

The repository includes the Wav2Lip source code under `realtime-digital-human/wav2lip256/`. It intentionally excludes large runtime assets. Restore them after cloning the project.

## Required

| Asset | Baidu Netdisk link | Code | Restore path | Notes |
| --- | --- | --- | --- | --- |
| `wav2lip.pth` | https://pan.baidu.com/s/1Sm5NpQOa9Ue_No4gm_pVeA?pwd=pfq1 | `pfq1` | `realtime-digital-human/wav2lip256/wav2lip.pth` | Required by the backend model loader. |
| `data.zip` | https://pan.baidu.com/s/1FtGG3WoNOXHZdwBWKc-yJw?pwd=fhnq | `fhnq` | unzip into `realtime-digital-human/` | Contains `data/avatars/`, `data/ref_audios/`, and `data/customimage/`. |

After extracting `data.zip`, confirm these paths exist:

- `realtime-digital-human/data/avatars/wav2lip_avatar11/`
- `realtime-digital-human/data/ref_audios/`
- `realtime-digital-human/data/customimage/`

## Optional

| Asset | Restore path | Size in local x86 project | Notes |
| --- | --- | ---: | --- |
| Avatar 5 frames | `realtime-digital-human/data/avatars/wav2lip_avatar5/` | about 1.3 GB | Keep only if you need this older avatar. It is not used by the current `start.sh` flow. |

## Do not upload to Baidu Netdisk

These files are not needed for deployment because they can be rebuilt or are local byproducts:

- `realtime-digital-human/.venv/`
- `realtime-digital-human/logs/`
- `realtime-digital-human/dataandwave2lip256.zip`
- frontend `node_modules/`, `dist/`, `dist-electron/`
- local certificates and `.env` files
