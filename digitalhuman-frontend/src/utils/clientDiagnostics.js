import { buildApiUrl } from '@/config';
import { store } from '@/store/store';

const env = import.meta.env || {};
const CLIENT_METRICS_ENABLED = env.VITE_CLIENT_METRICS_ENABLED !== '0';
const parsedClientMetricsInterval = Number(env.VITE_CLIENT_METRICS_INTERVAL_MS || 10000);
const CLIENT_METRICS_INTERVAL_MS = Number.isFinite(parsedClientMetricsInterval)
  ? Math.max(3000, parsedClientMetricsInterval)
  : 10000;
const CLIENT_METRICS_VERBOSE = env.VITE_CLIENT_METRICS_VERBOSE === '1';
const MODULE_STARTED_AT = performance.now();

function nowIso() {
  return new Date().toISOString();
}

function round(value, digits = 3) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return value;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function safeTimeRanges(ranges) {
  const result = [];
  if (!ranges) return result;
  for (let i = 0; i < Math.min(ranges.length, 4); i += 1) {
    try {
      result.push([round(ranges.start(i), 3), round(ranges.end(i), 3)]);
    } catch {
      break;
    }
  }
  return result;
}

function mediaElementSnapshot(el) {
  if (!el) return null;
  return {
    currentTime: round(el.currentTime, 3),
    duration: Number.isFinite(el.duration) ? round(el.duration, 3) : null,
    paused: el.paused,
    ended: el.ended,
    muted: el.muted,
    volume: round(el.volume, 2),
    playbackRate: round(el.playbackRate, 2),
    readyState: el.readyState,
    networkState: el.networkState,
    buffered: safeTimeRanges(el.buffered),
    seekable: safeTimeRanges(el.seekable),
    srcObjectTracks: el.srcObject
      ? el.srcObject.getTracks().map(track => ({
          kind: track.kind,
          id: track.id,
          label: track.label,
          enabled: track.enabled,
          muted: track.muted,
          readyState: track.readyState,
        }))
      : [],
  };
}

function videoSnapshot(video, state, elapsedMs) {
  const base = mediaElementSnapshot(video);
  if (!video) return base;

  let totalVideoFrames = null;
  let droppedVideoFrames = null;
  let corruptedVideoFrames = null;
  let qualityCreationTime = null;

  if (typeof video.getVideoPlaybackQuality === 'function') {
    const quality = video.getVideoPlaybackQuality();
    totalVideoFrames = quality.totalVideoFrames;
    droppedVideoFrames = quality.droppedVideoFrames;
    corruptedVideoFrames = quality.corruptedVideoFrames;
    qualityCreationTime = quality.creationTime;
  } else {
    totalVideoFrames = video.webkitDecodedFrameCount;
    droppedVideoFrames = video.webkitDroppedFrameCount;
  }

  const elapsedSec = Math.max(0.001, elapsedMs / 1000);
  const prev = state.prevVideo || {};
  const decodedDelta =
    typeof totalVideoFrames === 'number' && typeof prev.totalVideoFrames === 'number'
      ? totalVideoFrames - prev.totalVideoFrames
      : null;
  const droppedDelta =
    typeof droppedVideoFrames === 'number' && typeof prev.droppedVideoFrames === 'number'
      ? droppedVideoFrames - prev.droppedVideoFrames
      : null;
  const currentTimeDelta =
    typeof prev.currentTime === 'number' ? video.currentTime - prev.currentTime : null;

  const stalled =
    video.readyState >= 2 &&
    !video.paused &&
    decodedDelta === 0 &&
    currentTimeDelta !== null &&
    currentTimeDelta < 0.05;

  if (stalled) {
    state.stalledIntervals = (state.stalledIntervals || 0) + 1;
  }

  state.prevVideo = {
    totalVideoFrames,
    droppedVideoFrames,
    currentTime: video.currentTime,
  };

  return {
    ...base,
    videoWidth: video.videoWidth,
    videoHeight: video.videoHeight,
    clientWidth: video.clientWidth,
    clientHeight: video.clientHeight,
    totalVideoFrames,
    droppedVideoFrames,
    corruptedVideoFrames,
    qualityCreationTime,
    decodedDelta,
    droppedDelta,
    decodedFps: decodedDelta === null ? null : round(decodedDelta / elapsedSec, 2),
    droppedFps: droppedDelta === null ? null : round(droppedDelta / elapsedSec, 2),
    dropRatio:
      decodedDelta && decodedDelta > 0 && droppedDelta !== null
        ? round(droppedDelta / decodedDelta, 4)
        : null,
    currentTimeDelta: currentTimeDelta === null ? null : round(currentTimeDelta, 3),
    stalled,
    stalledIntervals: state.stalledIntervals || 0,
  };
}

function heapSnapshot() {
  const memory = performance?.memory;
  if (!memory) return null;
  return {
    usedJSHeapMB: round(memory.usedJSHeapSize / 1024 / 1024, 2),
    totalJSHeapMB: round(memory.totalJSHeapSize / 1024 / 1024, 2),
    jsHeapLimitMB: round(memory.jsHeapSizeLimit / 1024 / 1024, 2),
  };
}

