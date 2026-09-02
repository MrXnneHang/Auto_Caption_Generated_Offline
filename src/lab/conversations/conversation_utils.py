from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import numpy as np
import soundfile as sf
from loguru import logger

from lab.agent.input_types import BatchInput, ImageData, ImageSource, TextData, TextSource
from lab.agent.output_types import Actions
from lab.api.clients import ASRClient, ASRRequest
from lab.conversations.tts_manager import has_audible_tts_text
from lab.live2d_startup import inject_startup_expression_once
from lab.message_handler import message_handler

if TYPE_CHECKING:
    from lab.agent.output_types import SentenceOutput, ToolCallEvent
    from lab.api.logic.translate import TranslateEngineRouter
    from lab.config_manager import XnneHangLabSettings
    from lab.conversations.tts_manager import TTSTaskManager
    from lab.conversations.types import BroadcastContext, WebSocketSend
    from lab.live2d_model import Live2dModel
    from lab.service_context import ServiceContext


# Convert class methods to standalone functions
def create_batch_input(
    input_text: str,
    images: list[dict[str, Any]] | None,
    from_name: str,
) -> BatchInput:
    """Create batch input for agent processing"""
    return BatchInput(
        texts=[TextData(source=TextSource.INPUT, content=input_text, from_name=from_name)],
        images=[
            ImageData(
                source=ImageSource(img["source"]),
                data=img["data"],
                mime_type=img["mime_type"],
            )
            for img in (images or [])
        ]
        if images
        else None,
    )


async def process_agent_output(
    output: SentenceOutput,  # 我们不使用 human ai ，所以仅有 SentenceOutput, voice 通过 tts 生成
    lab_settings: XnneHangLabSettings,
    character_config: Any,
    live2d_model: Live2dModel | None,
    service_context: ServiceContext,
    # tts_engine: TTSInterface,
    websocket_send: WebSocketSend,
    tts_manager: TTSTaskManager,
    translate_engine: TranslateEngineRouter | None = None,
) -> str:
    """Process agent output with character information and optional translation"""
    if character_config is not None:
        output.display_text.name = character_config.character_name
        output.display_text.avatar = character_config.avatar

    full_response = ""
    try:
        # if isinstance(output, SentenceOutput):
        logger.debug("SentenceOutput Detect")
        full_response = await handle_sentence_output(
            output,
            lab_settings,
            live2d_model,
            service_context,
            # tts_engine,
            websocket_send,
            tts_manager,
            translate_engine,
        )
    except Exception as e:
        logger.error(f"Error processing agent output: {e}")
        await websocket_send(json.dumps({"type": "error", "message": f"Error processing response: {str(e)}"}))

    return full_response


async def send_tool_call_event(
    event: ToolCallEvent,
    websocket_send: WebSocketSend,
    service_context: ServiceContext | None = None,
) -> None:
    char_name = "AI"
    if service_context and service_context.character_config:
        char_name = service_context.character_config.character_name
    await websocket_send(
        json.dumps(
            {
                "type": "tool_call_status",
                "tool_id": event.tool_id,
                "tool_name": event.tool_name,
                "name": char_name,
                "status": event.status,
                "content": event.result if event.result is not None else event.args,
                "timestamp": datetime.now().isoformat(),
            }
        )
    )


