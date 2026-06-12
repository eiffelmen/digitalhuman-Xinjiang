#!/bin/bash
set -e

export IFLYTEK_SN="${IFLYTEK_SN:-}"
export IFLYTEK_APPID="${IFLYTEK_APPID:-}"
export IFLYTEK_API_KEY="${IFLYTEK_API_KEY:-}"
export IFLYTEK_API_SECRET="${IFLYTEK_API_SECRET:-}"
export IFLYTEK_VCN="${IFLYTEK_VCN:-x2_xiaojuan}"
export IFLYTEK_TTS_ENGINE="${IFLYTEK_TTS_ENGINE:-aiui}"
export IFLYTEK_TTS_FALLBACK_VCN="${IFLYTEK_TTS_FALLBACK_VCN:-xiaoyan}"
export IFLYTEK_SUPER_TTS_URL="${IFLYTEK_SUPER_TTS_URL:-wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6}"
export IFLYTEK_TTS_SPEED="${IFLYTEK_TTS_SPEED:-45}"
export IFLYTEK_TTS_VOLUME="${IFLYTEK_TTS_VOLUME:-55}"
export IFLYTEK_TTS_PITCH="${IFLYTEK_TTS_PITCH:-48}"
export IFLYTEK_INCREMENTAL_TTS="${IFLYTEK_INCREMENTAL_TTS:-1}"
export IFLYTEK_REPLY_INSTRUCTION="${IFLYTEK_REPLY_INSTRUCTION:-请用简洁、口语化中文回答，控制在80字以内，适合数字人口播。}"

# 公安新 API（ASR / TTS / 大模型）
export GONGAN_API_BASE_URL="${GONGAN_API_BASE_URL:-https://jywt.com.cn/ga/api}"
export GONGAN_TTS_WS_URL="${GONGAN_TTS_WS_URL:-wss://jywt.com.cn/ga/api/audio/paddlespeech/tts/streaming}"
export GONGAN_ASR_WS_URL="${GONGAN_ASR_WS_URL:-wss://jywt.com.cn/ga/api/audio/paddlespeech/asr/streaming}"
export GONGAN_API_USERNAME="${GONGAN_API_USERNAME:-}"
export GONGAN_API_PWD_MD5="${GONGAN_API_PWD_MD5:-}"
export GONGAN_MODEL_NAME="${GONGAN_MODEL_NAME:-qwen3-14b}"
export GONGAN_REPLY_INSTRUCTION="${GONGAN_REPLY_INSTRUCTION:-请用简洁、口语化中文回答，控制在80字以内，适合数字人口播。不要输出思考过程。}"
export GONGAN_DIRECT_TTS="${GONGAN_DIRECT_TTS:-1}"
export GONGAN_TTS_SPK_ID="${GONGAN_TTS_SPK_ID:-0}"
export GONGAN_ASR_PUNCTUATION="${GONGAN_ASR_PUNCTUATION:-1}"
export GONGAN_ASR_STREAMING="${GONGAN_ASR_STREAMING:-1}"
export GONGAN_ASR_SEND_INTERVAL="${GONGAN_ASR_SEND_INTERVAL:-0.01}"

export ASR_PROVIDER="${ASR_PROVIDER:-gongan}"
export LLM_PROVIDER="${LLM_PROVIDER:-gongan}"
export TTS_PROVIDER="${TTS_PROVIDER:-gongantts}"
export FUNASR_HOST="${FUNASR_HOST:-127.0.0.1}"
export FUNASR_PORT="${FUNASR_PORT:-10095}"

export CUDA_VISIBLE_DEVICES=0

BACKEND_DIR="$(cd "$(dirname "$0")/realtime-digital-human" && pwd)"
cd "$BACKEND_DIR" && exec bash run_iflytek_server.sh
