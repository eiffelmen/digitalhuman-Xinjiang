<script setup>
import { eventBus } from '@/api/session';
import { store } from '@/store/store';
import { nextTick, onMounted, onUnmounted, ref, defineEmits } from 'vue';
import { buildApiUrl, buildWsUrl } from '@/config';
import { getPublicUrl } from '@/utils/getAssets';
import { createClientDiagnostics } from '@/utils/clientDiagnostics';
const env = import.meta.env || {};
const WEBRTC_WATCHDOG_ENABLED = env.VITE_WEBRTC_WATCHDOG_ENABLED !== '0';
const WEBRTC_WATCHDOG_INTERVAL_MS = Math.max(
	3000,
	Number(env.VITE_WEBRTC_WATCHDOG_INTERVAL_MS || 5000)
);
const WEBRTC_NO_FRAME_TIMEOUT_MS = Math.max(
	10000,
	Number(env.VITE_WEBRTC_NO_FRAME_TIMEOUT_MS || 25000)
);
const WEBRTC_BAD_CONNECTION_TIMEOUT_MS = Math.max(
	3000,
	Number(env.VITE_WEBRTC_BAD_CONNECTION_TIMEOUT_MS || 8000)
);
const WEBRTC_RECONNECT_DELAY_MS = Math.max(
	500,
	Number(env.VITE_WEBRTC_RECONNECT_DELAY_MS || 1500)
);
const WEBRTC_MAX_RECONNECTS = Math.max(
	1,
	Number(env.VITE_WEBRTC_MAX_RECONNECTS || 8)
);
const WEBRTC_RELOAD_AFTER_RECONNECTS = env.VITE_WEBRTC_RELOAD_AFTER_RECONNECTS !== '0';
let pc = null;
let backendCloseSent = false;
let currentVideoStream = null;
let currentAudioStream = null;
let videoLoadedHandler = null;
let videoPlayingHandler = null;
let videoWaitingHandler = null;
let videoStalledHandler = null;
let videoErrorHandler = null;
let audioWaitingHandler = null;
let audioStalledHandler = null;
let diagnostics = null;
let watchdogTimer = null;
let reconnectTimer = null;
let reconnectInProgress = false;
let reconnectAttempts = 0;
let badConnectionSince = 0;
let lastGoodVideoAt = 0;
let lastVideoSnapshot = null;
let peerGeneration = 0;
defineExpose({
	getPoster,
	start,
	startPlayVideo,
	stop,
});

const emit = defineEmits(['offerSuccess', 'videoReady']);

function startPlayVideo() {
	const videoElem = document.getElementById('video');
	if (!videoElem) return;
	videoElem.play().catch(error => {
		console.error('Error playing video:', error);
		diagnostics?.mark('video_play_error', {
			name: error?.name,
			message: error?.message || String(error),
		});
	});
	videoElem.muted = false;
}
const loading = ref(true);
const poster = ref('');

function videoQualitySnapshot(videoElem) {
	if (!videoElem) return null;
	let decoded = null;
	let dropped = null;
	if (typeof videoElem.getVideoPlaybackQuality === 'function') {
		const quality = videoElem.getVideoPlaybackQuality();
		decoded = quality.totalVideoFrames;
		dropped = quality.droppedVideoFrames;
	} else {
		decoded = videoElem.webkitDecodedFrameCount;
		dropped = videoElem.webkitDroppedFrameCount;
	}
	return {
		at: Date.now(),
		currentTime: videoElem.currentTime || 0,
		decoded: Number.isFinite(decoded) ? decoded : null,
		dropped: Number.isFinite(dropped) ? dropped : null,
		readyState: videoElem.readyState,
		paused: videoElem.paused,
	};
}

function markVideoHealthy(reason = 'video_progress') {
	lastGoodVideoAt = Date.now();
	const videoElem = document.getElementById('video');
	lastVideoSnapshot = videoQualitySnapshot(videoElem);
	badConnectionSince = 0;
	if (reason === 'video_playing') {
		reconnectAttempts = 0;
	}
}

