import Recorder from 'recorder-core'
import 'recorder-core/src/engine/pcm'
import { buildWsUrl, buildApiUrl } from '@/config/index.js'
import { store } from '@/store/store.js'
import { postClientDiagnosticEvent } from '@/utils/clientDiagnostics.js'

const parsedAudioMetricsInterval = Number(import.meta.env.VITE_AUDIO_STREAM_METRICS_INTERVAL_MS || 10000)
const AUDIO_STREAM_METRICS_INTERVAL_MS = Number.isFinite(parsedAudioMetricsInterval)
  ? Math.max(3000, parsedAudioMetricsInterval)
  : 10000
const parsedAudioWsReconnectBase = Number(import.meta.env.VITE_AUDIO_WS_RECONNECT_BASE_MS || 500)
const AUDIO_WS_RECONNECT_BASE_MS = Number.isFinite(parsedAudioWsReconnectBase)
  ? Math.max(200, parsedAudioWsReconnectBase)
  : 500
const parsedAudioWsReconnectMax = Number(import.meta.env.VITE_AUDIO_WS_RECONNECT_MAX_MS || 5000)
const AUDIO_WS_RECONNECT_MAX_MS = Number.isFinite(parsedAudioWsReconnectMax)
  ? Math.max(AUDIO_WS_RECONNECT_BASE_MS, parsedAudioWsReconnectMax)
  : 5000

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
  let reconnectTimer = null
  let reconnectAttempts = 0
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

  function scheduleAudioWsReconnect(reason) {
    if (!started || reconnectTimer) return
    const delay = Math.min(
      AUDIO_WS_RECONNECT_MAX_MS,
      AUDIO_WS_RECONNECT_BASE_MS * (2 ** Math.min(reconnectAttempts, 4)),
    )
    reconnectAttempts += 1
    reportAudioMetric('audio_ws_reconnect_scheduled', {
      reason,
      reconnectAttempts,
      delay,
    })
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connectAudioWs(`reconnect:${reason}`)
    }, delay)
  }

  function connectAudioWs(reason = 'start') {
    if (!started) return
    if (
      audioWs &&
      (audioWs.readyState === WebSocket.OPEN || audioWs.readyState === WebSocket.CONNECTING)
    ) {
      return
    }
    const wsPath = `/ws-audio/${sessionId}`
    const url = buildWsUrl('backend', wsPath)
    const ws = new WebSocket(url)
    audioWs = ws
    ws.binaryType = 'arraybuffer'

    ws.addEventListener('error', (e) => {
      console.error('[AudioStream] WebSocket error', e)
      reportAudioMetric('audio_ws_error', { errorType: e?.type, reason })
    })
    ws.addEventListener('close', (event) => {
      console.log('[AudioStream] WebSocket closed', event.code, event.reason)
      reportAudioMetric('audio_ws_close', {
        code: event.code,
        reason: event.reason,
        wasClean: event.wasClean,
        connectReason: reason,
        shouldReconnect: started,
      })
      if (audioWs === ws) {
        audioWs = null
      }
      if (started) {
        scheduleAudioWsReconnect(`close:${event.code || 'unknown'}`)
      }
    })
    ws.addEventListener('open', () => {
      reconnectAttempts = 0
      reportAudioMetric('audio_ws_open', { reason })
    })
  }

  function start() {
    if (started) return
    started = true
    reportAudioMetric('audio_stream_start')
    connectAudioWs('start')

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
          buffers.length = 0
          if (
            started &&
            (!audioWs ||
              audioWs.readyState === WebSocket.CLOSING ||
              audioWs.readyState === WebSocket.CLOSED)
          ) {
            scheduleAudioWsReconnect('audio_process_without_open_ws')
          }
          return
        }
        if (audioWs.bufferedAmount > MAX_BUFFERED_BYTES) {
          droppedBuffered += 1
          buffers.length = 0
          return
        }

        const pcm = Recorder.SampleData(
          [buffers[buffers.length - 1]],
          bufferSampleRate,
          16000,
        ).data
        buffers.length = 0

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
        if (audioWs) {
          audioWs.close()
          audioWs = null
        }
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
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
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
