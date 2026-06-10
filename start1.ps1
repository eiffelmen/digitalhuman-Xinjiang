$env:IFLYTEK_SN = "1234567890"
$env:IFLYTEK_APPID = "3180af67"
$env:IFLYTEK_API_KEY = "2f34da499df6d46b350ec6dc23e92e21"
$env:IFLYTEK_API_SECRET = "ZjM3ZmMyYjRiYmFiMDkwMmU0ZjQyM2Yz"
if (-not $env:IFLYTEK_VCN) { $env:IFLYTEK_VCN = "x2_xiaojuan" }
if (-not $env:IFLYTEK_TTS_ENGINE) { $env:IFLYTEK_TTS_ENGINE = "aiui" }
if (-not $env:IFLYTEK_TTS_FALLBACK_VCN) { $env:IFLYTEK_TTS_FALLBACK_VCN = "xiaoyan" }
if (-not $env:IFLYTEK_SUPER_TTS_URL) { $env:IFLYTEK_SUPER_TTS_URL = "wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6" }
if (-not $env:IFLYTEK_TTS_SPEED) { $env:IFLYTEK_TTS_SPEED = "45" }
if (-not $env:IFLYTEK_TTS_VOLUME) { $env:IFLYTEK_TTS_VOLUME = "55" }
if (-not $env:IFLYTEK_TTS_PITCH) { $env:IFLYTEK_TTS_PITCH = "48" }
if (-not $env:IFLYTEK_INCREMENTAL_TTS) { $env:IFLYTEK_INCREMENTAL_TTS = "1" }
if (-not $env:IFLYTEK_REPLY_INSTRUCTION) { $env:IFLYTEK_REPLY_INSTRUCTION = "请用简洁、口语化中文回答，控制在80字以内，适合数字人口播。" }

# 公安新 API（ASR / TTS / 大模型）
if (-not $env:GONGAN_API_BASE_URL) { $env:GONGAN_API_BASE_URL = "https://jywt.com.cn/ga/api" }
if (-not $env:GONGAN_TTS_WS_URL) { $env:GONGAN_TTS_WS_URL = "wss://jywt.com.cn/ga/api/audio/paddlespeech/tts/streaming" }
if (-not $env:GONGAN_ASR_WS_URL) { $env:GONGAN_ASR_WS_URL = "wss://jywt.com.cn/ga/api/audio/paddlespeech/asr/streaming" }
if (-not $env:GONGAN_API_USERNAME) { $env:GONGAN_API_USERNAME = "1234567" }
if (-not $env:GONGAN_API_PWD_MD5) { $env:GONGAN_API_PWD_MD5 = "96e79218965eb72c92a549dd5a330112" }
if (-not $env:GONGAN_MODEL_NAME) { $env:GONGAN_MODEL_NAME = "qwen3-14b" }
if (-not $env:GONGAN_REPLY_INSTRUCTION) { $env:GONGAN_REPLY_INSTRUCTION = "请用简洁、口语化中文回答，控制在80字以内，适合数字人口播。不要输出思考过程。" }
if (-not $env:GONGAN_DIRECT_TTS) { $env:GONGAN_DIRECT_TTS = "1" }
if (-not $env:GONGAN_TTS_SPK_ID) { $env:GONGAN_TTS_SPK_ID = "0" }
if (-not $env:GONGAN_ASR_PUNCTUATION) { $env:GONGAN_ASR_PUNCTUATION = "1" }
if (-not $env:GONGAN_ASR_STREAMING) { $env:GONGAN_ASR_STREAMING = "0" }
if (-not $env:GONGAN_ASR_SEND_INTERVAL) { $env:GONGAN_ASR_SEND_INTERVAL = "0.01" }

if (-not $env:ASR_PROVIDER) { $env:ASR_PROVIDER = "gongan" }
if (-not $env:LLM_PROVIDER) { $env:LLM_PROVIDER = "gongan" }
if (-not $env:TTS_PROVIDER) { $env:TTS_PROVIDER = "gongantts" }
$env:FUNASR_HOST = "36.103.180.159"
$env:FUNASR_PORT = "10095"

$env:CUDA_VISIBLE_DEVICES = "0"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BACKEND_DIR = Join-Path -Path $ScriptDir -ChildPath "realtime-digital-human"

Set-Location -Path $BACKEND_DIR
& .\run_iflytek_server.ps1
