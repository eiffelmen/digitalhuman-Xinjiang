import Recorder from 'recorder-core'
import 'recorder-core/src/engine/pcm'
import { buildWsUrl, buildApiUrl } from '@/config/index.js'
import { store } from '@/store/store.js'

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
  const MAX_BUFFERED_BYTES = 256 * 1024

  function start() {
    if (started) return
    started = true

    const wsPath = `/ws-audio/${sessionId}`
    const url = buildWsUrl('backend', wsPath)
    audioWs = new WebSocket(url)
    audioWs.binaryType = 'arraybuffer'

    audioWs.addEventListener('error', (e) => {
      console.error('[AudioStream] WebSocket error', e)
    })
    audioWs.addEventListener('close', () => {
      console.log('[AudioStream] WebSocket closed')
    })

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
        if (!started || !audioWs || audioWs.readyState !== WebSocket.OPEN) return
        if (audioWs.bufferedAmount > MAX_BUFFERED_BYTES) return

        const pcm = Recorder.SampleData(
          [buffers[buffers.length - 1]],
          bufferSampleRate,
          16000,
        ).data

        // 数字人正在说话时：检测到较大音量才触发打断，再送 ASR
        if (powerLevel > 20 && store.avatarSpeaking && !interruptCooling) {
          interruptCooling = true
          callInterrupt(sessionId).finally(() => {
            interruptCoolingTimer = setTimeout(() => {
              interruptCooling = false
              interruptCoolingTimer = null
            }, 500)
          })
        }

        // 所有帧都发给后端，由 VAD 状态机判断语音起止
        audioWs.send(pcm.buffer)
      },
    })

    rec.open(
      () => {
        console.log('[AudioStream] mic opened with AEC, starting continuous recording')
        rec.start()
      },
      (msg, isUserNotAllow) => {
        console.error(
          '[AudioStream] mic open failed:',
          isUserNotAllow ? '用户拒绝麦克风权限' : msg,
        )
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