function clearWatchdogTimers({ clearReconnect = true } = {}) {
	if (watchdogTimer) {
		window.clearInterval(watchdogTimer);
		watchdogTimer = null;
	}
	if (clearReconnect && reconnectTimer) {
		window.clearTimeout(reconnectTimer);
		reconnectTimer = null;
	}
}

function scheduleReconnect(reason, extra = {}) {
	if (!WEBRTC_WATCHDOG_ENABLED || reconnectInProgress || reconnectTimer) return;
	if (!eventBus.sessionId) return;

	const nextAttempt = reconnectAttempts + 1;
	diagnostics?.mark('webrtc_reconnect_scheduled', {
		reason,
		attempt: nextAttempt,
		maxAttempts: WEBRTC_MAX_RECONNECTS,
		...extra,
	});

	if (nextAttempt > WEBRTC_MAX_RECONNECTS) {
		diagnostics?.mark('webrtc_watchdog_reload', {
			reason,
			attempt: nextAttempt,
			maxAttempts: WEBRTC_MAX_RECONNECTS,
		});
		if (WEBRTC_RELOAD_AFTER_RECONNECTS) {
			window.setTimeout(() => window.location.reload(), 500);
		}
		return;
	}

	reconnectAttempts = nextAttempt;
	reconnectTimer = window.setTimeout(() => {
		reconnectTimer = null;
		reconnectInProgress = true;
		diagnostics?.mark('webrtc_reconnect_start', {
			reason,
			attempt: reconnectAttempts,
			...extra,
		});
		stop({ notifyBackend: false });
		window.setTimeout(() => {
			try {
				start();
			} finally {
				reconnectInProgress = false;
			}
		}, WEBRTC_RECONNECT_DELAY_MS);
	}, 200);
}

function startWatchdog(peer) {
	if (!WEBRTC_WATCHDOG_ENABLED) return;
	clearWatchdogTimers({ clearReconnect: false });
	markVideoHealthy('watchdog_start');
	const generation = peerGeneration;

	watchdogTimer = window.setInterval(() => {
		if (generation !== peerGeneration || pc !== peer || !peer || peer.signalingState === 'closed') {
			clearWatchdogTimers({ clearReconnect: false });
			return;
		}
		if (document.hidden) {
			markVideoHealthy('document_hidden');
			return;
		}

		const nowMs = Date.now();
		const connectionState = peer.connectionState;
		const iceConnectionState = peer.iceConnectionState;
		const badConnection = ['failed', 'disconnected', 'closed'].includes(connectionState)
			|| ['failed', 'disconnected', 'closed'].includes(iceConnectionState);
		if (badConnection) {
			if (!badConnectionSince) badConnectionSince = nowMs;
			if (nowMs - badConnectionSince >= WEBRTC_BAD_CONNECTION_TIMEOUT_MS) {
				scheduleReconnect('bad_connection_state', {
					connectionState,
					iceConnectionState,
					badForMs: nowMs - badConnectionSince,
				});
			}
			return;
		}
		badConnectionSince = 0;

		const videoElem = document.getElementById('video');
		if (!videoElem || !videoElem.srcObject || videoElem.readyState < 2) {
			if (nowMs - lastGoodVideoAt >= WEBRTC_NO_FRAME_TIMEOUT_MS) {
				scheduleReconnect('video_not_ready', {
					readyState: videoElem?.readyState,
					hasSrcObject: Boolean(videoElem?.srcObject),
					noFrameMs: nowMs - lastGoodVideoAt,
				});
			}
			return;
		}

		const snapshot = videoQualitySnapshot(videoElem);
		const previous = lastVideoSnapshot;
		const decodedAdvanced =
			snapshot?.decoded !== null
			&& previous?.decoded !== null
			&& snapshot.decoded > previous.decoded;
		const timeAdvanced =
			typeof snapshot?.currentTime === 'number'
			&& typeof previous?.currentTime === 'number'
			&& snapshot.currentTime - previous.currentTime > 0.05;

		if (!videoElem.paused && (decodedAdvanced || timeAdvanced)) {
			markVideoHealthy('video_progress');
			return;
		}

		lastVideoSnapshot = snapshot;
		if (!videoElem.paused && nowMs - lastGoodVideoAt >= WEBRTC_NO_FRAME_TIMEOUT_MS) {
			scheduleReconnect('video_no_frame_progress', {
				noFrameMs: nowMs - lastGoodVideoAt,
				readyState: videoElem.readyState,
				currentTime: videoElem.currentTime,
				decoded: snapshot?.decoded,
				dropped: snapshot?.dropped,
			});
		}
	}, WEBRTC_WATCHDOG_INTERVAL_MS);
}

