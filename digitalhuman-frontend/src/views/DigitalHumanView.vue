<script setup>
import CustomDesign from '@/components/CustomDesign.vue';
import DetailDiv from '@/components/DetailDiv.vue';
import VideoDiv from '@/components/VideoDiv.vue';
import { store } from '@/store/store';
import { getPublicUrl } from '@/utils/getAssets';
import { getStore, setStore } from '@/utils/store';
import {nextTick, onMounted, onUnmounted, ref} from 'vue';
import { eventBus } from '@/api/session';
import ChatLog from '@/components/ChatLog.vue';
import ChatQuestion from '@/components/ChatQuestion.vue';
import { v4 as uuidv4 } from 'uuid';
import { digitalHumanSay } from '@/api';
import { buildWsUrl, buildApiUrl } from '@/config';
import { WebSocketManager } from '@/utils/websocket';
import { useAudioStream } from '@/composables/useAudioStream.js';

// 使用 buildApiUrl 构建完整的 API URL(Electron 环境下)
const adVideoSrc = buildApiUrl('main', '/static/反诈视频.mp4');
const sessionId = ref('');
let stopAudioStream = null;
let speakingPollTimer = null;

function startSpeakingPoll(sessionid) {
	speakingPollTimer = setInterval(async () => {
		try {
			const res = await fetch(buildApiUrl('backend', '/is_speaking'), {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ sessionid }),
			})
			const data = await res.json()
			store.changeAvatarSpeaking(data.data === true)
		} catch (e) {
			// 网络抖动不影响主流程
		}
	}, 1000)
}

function stopSpeakingPoll() {
	if (speakingPollTimer) {
		clearInterval(speakingPollTimer)
		speakingPollTimer = null
	}
}
const showDetail = ref(false);
const showDiv = ref(false);
const videoDivRef = ref(null);
const loading = ref(false);
const chatRef = ref(null);
const chatQuestionRef = ref(null);
const changeType = ref('形象');

const currentWorkStata = ref('work');

// 是否为待机模式
const isStandby = ref(false);
// 是否展示人名字
const showName = ref(false);
// 是否展示待机图像
const showStandby = ref(false);
// 视频是否已就绪（WebRTC流加载完成并正常播放）
const isVideoReady = ref(false);
// 安卓检测WebSocket管理器
let androidSocketManager = null;
let electronFaceUnsubscribe = null;

// 视频就绪处理函数
function handleVideoReady() {
	console.log('视频流已就绪');
	isVideoReady.value = true;
	showName.value = true;
}

// 供安卓 WebView 调用的人脸状态处理函数（始终对话模式：忽略所有休眠信号）
function handleFaceStatus(status) {
	if (status === 'sleep') return;
}

function initElectronFaceListener() {
	if (window.electronAPI && typeof window.electronAPI.onFaceData === 'function') {
		electronFaceUnsubscribe = window.electronAPI.onFaceData(payload => {
			const hasFace = Array.isArray(payload?.faces) && payload.faces.length > 0;
			handleFaceStatus(hasFace ? 'work' : 'sleep');
		});
	}
}

const keyDown = e => {
	const keyName = e.key;
	if (keyName === 'd') {
		showDetail.value = !showDetail.value;
		console.log('change detail view');
	}
};
let hasUserGesture = false;
function handleFirstUserGesture() {
	if (!hasUserGesture) {
		hasUserGesture = true;
		initAudioContext();
	}
}
function initAudioContext() {
	if (hasUserGesture) {
		store.changeStartRecord(true);
		// 进行音频相关的初始化操作
		console.log('AudioContext initialized after first user gesture.');
	}
}
// todo: 去掉？
function recordChange(type) {
	if (!hasUserGesture) {
		handleFirstUserGesture();
	} else {
		if (type === 'end') {
			// store.changeStartRecord(false)
			// store.changeAsrStatus(false)
		} else {
			// store.changeAsrStatus(true)
			// store.changeStartRecord(true)
		}
	}
}

function handleUserPress() {
	// toggleFullScreen();
	videoDivRef.value.startPlayVideo();

	const adVideoElem = document.getElementById('ad-video');
	if (adVideoElem) {
		adVideoElem.muted = false;
	}
}
function toggleFullScreen() {
	if (!document.fullscreenElement) {
		document.documentElement.requestFullscreen();
	} else if (document.exitFullscreen) {
		document.exitFullscreen();
	}
}

/**
 * 用户问候功能
 * @param {string} message - 问候消息
 * @returns {Promise<void>}
 */
async function greetUser(message) {
  await digitalHumanSay(message);
}

// 上报设备ID
function handleReportDeviceId() {
	try {
		eventBus.sessionId = localStorage.getItem('deviceid');
		videoDivRef.value.start();
	} catch(error) {
		console.log("handleReportDeviceId-error:", error);
	}
}