async def handle_sentence_output(
    output: SentenceOutput,
    lab_settings: XnneHangLabSettings,
    live2d_model: Live2dModel | None,
    service_context: ServiceContext,
    # tts_engine: TTSInterface,
    websocket_send: WebSocketSend,
    tts_manager: TTSTaskManager,
    translate_engine: TranslateEngineRouter | None = None,
) -> str:
    """Handle sentence output type with optional translation support"""
    full_response = ""
    async for display_text, tts_text, actions in output:
        actions = actions or Actions()
        tts_text = tts_text.replace("*", "")
        display_text.text = display_text.text.replace("*", "")

        if lab_settings.agent.speaker_lang != lab_settings.agent.user_lang and has_audible_tts_text(tts_text):
            logger.debug(f"🏃 Processing output: '''{tts_text}'''...")
            logger.debug(f"🏃 Translating text to {lab_settings.agent.speaker_lang}...")
            if translate_engine is None:
                logger.warning("translate_engine is None, skipping translation")
            else:
                try:
                    tts_text = await translate_engine.translate(
                        text=tts_text,
                        target_language=lab_settings.agent.speaker_lang,
                    )
                    logger.debug(f"🏃 Text after translation: '''{tts_text}'''...")
                except Exception as exc:
                    logger.warning("Translation failed, using original text: {}", exc)
        full_response += display_text.text
        actions, service_context.live2d_startup_expression_applied = inject_startup_expression_once(
            actions=actions,
            live2d_model=live2d_model,
            already_applied=service_context.live2d_startup_expression_applied,
        )
        await tts_manager.speak(
            tts_text=tts_text,  # 直接使用大模型回復作為 TTS Text
            display_text=display_text,
            actions=actions,
            live2d_model=live2d_model,
            character_config=service_context.character_config,
            # tts_engine=tts_engine,
            websocket_send=websocket_send,
        )
    return full_response


async def send_conversation_start_signals(websocket_send: WebSocketSend) -> None:
    """Send initial conversation signals"""
    await websocket_send(
        json.dumps(
            {
                "type": "control",
                "text": "conversation-chain-start",
            }
        )
    )
    await websocket_send(json.dumps({"type": "full-text", "text": "Thinking..."}))


def create_turn_id() -> str:
    return uuid4().hex


async def send_conversation_start_signals_for_turn(
    websocket_send: WebSocketSend,
    turn_id: str,
    service_context: ServiceContext | None = None,
) -> None:
    await websocket_send(
        json.dumps(
            {
                "type": "control",
                "text": "conversation-chain-start",
                "turn_id": turn_id,
            }
        )
    )
    await websocket_send(json.dumps({"type": "full-text", "text": "Thinking...", "turn_id": turn_id}))
    if service_context is not None:
        await service_context.send_live2d_runtime_state(websocket_send, state="speaking")


async def process_user_input(
    user_input: str | np.ndarray[Any, Any],
    websocket_send: WebSocketSend,
    lab_setting: XnneHangLabSettings | None = None,
) -> str:
    """Process user input, converting audio to text if needed"""
    if isinstance(user_input, np.ndarray):
        if lab_setting is not None and lab_setting.asr.asr_model_provider == "none":
            raise RuntimeError("ASR is disabled in lab.toml. Use text input or enable an ASR service.")

        logger.info("Transcribing audio input...")
        # 确保 cache 目录存在
        cache_dir = Path("cache")
        cache_dir.mkdir(parents=True, exist_ok=True)

        # 生成唯一的文件名
        audio_dir = cache_dir / "asr"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_file_path = audio_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}.wav"

        try:
            # 将音频数据写入文件
            sf.write(audio_file_path, user_input, samplerate=16000)  # 假设采样率为 16000 Hz
            # 使用文件路径调用异步转录方法
            asr_client = ASRClient(lab_setting=lab_setting) if lab_setting is not None else ASRClient()
            response = await asr_client.asyncpost(ASRRequest(file_path=audio_file_path))
            if response is None:
                raise RuntimeError(
                    asr_client.last_error or "ASR is unavailable. Use text input or enable an ASR service."
                )

            # Sherpa-ONNX Paraformer 在字符级别做 tokenize，返回的文本中每个字符间都有空格
            cleaned_text = response["text"].replace(" ", "")
            await websocket_send(json.dumps({"type": "user-input-transcription", "text": cleaned_text}))
        finally:
            # 删除临时音频文件
            if audio_file_path.exists():
                audio_file_path.unlink()

        return cleaned_text  # TODO, 规范化我们的 routes 输出，以 TypedDict 约束
    else:
        logger.debug(f"User input: {user_input}")
        # await websocket_send(json.dumps({"type": "user-input-text", "text": user_input}))
        return user_input