function getPoster() {
	return new Promise((resolve, reject) => {
		fetch(buildWsUrl('llm', '/image'))
			.then(response => {
				return response.json();
			})
			.then(data => {
				console.log(data);
				// return `data:image/png;base64,${base64Str}`

				poster.value = `data:image/png;base64,${data.image}`;
				resolve(poster.value);
			})
			.catch(err => {
				reject(err);
			});
	});
}

function start() {
	console.log('start eventBus.sessionId:', eventBus.sessionId);
	if (pc && pc.signalingState !== 'closed') {
		stop({ notifyBackend: !reconnectInProgress });
	}
	backendCloseSent = false;
	loading.value = true;
	peerGeneration += 1;
	var config = {
		sdpSemantics: 'unified-plan',
	};

	// config.iceServers = [{ urls: ['stun:stun.miwifi.com:3478'] }]
	// config.iceServers = [{ urls: ['stun:stun.yy.com:3478'] }]
/* 	config.iceServers = [
		{
		  urls: 'turn:media.example.com:3478',
		  username: 'admin',
		  credential: 'passwd123456'
		},
		// 保留STUN服务器作为备用
		{ urls: 'stun:stun.miwifi.com:3478' },
		{ urls: 'stun:stun.l.google.com:19302' }
    ]; */

	pc = new RTCPeerConnection(config);
	const peer = pc;
	diagnostics = createClientDiagnostics({
		sessionId: eventBus.sessionId,
		getPeerConnection: () => (pc === peer ? peer : null),
		getVideoElement: () => document.getElementById('video'),
		getAudioElement: () => document.getElementById('audio'),
	});
	diagnostics.start('webrtc_start');
	startWatchdog(peer);
	// pc = new RTCPeerConnection();

	peer.addEventListener('iceconnectionstatechange', () => {
		diagnostics?.mark('ice_connection_state_change', {
			iceConnectionState: peer.iceConnectionState,
		});
	});
	peer.addEventListener('icegatheringstatechange', () => {
		diagnostics?.mark('ice_gathering_state_change', {
			iceGatheringState: peer.iceGatheringState,
		});
	});
	peer.addEventListener('signalingstatechange', () => {
		diagnostics?.mark('signaling_state_change', {
			signalingState: peer.signalingState,
		});
	});

	// connect audio / video
	peer.addEventListener('track', evt => {
		diagnostics?.mark('track_received', {
			kind: evt.track.kind,
			trackId: evt.track.id,
			streamIds: evt.streams.map(stream => stream.id),
		});
		if (evt.track.kind === 'video') {
			const videoElem = document.getElementById('video');
			if (!videoElem) return;
			if (currentVideoStream && currentVideoStream !== evt.streams[0]) {
				currentVideoStream.getTracks().forEach(track => track.stop());
			}
			if (videoLoadedHandler) {
				videoElem.removeEventListener('loadedmetadata', videoLoadedHandler);
			}
			if (videoPlayingHandler) {
				videoElem.removeEventListener('playing', videoPlayingHandler);
			}
			if (videoWaitingHandler) {
				videoElem.removeEventListener('waiting', videoWaitingHandler);
			}
			if (videoStalledHandler) {
				videoElem.removeEventListener('stalled', videoStalledHandler);
			}
			if (videoErrorHandler) {
				videoElem.removeEventListener('error', videoErrorHandler);
			}
			currentVideoStream = evt.streams[0];
			videoElem.srcObject = evt.streams[0];
			videoLoadedHandler = () => {
				diagnostics?.mark('video_loadedmetadata', {
					videoWidth: videoElem.videoWidth,
					videoHeight: videoElem.videoHeight,
					readyState: videoElem.readyState,
				});
				markVideoHealthy('video_loadedmetadata');
				nextTick(() => {
					loading.value = false;
				});
			};
			videoElem.addEventListener('loadedmetadata', videoLoadedHandler);

			// 监听视频真正开始播放的事件
			videoPlayingHandler = () => {
				console.log('Video is now playing');
				diagnostics?.mark('video_playing', {
					videoWidth: videoElem.videoWidth,
					videoHeight: videoElem.videoHeight,
					readyState: videoElem.readyState,
				});
				markVideoHealthy('video_playing');
				emit('videoReady', true);
			};
			videoElem.addEventListener('playing', videoPlayingHandler, { once: true });
			videoWaitingHandler = () => {
				diagnostics?.mark('video_waiting', {
					currentTime: videoElem.currentTime,
					readyState: videoElem.readyState,
				});
			};
			videoStalledHandler = () => {
				diagnostics?.mark('video_stalled', {
					currentTime: videoElem.currentTime,
					readyState: videoElem.readyState,
				});
			};
			videoErrorHandler = () => {
				diagnostics?.mark('video_error', {
					errorCode: videoElem.error?.code,
					errorMessage: videoElem.error?.message,
				});
				scheduleReconnect('video_error_event', {
					errorCode: videoElem.error?.code,
					errorMessage: videoElem.error?.message,
				});
			};
			videoElem.addEventListener('waiting', videoWaitingHandler);
			videoElem.addEventListener('stalled', videoStalledHandler);
			videoElem.addEventListener('error', videoErrorHandler);
		} else {
			const audioElem = document.getElementById('audio');
			if (!audioElem) return;
			if (currentAudioStream && currentAudioStream !== evt.streams[0]) {
				currentAudioStream.getTracks().forEach(track => track.stop());
			}
			currentAudioStream = evt.streams[0];
			audioElem.srcObject = evt.streams[0];
			if (audioWaitingHandler) {
				audioElem.removeEventListener('waiting', audioWaitingHandler);
			}
			if (audioStalledHandler) {
				audioElem.removeEventListener('stalled', audioStalledHandler);
			}
			audioWaitingHandler = () => {
				diagnostics?.mark('audio_waiting', {
					currentTime: audioElem.currentTime,
					readyState: audioElem.readyState,
				});
			};
			audioStalledHandler = () => {
				diagnostics?.mark('audio_stalled', {
					currentTime: audioElem.currentTime,
					readyState: audioElem.readyState,
				});
			};
			audioElem.addEventListener('waiting', audioWaitingHandler);
			audioElem.addEventListener('stalled', audioStalledHandler);
		}
	});
	peer.addEventListener('connectionstatechange', () => {
		if (pc !== peer) return;
		diagnostics?.mark('connection_state_change', {
			connectionState: peer.connectionState,
		});
		if (peer.connectionState === 'connected') {
			markVideoHealthy('peer_connected');
		}
		if (peer.connectionState === 'failed') {
			scheduleReconnect('peer_connection_failed', {
				connectionState: peer.connectionState,
			});
		}
	});

	negotiate();
}

