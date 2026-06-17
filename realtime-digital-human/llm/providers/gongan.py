import asyncio
import json
import os
import re
import time
import uuid
from typing import Callable, Optional

from loguru import logger

from basereal import BaseReal
from gongan_api import env_bool, env_float, get_gongan_client
from perf_logger import elapsed_ms, log_perf, log_timepoint, now


PUNCTUATION_RE = re.compile(r"[，。！？：；、,.!?;:\n]")


def _find_last_punct(text: str) -> int:
    last_punct = -1
    for mark in "，。！？：；、,.!?;:\n":
        pos = text.rfind(mark)
        if pos > last_punct:
            last_punct = pos
    return last_punct


def _clean_chunk(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return text.translate(str.maketrans("", "", "*#-")).strip()


def _build_query(message: str) -> str:
    instruction = os.environ.get(
        "GONGAN_REPLY_INSTRUCTION",
        "请用简洁、口语化中文回答，控制在80字以内，适合数字人口播。不要输出思考过程。",
    ).strip()
    if not instruction:
        return message
    return f"{instruction}\n用户问题：{message}"


def _extract_answer(data) -> str:
    if not isinstance(data, dict):
        return ""
    if "answer" in data:
        answer = data.get("answer")
        return answer if isinstance(answer, str) else ""
    nested = data.get("data")
    if isinstance(nested, dict):
        answer = nested.get("answer") or nested.get("content")
        return answer if isinstance(answer, str) else ""
    content = data.get("content")
    return content if isinstance(content, str) else ""


def _make_tts_sender(
    nerfreal: BaseReal,
    trace_id: Optional[str] = None,
) -> tuple[Callable[[str], None], Callable[[], None]]:
    tts = getattr(nerfreal, "tts", None)
    direct_tts = env_bool("GONGAN_DIRECT_TTS", True)
    stream = None
    segment_index = 0
    stream_start = now()

    if direct_tts and hasattr(tts, "start_text_stream"):
        try:
            stream = tts.start_text_stream()
            logger.info(f"Gongan LLM direct TTS stream started trace_id={trace_id}")
            log_perf(
                "tts",
                "direct_stream_start",
                elapsed_ms(stream_start),
                trace_id=trace_id,
                direct_tts=True,
            )
        except Exception as exc:
            logger.warning(
                f"Gongan direct TTS unavailable, fallback to queue trace_id={trace_id}: {exc}"
            )
            stream = None

    def send(text: str) -> None:
        nonlocal segment_index
        clean_text = text.strip()
        if not clean_text:
            return
        segment_index += 1
        is_active = getattr(nerfreal, "is_active_chat_trace", None)
        if trace_id and callable(is_active) and not is_active(trace_id):
            logger.info(
                f"Skip stale Gongan TTS segment trace_id={trace_id}, "
                f"segment_index={segment_index}, len={len(clean_text)}"
            )
            return
        log_timepoint(
            "TTS",
            "LLM文本段进入TTS",
            trace_id=trace_id,
            segment_index=segment_index,
            text_len=len(clean_text),
            direct_tts=stream is not None,
            first_char=clean_text[:1],
        )
        log_perf(
            "trace",
            "tts_segment_dispatch",
            trace_id=trace_id,
            segment_index=segment_index,
            text_len=len(clean_text),
            direct_tts=stream is not None,
        )
        if stream is not None:
            if hasattr(nerfreal, "set_active_tts_trace"):
                nerfreal.set_active_tts_trace(trace_id, segment_index)
            stream.send_text(clean_text)
        else:
            nerfreal.put_msg_txt(
                clean_text,
                trace_id=trace_id,
                segment_index=segment_index,
            )

    def finish() -> None:
        if stream is not None:
            stream.finish()
        if hasattr(nerfreal, "clear_active_tts_trace"):
            nerfreal.clear_active_tts_trace()

    return send, finish


def llm_response(
    message: str,
    nerfreal: BaseReal,
    sessionid: str,
    result_queue: asyncio.Queue,
    trace_id: Optional[str] = None,
) -> str:
    start_time = time.perf_counter()
    first_token_received = False
    msg_id = trace_id or str(uuid.uuid4())
    trace_id = msg_id
    client = get_gongan_client()
    complete_response: list[str] = []
    tts_buffer = ""
    chunk_count = 0
    tts_segments_queued = 0
    response = None
    min_segment_len = int(os.environ.get("GONGAN_TTS_MIN_SEGMENT_LEN", "12"))
    max_segment_len = int(os.environ.get("GONGAN_TTS_MAX_SEGMENT_LEN", "80"))
    read_timeout = env_float("GONGAN_LLM_READ_TIMEOUT", 60.0)
    send_tts, finish_tts = _make_tts_sender(nerfreal, trace_id=trace_id)

    def queue_tts(text: str) -> None:
        nonlocal tts_segments_queued
        tts_segments_queued += 1
        logger.info(
            f"Gongan TTS segment queued trace_id={msg_id}, "
            f"segment_index={tts_segments_queued}, text={text[:30]!r}, len={len(text)}"
        )
        log_perf(
            "llm",
            "queue_tts_segment",
            trace_id=msg_id,
            segment_index=tts_segments_queued,
            text_len=len(text),
            total_answer_len=sum(len(part) for part in complete_response),
        )
        send_tts(text)

    try:
        client.ensure_ready()
        url = f"{client.base_url}/aichat/chat/query"
        payload = {
            "query": _build_query(message),
            "history": [],
            "stream": True,
            "startFlag": 0,
            "groupId": None,
            "useTmp": 0,
            "kb_ids": [],
            "file_names": [],
            "is_only_specialized": False,
            "modelId": client.ensure_model_id(),
            "isBoot": "1",
        }

        logger.info(
            f"Start receiving Gongan LLM stream trace_id={msg_id}, "
            f"sessionid={sessionid}, text_len={len(message)}, read_timeout={read_timeout}"
        )
        log_timepoint(
            "LLM",
            "请求公安大模型",
            trace_id=msg_id,
            sessionid=sessionid,
            text_len=len(message),
            model=payload.get("modelId"),
        )
        post_start = now()
        response = client.session.post(
            url,
            json=payload,
            headers=client.sse_headers(),
            stream=True,
            timeout=(client.timeout, read_timeout),
        )
        log_perf(
            "llm",
            "http_post",
            elapsed_ms(post_start),
            trace_id=msg_id,
            sessionid=sessionid,
            status_code=getattr(response, "status_code", None),
        )
        header_start = now()
        response.raise_for_status()
        log_perf(
            "llm",
            "http_headers_ready",
            elapsed_ms(header_start),
            trace_id=msg_id,
            sessionid=sessionid,
            status_code=getattr(response, "status_code", None),
        )

        for raw_line in response.iter_lines(decode_unicode=True):
            is_active = getattr(nerfreal, "is_active_chat_trace", None)
            if trace_id and callable(is_active) and not is_active(trace_id):
                logger.info(
                    f"停止处理已失效的公安LLM响应 trace_id={trace_id}, "
                    f"chunks={chunk_count}, answer_len={sum(len(part) for part in complete_response)}"
                )
                return None
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                raw_line = raw_line.decode("utf-8", errors="ignore")
            line = raw_line.strip()
            if line.startswith(("event:", "id:", "retry:")):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.debug(f"Gongan LLM ignored non-JSON SSE line: {line[:120]!r}")
                continue

            chunk = _clean_chunk(_extract_answer(data))
            if not chunk:
                continue

            if not first_token_received:
                first_token_received = True
                first_token_ms = (time.perf_counter() - start_time) * 1000
                logger.info(
                    f"Gongan LLM first token trace_id={msg_id}: "
                    f"{first_token_ms / 1000:.2f}s"
                )
                log_timepoint(
                    "LLM",
                    "流式首token输出",
                    trace_id=msg_id,
                    sessionid=sessionid,
                    first_chunk_len=len(chunk),
                )
                log_perf(
                    "trace",
                    "llm_first_token",
                    first_token_ms,
                    trace_id=msg_id,
                    sessionid=sessionid,
                    first_chunk_len=len(chunk),
                )

            chunk_count += 1
            result_queue.put_nowait(
                {
                    "data": chunk,
                    "id": msg_id,
                    "trace_id": msg_id,
                    "finish": False,
                    "_perf_enqueued_mono": now(),
                }
            )
            complete_response.append(chunk)

            tts_buffer += chunk
            punct_pos = _find_last_punct(tts_buffer)
            if punct_pos >= 0 and (punct_pos >= min_segment_len or len(tts_buffer) >= 30):
                queue_tts(tts_buffer[: punct_pos + 1])
                tts_buffer = tts_buffer[punct_pos + 1 :]
            elif len(tts_buffer) >= max_segment_len:
                queue_tts(tts_buffer)
                tts_buffer = ""

        if tts_buffer.strip():
            queue_tts(tts_buffer)

        result_queue.put_nowait(
            {
                "data": "",
                "id": msg_id,
                "trace_id": msg_id,
                "finish": True,
                "_perf_enqueued_mono": now(),
            }
        )
        total_ms = (time.perf_counter() - start_time) * 1000
        answer_len = sum(len(part) for part in complete_response)
        logger.info(
            f"Gongan LLM total time trace_id={msg_id}: {total_ms / 1000:.2f}s, "
            f"chunks={chunk_count}, answer_len={answer_len}, tts_segments={tts_segments_queued}"
        )
        log_perf(
            "llm",
            "stream_done",
            total_ms,
            trace_id=msg_id,
            sessionid=sessionid,
            chunks=chunk_count,
            answer_len=answer_len,
            tts_segments=tts_segments_queued,
        )
        log_perf(
            "trace",
            "llm_done",
            total_ms,
            trace_id=msg_id,
            sessionid=sessionid,
            chunks=chunk_count,
            answer_len=answer_len,
            tts_segments=tts_segments_queued,
        )
        return "".join(complete_response)

    except Exception as exc:
        logger.exception(f"Gongan LLM error trace_id={msg_id}: {exc}")
        result_queue.put_nowait(
            {
                "data": "",
                "id": msg_id,
                "trace_id": msg_id,
                "finish": True,
                "_perf_enqueued_mono": now(),
            }
        )
        return None
    finally:
        try:
            finish_start = now()
            finish_tts()
            log_perf(
                "tts",
                "finish_after_llm",
                elapsed_ms(finish_start),
                trace_id=msg_id,
                sessionid=sessionid,
                llm_chunks=chunk_count,
                tts_segments=tts_segments_queued,
            )
        except Exception as exc:
            logger.warning(f"Gongan TTS finish error trace_id={msg_id}: {exc}")
        finally:
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