function pageSnapshot(startedAt) {
  return {
    uptimeMs: Math.round(performance.now() - startedAt),
    visibilityState: document.visibilityState,
    hidden: document.hidden,
    focused: document.hasFocus(),
    online: navigator.onLine,
    location: window.location.href,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    },
    screen: {
      width: window.screen?.width,
      height: window.screen?.height,
      availWidth: window.screen?.availWidth,
      availHeight: window.screen?.availHeight,
    },
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency,
    heap: heapSnapshot(),
    store: {
      webrtcStatus: store.webrtcStatus,
      avatarSpeaking: store.avatarSpeaking,
      startRecord: store.startRecord,
      asrStatus: store.asrStatus,
      llmStatus: store.llmStatus,
    },
  };
}

function trackSnapshot(pc) {
  if (!pc) return [];
  return pc.getReceivers().map(receiver => {
    const track = receiver.track;
    return {
      kind: track?.kind,
      id: track?.id,
      label: track?.label,
      muted: track?.muted,
      enabled: track?.enabled,
      readyState: track?.readyState,
      transportState: receiver.transport?.state,
    };
  });
}

function pcSnapshot(pc) {
  if (!pc) return null;
  return {
    connectionState: pc.connectionState,
    iceConnectionState: pc.iceConnectionState,
    iceGatheringState: pc.iceGatheringState,
    signalingState: pc.signalingState,
    receivers: trackSnapshot(pc),
  };
}

function selectedCandidatePair(stats) {
  for (const report of stats.values()) {
    if (report.type === 'candidate-pair' && report.state === 'succeeded' && report.nominated) {
      return report;
    }
  }
  for (const report of stats.values()) {
    if (report.type === 'transport' && report.selectedCandidatePairId) {
      return stats.get(report.selectedCandidatePairId);
    }
  }
  return null;
}

function inboundSnapshot(report, state, elapsedSec) {
  const prev = state.prevStats.get(report.id);
  const bytesDelta =
    prev && typeof report.bytesReceived === 'number' && typeof prev.bytesReceived === 'number'
      ? report.bytesReceived - prev.bytesReceived
      : null;
  const packetsDelta =
    prev && typeof report.packetsReceived === 'number' && typeof prev.packetsReceived === 'number'
      ? report.packetsReceived - prev.packetsReceived
      : null;
  state.prevStats.set(report.id, {
    bytesReceived: report.bytesReceived,
    packetsReceived: report.packetsReceived,
  });
  if (state.prevStats.size > 100) {
    const keys = Array.from(state.prevStats.keys());
    for (let i = 0; i < keys.length - 50; i += 1) {
      state.prevStats.delete(keys[i]);
    }
  }

  return {
    id: report.id,
    kind: report.kind || report.mediaType,
    codecId: report.codecId,
    packetsReceived: report.packetsReceived,
    packetsLost: report.packetsLost,
    bytesReceived: report.bytesReceived,
    bitrateKbps: bytesDelta === null ? null : round((bytesDelta * 8) / elapsedSec / 1000, 2),
    packetsPerSecond: packetsDelta === null ? null : round(packetsDelta / elapsedSec, 2),
    jitter: round(report.jitter, 5),
    framesDecoded: report.framesDecoded,
    framesDropped: report.framesDropped,
    framesPerSecond: report.framesPerSecond,
    keyFramesDecoded: report.keyFramesDecoded,
    frameWidth: report.frameWidth,
    frameHeight: report.frameHeight,
    freezeCount: report.freezeCount,
    pauseCount: report.pauseCount,
    totalFreezesDuration: round(report.totalFreezesDuration, 3),
    totalPausesDuration: round(report.totalPausesDuration, 3),
    totalDecodeTime: round(report.totalDecodeTime, 3),
    totalInterFrameDelay: round(report.totalInterFrameDelay, 3),
    jitterBufferDelay: round(report.jitterBufferDelay, 3),
    jitterBufferEmittedCount: report.jitterBufferEmittedCount,
    nackCount: report.nackCount,
    pliCount: report.pliCount,
    firCount: report.firCount,
  };
}

async function rtcStatsSnapshot(pc, state, elapsedMs) {
  if (!pc || typeof pc.getStats !== 'function') return null;
  const elapsedSec = Math.max(0.001, elapsedMs / 1000);
  const stats = await pc.getStats();
  const inbound = [];
  let candidatePair = null;

  stats.forEach(report => {
    if (report.type === 'inbound-rtp' && !report.isRemote) {
      inbound.push(inboundSnapshot(report, state, elapsedSec));
    }
  });

  const pair = selectedCandidatePair(stats);
  if (pair) {
    candidatePair = {
      id: pair.id,
      currentRoundTripTime: round(pair.currentRoundTripTime, 4),
      availableIncomingBitrate: pair.availableIncomingBitrate,
      availableOutgoingBitrate: pair.availableOutgoingBitrate,
      bytesReceived: pair.bytesReceived,
      bytesSent: pair.bytesSent,
      packetsReceived: pair.packetsReceived,
      packetsSent: pair.packetsSent,
      requestsReceived: pair.requestsReceived,
      responsesReceived: pair.responsesReceived,
      consentRequestsSent: pair.consentRequestsSent,
    };
  }

  return { inbound, candidatePair };
}