function notifyBackendClose() {
	const sessionid = eventBus.sessionId;
	if (!sessionid || backendCloseSent) return;
	backendCloseSent = true;

	const url = buildApiUrl('backend', '/close_session');
	const body = JSON.stringify({ sessionid });
	try {
		if (navigator.sendBeacon) {
			const blob = new Blob([body], { type: 'application/json' });
			if (navigator.sendBeacon(url, blob)) return;
		}
	} catch (e) {
		console.warn('sendBeacon close_session failed, fallback to fetch', e);
	}

	fetch(url, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body,
		keepalive: true,
	}).catch(e => console.warn('close_session failed', e));
}

function stop(options = {}) {
	const { notifyBackend = true } = options;
	diagnostics?.mark('webrtc_stop_requested', { notifyBackend });
	clearWatchdogTimers();
	if (diagnostics) {
		diagnostics.stop('webrtc_stop');
		diagnostics = null;
	}
	if (notifyBackend) {
		notifyBackendClose();
	}
	// close peer connection
	loading.value = false;
	try {
		if (pc) pc.close();
	} catch (e) {
		console.log(e);
	}
	const videoElem = document.getElementById('video');
	if (videoElem) {
		if (videoLoadedHandler) {
			videoElem.removeEventListener('loadedmetadata', videoLoadedHandler);
			videoLoadedHandler = null;
		}
		if (videoPlayingHandler) {
			videoElem.removeEventListener('playing', videoPlayingHandler);
			videoPlayingHandler = null;
		}
		if (videoWaitingHandler) {
			videoElem.removeEventListener('waiting', videoWaitingHandler);
			videoWaitingHandler = null;
		}
		if (videoStalledHandler) {
			videoElem.removeEventListener('stalled', videoStalledHandler);
			videoStalledHandler = null;
		}
		if (videoErrorHandler) {
			videoElem.removeEventListener('error', videoErrorHandler);
			videoErrorHandler = null;
		}
		videoElem.pause();
		videoElem.srcObject = null;
	}
	const audioElem = document.getElementById('audio');
	if (audioElem) {
		if (audioWaitingHandler) {
			audioElem.removeEventListener('waiting', audioWaitingHandler);
			audioWaitingHandler = null;
		}
		if (audioStalledHandler) {
			audioElem.removeEventListener('stalled', audioStalledHandler);
			audioStalledHandler = null;
		}
		audioElem.pause();
		audioElem.srcObject = null;
	}
	if (currentVideoStream) {
		currentVideoStream.getTracks().forEach(track => track.stop());
		currentVideoStream = null;
	}
	if (currentAudioStream) {
		currentAudioStream.getTracks().forEach(track => track.stop());
		currentAudioStream = null;
	}
	pc = null;
	lastVideoSnapshot = null;
	lastGoodVideoAt = 0;
	badConnectionSince = 0;
	console.log('webrtc closed');
	store.changeWebrtcStatus(false);
}

