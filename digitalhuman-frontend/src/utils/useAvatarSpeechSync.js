import { queryAvatarSpeaking } from '@/api';

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

export function useAvatarSpeechSync() {
  async function isAvatarSpeaking() {
    const deviceid = localStorage.getItem('deviceid');

    try {
      const res = await queryAvatarSpeaking({ sessionid: deviceid });
      return !!(res && res.data);
    } catch (error) {
      console.warn('数字人说话查询接口查询失败~', error);
      return false;
    }
  }

  async function waitUntilSpeaking(signal, interval = 100) {
    while (!signal?.aborted) {
      if (await isAvatarSpeaking()) {
        return true;
      }
      await sleep(interval);
    }

    return false;
  }

  async function waitUntilSilent(signal, interval = 100) {
    while (!signal?.aborted) {
      if (!await isAvatarSpeaking()) {
        return true;
      }
      await sleep(interval);
    }

    return false;
  }

  return {
    isAvatarSpeaking,
    waitUntilSpeaking,
    waitUntilSilent,
  };
}

export default useAvatarSpeechSync;