async def finalize_conversation_turn(
    tts_manager: TTSTaskManager,
    websocket_send: WebSocketSend,
    client_uid: str,
    broadcast_ctx: BroadcastContext | None = None,
    turn_id: str | None = None,
    service_context: ServiceContext | None = None,
) -> None:
    """Finalize a conversation turn"""
    if tts_manager.has_output():
        await tts_manager.wait_until_all_payloads_sent()
        await websocket_send(json.dumps({"type": "backend-synth-complete", "turn_id": turn_id}))

        playback_timeout = tts_manager.playback_completion_timeout_s()
        response = await wait_for_frontend_playback_completion(
            client_uid,
            turn_id=turn_id,
            timeout=playback_timeout,
        )
        if not response:
            logger.warning(
                "No playback completion response from {} within {:.2f}s; continuing turn finalization",
                client_uid,
                playback_timeout,
            )

    await websocket_send(json.dumps({"type": "force-new-message"}))

    if broadcast_ctx and broadcast_ctx.broadcast_func:
        await broadcast_ctx.broadcast_func(
            broadcast_ctx.group_members,  # type: ignore
            {"type": "force-new-message"},
            broadcast_ctx.current_client_uid,
        )

    await send_conversation_end_signal(
        websocket_send,
        broadcast_ctx,
        service_context=service_context,
    )


async def send_conversation_end_signal(
    websocket_send: WebSocketSend,
    broadcast_ctx: BroadcastContext | None,
    session_emoji: str = "😊",
    service_context: ServiceContext | None = None,
) -> None:
    """Send conversation chain end signal"""
    chain_end_msg = {
        "type": "control",
        "text": "conversation-chain-end",
    }

    await websocket_send(json.dumps(chain_end_msg))

    if broadcast_ctx and broadcast_ctx.broadcast_func and broadcast_ctx.group_members:
        await broadcast_ctx.broadcast_func(  # type: ignore
            broadcast_ctx.group_members,
            chain_end_msg,
        )

    if service_context is not None:
        await service_context.send_live2d_runtime_state(websocket_send, state="listening")

    logger.info(f"😎👍✅ Conversation Chain {session_emoji} completed!")


async def wait_for_frontend_playback_completion(
    client_uid: str,
    *,
    turn_id: str | None = None,
    timeout: float | None = None,
) -> dict[Any, Any] | None:
    """Wait for the frontend playback completion ack for the current turn."""
    return await message_handler.wait_for_response(
        client_uid,
        "frontend-playback-complete",
        timeout=timeout,
        response_filter=(lambda message: message.get("turn_id") == turn_id) if turn_id else None,
    )


def cleanup_conversation(tts_manager: TTSTaskManager, session_emoji: str) -> None:
    """Clean up conversation resources"""
    tts_manager.clear()
    logger.debug(f"🧹 Clearing up conversation {session_emoji}.")


EMOJI_LIST = [
    "🐶",
    "🐱",
    "🐭",
    "🐹",
    "🐰",
    "🦊",
    "🐻",
    "🐼",
    "🐨",
    "🐯",
    "🦁",
    "🐮",
    "🐷",
    "🐸",
    "🐵",
    "🐔",
    "🐧",
    "🐦",
    "🐤",
    "🐣",
    "🐥",
    "🦆",
    "🦅",
    "🦉",
    "🦇",
    "🐺",
    "🐗",
    "🐴",
    "🦄",
    "🐝",
    "🌵",
    "🎄",
    "🌲",
    "🌳",
    "🌴",
    "🌱",
    "🌿",
    "☘️",
    "🍀",
    "🍂",
    "🍁",
    "🍄",
    "🌾",
    "💐",
    "🌹",
    "🌸",
    "🌛",
    "🌍",
    "⭐️",
    "🔥",
    "🌈",
    "🌩",
    "⛄️",
    "🎃",
    "🎄",
    "🎉",
    "🎏",
    "🎗",
    "🀄️",
    "🎭",
    "🎨",
    "🧵",
    "🪡",
    "🧶",
    "🥽",
    "🥼",
    "🦺",
    "👔",
    "👕",
    "👜",
    "👑",
]
