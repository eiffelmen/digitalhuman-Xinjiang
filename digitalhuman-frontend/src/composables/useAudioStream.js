import Recorder from 'recorder-core'
import 'recorder-core/src/engine/pcm'
import { buildWsUrl, buildApiUrl } from '@/config/index.js'
import { store } from '@/store/store.js'
import { postClientDiagnosticEvent } from '@/utils/clientDiagnostics.js'

const parsedAudioMetricsInterval = Number(import.meta.env.VITE_AUDIO_STREAM_METRICS_INTERVAL_MS || 10000)
const AUDIO_STREAM_METRICS_INTERVAL_MS = Number.isFinite(parsedAudioMetricsInterval)
  ? Math.max(3000, parsedAudioMetricsInterval)
  : 10000

async function callInterrupt(sessionId) {
  try {
    await fetch(buildApiUrl('backend', '/interrupt'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionid: sessionId }),
    })
  } catch (e) {
    console.warn('[AudioStream] interrupt call failed', e)
  }
}

export function useAudioStream(sessionId) {
  let rec = null
  let audioWs = null
  let started = false
  let interruptCooling = false  // 防止重复触发打断
  let interruptCoolingTimer = null
  let metricsTimer = null
  let chunksSent = 0
  let bytesSent = 0
  let droppedBuffered = 0
  let droppedNotOpen = 0
  let interruptRequests = 0
  let maxPowerLevel = 0
  const MAX_BUFFERED_BYTES = 256 * 1024

  function reportAudioMetric(event, extra = {}) {
    postClientDiagnosticEvent(event, {
      sessionId,
      extra: {
        chunksSent,
        bytesSent,
        droppedBuffered,
        droppedNotOpen,
        interruptRequests,
        maxPowerLevel,
        wsReadyState: audioWs?.readyState,
        wsBufferedAmount: audioWs?.bufferedAmount,
        recorderStarted: started,
        avatarSpeaking: store.avatarSpeaking,
        ...extra,
      },
    })
  }

  function start() {
    if (started) return
    started = true

    const wsPath = `/ws-audio/${sessionId}`
    const url = buildWsUrl('backend', wsPath)
    audioWs = new WebSocket(url)
    audioWs.binaryType = 'arraybuffer'

    audioWs.addEventListener('error', (e) => {
      console.error('[AudioStream] WebSocket error', e)
      reportAudioMetric('audio_ws_error', { errorType: e?.type })
    })
    audioWs.addEventListener('close', () => {
      console.log('[AudioStream] WebSocket closed')
      reportAudioMetric('audio_ws_close')
    })
    audioWs.addEventListener('open', () => {
      reportAudioMetric('audio_ws_open')
    })

    metricsTimer = setInterval(() => {
      reportAudioMetric('audio_stream_metrics')
      maxPowerLevel = 0
    }, AUDIO_STREAM_METRICS_INTERVAL_MS)

    rec = Recorder({
      type: 'pcm',
      sampleRate: 16000,
      bitRate: 16,
      // 开启浏览器级 AEC，消除扬声器回声
      audioTrackSet: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      onProcess(buffers, powerLevel, bufferDuration, bufferSampleRate) {
        maxPowerLevel = Math.max(maxPowerLevel, powerLevel || 0)
        if (!started || !audioWs || audioWs.readyState !== WebSocket.OPEN) {
          droppedNotOpen += 1
          return
        }
        if (audioWs.bufferedAmount > MAX_BUFFERED_BYTES) {
          droppedBuffered += 1
          return
        }

        const pcm = Recorder.SampleData(
          [buffers[buffers.length - 1]],
          bufferSampleRate,
          16000,
        ).data

        // 数字人正在说话时：检测到较大音量才触发打断，再送 ASR
        if (powerLevel > 20 && store.avatarSpeaking && !interruptCooling) {
          interruptCooling = true
          interruptRequests += 1
          reportAudioMetric('audio_interrupt_request', {
            powerLevel,
            bufferDuration,
            bufferSampleRate,
          })
          callInterrupt(sessionId).finally(() => {
            interruptCoolingTimer = setTimeout(() => {
              interruptCooling = false
              interruptCoolingTimer = null
            }, 500)
          })
        }

        // 所有帧都发给后端，由 VAD 状态机判断语音起止
        audioWs.send(pcm.buffer)
        chunksSent += 1
        bytesSent += pcm.byteLength
      },
    })

    rec.open(
      () => {
        console.log('[AudioStream] mic opened with AEC, starting continuous recording')
        reportAudioMetric('audio_recorder_open')
        rec.start()
      },
      (msg, isUserNotAllow) => {
        console.error(
          '[AudioStream] mic open failed:',
          isUserNotAllow ? '用户拒绝麦克风权限' : msg,
        )
        reportAudioMetric('audio_recorder_open_failed', { message: msg, isUserNotAllow })
        if (metricsTimer) {
          clearInterval(metricsTimer)
          metricsTimer = null
        }
        started = false
      },
    )
  }

  function stop() {
    started = false
    interruptCooling = false
    if (interruptCoolingTimer) {
      clearTimeout(interruptCoolingTimer)
      interruptCoolingTimer = null
    }
    if (metricsTimer) {
      clearInterval(metricsTimer)
      metricsTimer = null
    }
    reportAudioMetric('audio_stream_stop')
    if (rec) {
      try {
        rec.stop()
      } catch (e) {
        console.warn('[AudioStream] recorder stop failed', e)
      }
      try {
        if (typeof rec.close === 'function') {
          rec.close()
        }
      } catch (e) {
        console.warn('[AudioStream] recorder close failed', e)
      }
      rec = null
    }
    if (audioWs) {
      try {
        audioWs.onopen = null
        audioWs.onmessage = null
        audioWs.onerror = null
        audioWs.onclose = null
        audioWs.close()
      } catch (e) {
        console.warn('[AudioStream] WebSocket close failed', e)
      }
      audioWs = null
    }
  }

  return { start, stop }
}