function negotiate() {
	// 添加收发器
	pc.addTransceiver('video', { direction: 'recvonly' });
	pc.addTransceiver('audio', { direction: 'recvonly' });
	return (
		pc
			// 创建并设置本地描述
			.createOffer()
			.then(offer => {
				console.log(offer);
				diagnostics?.mark('offer_created', {
					sdpLength: offer?.sdp?.length,
				});
				return pc.setLocalDescription(offer);
			})
			// 等待 ICE 聚集完成
			.then(() => {
				// wait for ICE gathering to complete
				return new Promise(resolve => {
					if (pc.iceGatheringState === 'complete') {
						resolve();
					} else {
						const checkState = () => {
							if (pc.iceGatheringState === 'complete') {
								console.log('webrtc connected');
								diagnostics?.mark('ice_gathering_complete');
								pc.removeEventListener('icegatheringstatechange', checkState);
								resolve();
							}
						};
						pc.addEventListener('icegatheringstatechange', checkState);
					}
				});
			})
			// 发送 offer 到服务器
			.then(() => {
				var offer = pc.localDescription;
				console.log('negotiate eventBus.sessionId:', eventBus.sessionId);
				diagnostics?.mark('offer_post_start', {
					sessionid: eventBus.sessionId,
					sdpLength: offer?.sdp?.length,
				});
				return fetch(buildApiUrl('backend', '/offer'), {
					body: JSON.stringify({
						sdp: offer.sdp,
						type: offer.type,
						// sessionid: getStore({ name: 'sessionId' }),
						sessionid: eventBus.sessionId,
					}),
					headers: {
						'Content-Type': 'application/json',
					},
					method: 'POST',
				});
			})
			.then(response => {
				if (!response.ok) {
					throw new Error(`Failed to send offer: ${response.statusText}`);
				} else {
					diagnostics?.mark('offer_post_success', {
						status: response.status,
					});
					emit('offerSuccess', true);
					return response;
				}
			})
			.then(response => {
				return response.json();
			})
			// 设置远程描述
			.then(answer => {
				// console.log('answer: ', answer)
				// 新增sessionid设置
				// setStore({ name: 'sessionId', content: answer.sessionid });
				// console.log('set seesionid is : ', answer.sessionid);
				// store.changeSessionId(answer.sessionid);
				// store.changeDigitalDefault(answer.config);
				// store.changeDigitalDefault({
				// 	digital_human_id: answer.config.avatar_id,
				// 	voice_type: answer.config.ref_file,
				// 	background_image: answer.config.bg_img,
				// });
				store.changeWebrtcStatus(true);
				markVideoHealthy('remote_description_set');
				diagnostics?.mark('remote_description_start', {
					answerType: answer?.type,
					sdpLength: answer?.sdp?.length,
					sessionid: answer?.sessionid,
				});
				return pc.setRemoteDescription(answer);
			})
			.catch(e => {
				// alert(e)
				console.log(e);
				console.log('negotiate error:', e);
				diagnostics?.mark('negotiate_error', {
					name: e?.name,
					message: e?.message || String(e),
				});
				store.changeWebrtcStatus(false);
				scheduleReconnect('negotiate_error', {
					name: e?.name,
					message: e?.message || String(e),
				});
			})
	);
}