function compactError(error) {
  return {
    name: error?.name,
    message: error?.message || String(error),
    stack: CLIENT_METRICS_VERBOSE ? error?.stack : undefined,
  };
}

function compactReason(reason) {
  if (reason instanceof Error) return compactError(reason);
  if (reason && typeof reason === 'object') {
    return {
      name: reason.name,
      message: reason.message || JSON.stringify(reason).slice(0, 800),
      stack: CLIENT_METRICS_VERBOSE ? reason.stack : undefined,
    };
  }
  return {
    message: String(reason),
  };
}

function sendClientMetricsPayload(payload) {
  if (!CLIENT_METRICS_ENABLED) return;
  const body = JSON.stringify(payload);
  const url = buildApiUrl('backend', '/client_metrics');
  try {
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: body.length < 60000,
    }).catch(error => {
      if (CLIENT_METRICS_VERBOSE) {
        console.warn('[CLIENT_METRICS] send failed', error);
      }
    });
  } catch (error) {
    if (CLIENT_METRICS_VERBOSE) {
      console.warn('[CLIENT_METRICS] send error', error);
    }
  }
}

export function postClientDiagnosticEvent(event, { sessionId, extra = {} } = {}) {
  sendClientMetricsPayload({
    type: 'client_event',
    event,
    timestamp: nowIso(),
    sessionid: sessionId,
    page: pageSnapshot(MODULE_STARTED_AT),
    extra,
  });
}

let globalDiagnosticsInstalled = false;

export function installGlobalClientDiagnostics() {
  if (globalDiagnosticsInstalled || typeof window === 'undefined') return;
  globalDiagnosticsInstalled = true;

  window.addEventListener('error', event => {
    postClientDiagnosticEvent('window_error', {
      extra: {
        message: event.message,
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
        error: compactError(event.error),
      },
    });
  });

  window.addEventListener('unhandledrejection', event => {
    postClientDiagnosticEvent('unhandled_rejection', {
      extra: {
        reason: compactReason(event.reason),
      },
    });
  });

  window.addEventListener('online', () => {
    postClientDiagnosticEvent('browser_online');
  });

  window.addEventListener('offline', () => {
    postClientDiagnosticEvent('browser_offline');
  });

  window.addEventListener('pageshow', event => {
    postClientDiagnosticEvent('pageshow', {
      extra: {
        persisted: event.persisted,
      },
    });
  });

  window.addEventListener('pagehide', event => {
    postClientDiagnosticEvent('pagehide_global', {
      extra: {
        persisted: event.persisted,
      },
    });
  });

  document.addEventListener('visibilitychange', () => {
    postClientDiagnosticEvent('visibility_change_global', {
      extra: {
        visibilityState: document.visibilityState,
        hidden: document.hidden,
      },
    });
  });

  document.addEventListener('freeze', () => {
    postClientDiagnosticEvent('page_freeze');
  });

  document.addEventListener('resume', () => {
    postClientDiagnosticEvent('page_resume');
  });
}

export function createClientDiagnostics({
  sessionId,
  getPeerConnection,
  getVideoElement,
  getAudioElement,
}) {
  const pageId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  const startedAt = performance.now();
  const state = {
    seq: 0,
    prevAt: performance.now(),
    prevStats: new Map(),
    prevVideo: null,
    stalledIntervals: 0,
    timer: null,
    stopped: false,
  };

  async function collect(event = 'interval', extra = {}) {
    if (!CLIENT_METRICS_ENABLED || state.stopped) return;
    const nowMs = performance.now();
    const elapsedMs = Math.max(1, nowMs - state.prevAt);
    state.prevAt = nowMs;

    const pc = getPeerConnection?.();
    const video = getVideoElement?.();
    const audio = getAudioElement?.();
    const payload = {
      type: 'client_metrics',
      event,
      timestamp: nowIso(),
      pageId,
      seq: ++state.seq,
      sessionid: sessionId,
      extra,
      page: pageSnapshot(startedAt),
      peerConnection: pcSnapshot(pc),
      video: videoSnapshot(video, state, elapsedMs),
      audio: mediaElementSnapshot(audio),
      rtcStats: null,
    };

    try {
      payload.rtcStats = await rtcStatsSnapshot(pc, state, elapsedMs);
    } catch (error) {
      payload.rtcStatsError = compactError(error);
    }

    send(payload);
  }

  function send(payload) {
    sendClientMetricsPayload(payload);
  }

  function start(reason = 'start') {
    if (!CLIENT_METRICS_ENABLED || state.timer) return;
    collect(reason);
    state.timer = window.setInterval(() => collect('interval'), CLIENT_METRICS_INTERVAL_MS);
  }

  function stop(reason = 'stop') {
    if (state.stopped) return;
    if (state.timer) {
      window.clearInterval(state.timer);
      state.timer = null;
    }
    collect(reason);
    state.stopped = true;
  }

  function mark(event, extra = {}) {
    collect(event, extra);
  }

  return { start, stop, mark };
}
