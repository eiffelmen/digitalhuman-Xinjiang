<script setup>
import { eventBus } from '@/api/session';
import { store } from '@/store/store';
import { nextTick, onMounted, onUnmounted, ref, defineEmits } from 'vue';
import { buildApiUrl, buildWsUrl } from '@/config';
import { getPublicUrl } from '@/utils/getAssets';
let pc = null;
let backendCloseSent = false;
let currentVideoStream = null;
let currentAudioStream = null;
let videoLoadedHandler = null;
let videoPlayingHandler = null;
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
	});
	videoElem.muted = false;
}
const loading = ref(true);
const poster = ref('');

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
		stop({ notifyBackend: true });
	}
	backendCloseSent = false;
	loading.value = true;
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
	// pc = new RTCPeerConnection();

	// connect audio / video
	peer.addEventListener('track', evt => {
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
			currentVideoStream = evt.streams[0];
			videoElem.srcObject = evt.streams[0];
			videoLoadedHandler = () => {
				nextTick(() => {
					loading.value = false;
				});
			};
			videoElem.addEventListener('loadedmetadata', videoLoadedHandler);

			// 监听视频真正开始播放的事件
			videoPlayingHandler = () => {
				console.log('Video is now playing');
				emit('videoReady', true);
			};
			videoElem.addEventListener('playing', videoPlayingHandler, { once: true });
		} else {
			const audioElem = document.getElementById('audio');
			if (!audioElem) return;
			if (currentAudioStream && currentAudioStream !== evt.streams[0]) {
				currentAudioStream.getTracks().forEach(track => track.stop());
			}
			currentAudioStream = evt.streams[0];
			audioElem.srcObject = evt.streams[0];
		}
	});
	peer.addEventListener('connectionstatechange', () => {
		if (pc !== peer) return;
		if (['failed', 'disconnected'].includes(peer.connectionState)) {
			stop({ notifyBackend: peer.connectionState === 'failed' });
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
		videoElem.pause();
		videoElem.srcObject = null;
	}
	const audioElem = document.getElementById('audio');
	if (audioElem) {
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
				return pc.setRemoteDescription(answer);
			})
			.catch(e => {
				// alert(e)
				console.log(e);
				console.log('negotiate error:', e);
				store.changeWebrtcStatus(false);
			})
	);
}

const beforeUnloadHandler = () => {
	console.log('webrtc closeing');
	stop({ notifyBackend: true });
};

const pageHideHandler = () => {
	stop({ notifyBackend: true });
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
});

onUnmounted(() => {
	window.removeEventListener('beforeunload', beforeUnloadHandler);
	window.removeEventListener('pagehide', pageHideHandler);
	stop({ notifyBackend: true });
});
</script>
<template>
	<div class="w-100 h-100 position-relative d-flex align-center justify-center">
		<video
			id="video"
			autoplay
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