const beforeUnloadHandler = () => {
	console.log('webrtc closeing');
	diagnostics?.mark('beforeunload');
	stop({ notifyBackend: true });
};

const pageHideHandler = () => {
	diagnostics?.mark('pagehide');
	stop({ notifyBackend: true });
};

const visibilityChangeHandler = () => {
	diagnostics?.mark('visibility_change', {
		visibilityState: document.visibilityState,
		hidden: document.hidden,
	});
	if (!document.hidden) {
		markVideoHealthy('document_visible');
	}
};

onMounted(() => {
	// start webrtc pull stream
	// try {
	//   start()
	// } catch (e) {
	//   console.log(e)
	//   store.changeWebrtcStatus(false)
	// }
	//getPoster()

	// 关闭网页后清理
	window.addEventListener('beforeunload', beforeUnloadHandler);
	window.addEventListener('pagehide', pageHideHandler);
	document.addEventListener('visibilitychange', visibilityChangeHandler);
});

onUnmounted(() => {
	window.removeEventListener('beforeunload', beforeUnloadHandler);
	window.removeEventListener('pagehide', pageHideHandler);
	document.removeEventListener('visibilitychange', visibilityChangeHandler);
	stop({ notifyBackend: true });
});
</script>
<template>
	<div class="w-100 h-100 position-relative d-flex align-center justify-center">
		<video
			id="video"
			autoplay
			playsinline
			:poster="poster"
		></video>
		<audio id="audio"></audio>
		<img
			v-if="loading"
			:src="getPublicUrl('/loading.png')"
			alt="alt text"
			class="loading-img position-absolute"
		/>
	</div>
</template>
<style scoped>
#video {
	background-color: gray;
	height: 100%;
	width: 100%;
	background: url(/video_bg2.jpg) no-repeat;
	background-size: 100% 100%;
	object-fit: fill;
}

@keyframes rotate {
	from {
		transform: rotate(0deg);
	}

	to {
		transform: rotate(360deg);
	}
}

.loading-img {
	width: 150px;
	height: 150px;
	animation: rotate 3s linear infinite;
}
</style>