// 初始化内容返回websocket，offer 成功即自动打招呼
async function handleInitChatWebSocket() {
	chatRef.value.initFn();
	await greetUser('你好，有什么可以帮助您的。').catch(
		error => console.error('打招呼失败:', error)
	);
	// offer 成功后后端已有 nerfreal 实例，启动持续录音 + 说话状态轮询
	const { start, stop } = useAudioStream(eventBus.sessionId);
	stopAudioStream = stop;
	start();
	startSpeakingPoll(eventBus.sessionId);
}

// 初始化socket检测，接收安卓信息
function handleInitSocket() {
	const deviceid = localStorage.getItem('deviceid');

	// 使用配置文件构建WebSocket URL
	const wsUrl = buildWsUrl('main', `/ws?type=web&id=${deviceid}`);

	console.log('WebSocket连接URL:', wsUrl);

	// 使用WebSocketManager管理连接
	androidSocketManager = new WebSocketManager(wsUrl, {
		heartbeatInterval: 5000,
		heartbeatTimeout: 10000,
		reconnectDelay: 3000,
		maxReconnectAttempts: 5,
		onOpen: () => {
			console.log('WebSocket连接成功，开始心跳机制');
		},
		onMessage: async (data) => {
			// 这里接收安卓端的消息，检测到有人脸信息，就将数字人从右上角的小窗放大到全屏，并开始睡眠倒计时
			if (data.data === 'work') {
				// handleToggleDialogueMode();
        handleFaceStatus('work')
				chatRef.value.startStandbyTimer();
			}
		},
		onClose: () => {
			console.log('WebSocket连接关闭');
		},
		onError: (error) => {
			console.log('WebSocket连接错误:', error);
		},
		onReconnect: (attempts) => {
			console.log(`正在重连WebSocket (第${attempts}次)...`);
		},
	});

	androidSocketManager.connect();
}

// 对话结束（始终对话模式：无需切回待机）
function handleMessageClose() {
}

function designSuccess() {
	showDiv.value = false;
	chatRef.value.resetChat();
}

function notifyAndroidReadyToRecv() {
	window.DeviceBridge.readyToRecv();
}

function initChatQuestionWebSocket() {
	if (
		chatQuestionRef.value &&
		typeof chatQuestionRef.value.initAsrWebSocket === 'function'
	) {
		chatQuestionRef.value.initAsrWebSocket();
	}
}

onMounted(async () => {
	// 暴露全局方法给安卓 WebView 调用
	window.handleFaceStatus = handleFaceStatus;
	// 检查Electron接口是否可用
	if (window.electronAPI && typeof window.electronAPI.getDeviceId === 'function') {
		// Electron环境，使用Electron API获取设备ID
		window.electronAPI.getDeviceId().then(deviceId => {
			if (deviceId) {
				localStorage.setItem('deviceid', deviceId);
				console.log('Electron设备ID:', deviceId);
			} else {
				throw new Error('获取Electron设备ID失败');
			}
		}).catch(error => {
			console.error('Electron获取设备ID异常:', error);
			// 使用UUID作为后备方案
			const uuid = uuidv4();
			localStorage.setItem('deviceid', uuid);
			console.log('使用UUID作为deviceid:', uuid);
		});
	} else if (window.DeviceBridge && typeof DeviceBridge.getDeviceId === 'function') {
		// Android环境，获取设备ID
		const deviceId = DeviceBridge.getDeviceId();
		localStorage.setItem('deviceid', deviceId);
		console.log('Android设备ID:', deviceId);
	} else {
		// 浏览器环境，使用UUID
		console.warn('非Electron/Android环境，使用UUID生成设备ID');
		const uuid = uuidv4();
		localStorage.setItem('deviceid', uuid);
		console.log('Browser deviceid:', uuid);
	}

	window.addEventListener('keydown', keyDown);
	const defualtHuman = getStore({ name: 'digitalDefault' });
	if (!defualtHuman) {
		setStore({
			name: 'digitalDefault',
			content: {
				digital_human_id: 1,
				voice_type: 1,
				background_image: 2,
			},
		});
	}

	await nextTick();
	initChatQuestionWebSocket();
	handleInitSocket();
	handleReportDeviceId();
	initElectronFaceListener();

	// notifyAndroidReadyToRecv();

});

onUnmounted(() => {
	window.removeEventListener('keydown', keyDown);
	sessionId.value = '';
	if (stopAudioStream) {
		stopAudioStream();
		stopAudioStream = null;
	}
	stopSpeakingPoll();
	store.changeAvatarSpeaking(false);
	// 清理WebSocket连接
	if (androidSocketManager) {
		androidSocketManager.close();
		androidSocketManager = null;
	}
	if (typeof electronFaceUnsubscribe === 'function') {
		electronFaceUnsubscribe();
		electronFaceUnsubscribe = null;
	}
	// 清理全局方法
	if (window.handleFaceStatus) {
		delete window.handleFaceStatus;
	}
});
</script>

<template>
	<div
		id="media"
		@click="handleUserPress()"
		class="w-100 h-100 overflow-hidden position-relative d-flex"
	>
		<audio autoplay></audio>
		<div class="h-100 overflow-hidden position-relative left-box-video">
			<!-- AI视频 -->
			<div :class="isStandby ? 'standby-video-content' : 'video-content'">
				<VideoDiv
					ref="videoDivRef"
					@offerSuccess="handleInitChatWebSocket"
					@videoReady="handleVideoReady"
				/>
			</div>

			<!-- 人名框 -->
			<div v-if="showName">
				<img
					:src="getPublicUrl('/name.png')"
					class="position-absolute"
					style="
						top: 200px;
						right: 130px;
						transform: translateX(-50%);
						width: 40px;
						height: auto;
					"
				/>
			</div>
			<!-- 右侧对话框 -->
			<div class="position-absolute chat-quesiton">
				<ChatQuestion
					ref="chatQuestionRef"
				/>
			</div>

			<!-- 文本对话框 -->
			<div class="position-absolute chat-log">
				<ChatLog
					ref="chatRef"
					@close="handleMessageClose"
					@recordChange="val => recordChange(val)"
					@asr-result="val => chatQuestionRef?.showAsrResult(val)"
				/>
			</div>

			<v-overlay
				class="align-center justify-center"
				:close-on-content-click="false"
				v-model="loading"
				contained
			>
				<span class="loading-tips">{{ changeType }}切换中，请稍后...</span>
			</v-overlay>
		</div>

		<div
			class="position-absolute right-0 top-0 bg-black opacity-70"
			style="width: 100%; height: 30%; font-size: 10rem;z-index: 999;"
			v-if="showDetail"
		>
			<DetailDiv />
		</div>
		<div
			v-if="showDiv"
			class="position-fixed right-0 top-0 w-100 h-100"
		>
			<CustomDesign
				@back="showDiv = false"
				@success="designSuccess()"
			/>
		</div>

		<!-- 待机图片与视频 -->
		<div
			v-if="showStandby"
			class="standby-bg-wrapper"
		>
			<div class="standby-bg-content">
				<!-- <img
					src="@/assets/imgs/demo.jpeg"
					class="camera-image"
				/> -->
				<!-- todo: http://media.example.com:8000/static/反诈视频.mp4 -->
				<video id="ad-video" class="camera-image" :src="adVideoSrc" autoplay loop></video>
			</div>
		</div>

		<div v-if="!showStandby">
			<img :src="getPublicUrl('/bottom_info.png')" class="position-absolute bottom-info" />
		</div>

		<!-- 待机人像 -->
		<div
			v-if="showStandby"
			class="standby-camera-video-content"
		></div>

		<div :style="`background-image: url('${getPublicUrl('/version_bg.png')}'); background-size: 100% 100%;`" class="version-content">Version 3.0.2</div>
	</div>
</template>

<style scoped>
#media {
	background-repeat: no-repeat;
	background-size: 100% 100%;
	background-image: url(/video_bg2.jpg);
}

.left-box-video {
	/* width: 739px; */
	width: 100vw;
	height: 100vh;
}

.standby-camera-video-content {
	position: absolute;
	width: 364px;
	height: 573px;
	top: 100px;
	right: 132px;
	padding: 8px;
	overflow: hidden;
	background-size: 100% 100%;
	background-image: url(/standby-camera.png);
}

.standby-bg-wrapper {
	width: 100%;
	height: 2116px;
	padding: 0 132px;
	position: absolute;
	bottom: 258px;

	.standby-bg-content {
		width: 100%;
		height: 100%;
		padding: 44px 42px;
		background-size: 100% 100%;
		background-image: url(/standby-bg.png);

		.camera-image {
			width: 100%;
			height: 100%;
			margin: 0;
			padding: 0;
		}
	}
}

.standby-video-content {
	position: fixed;
	width: 364px;
	height: 573px;
	top: 100px;
	right: 132px;
	transition: all 0.5s ease-in-out;
	transform-origin: right top;
}

.video-content {
	position: absolute;
	width: 100%;
	height: 100%;
	top: 0;
	right: 0;
	transition: all 0.5s ease-in-out;
}

.chat-log {
	width: min(84vw, 960px, 52vh);
	aspect-ratio: 1707 / 1318;
	top: 56vh !important;
	left: 50%;
	transform: translateX(-50%);
	z-index: 30;
	pointer-events: none;
}

.bottom-info {
	bottom: 60px;
	left: 0;
	width: 100%;
	height: auto;
	z-index: 10;
	pointer-events: none;
}
.chat-quesiton{
	height: 320px;
	width: 1164px;
	top: 1100px !important;
	right: 230px !important;
}

.loading-tips {
	font-size: 32px;
	font-weight: bold;
}

.version-content {
	position: fixed;
	height: 60px;
	right: 60px;
	bottom: 36px;
	font-size: 46px;
	color: #012557;
	padding: 0 24px;
	line-height: 60px;
}
</style>
