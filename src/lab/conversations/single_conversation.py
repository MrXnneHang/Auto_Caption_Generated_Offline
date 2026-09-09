from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import numpy as np
from loguru import logger

from lab.agent.core import AgentCore
from lab.agent.output_types import ToolCallEvent
from lab.conversations.conversation_utils import (
    EMOJI_LIST,
    cleanup_conversation,
    create_batch_input,
    create_turn_id,
    finalize_conversation_turn,
    process_agent_output,
    process_user_input,
    send_conversation_start_signals_for_turn,
    send_tool_call_event,
)
from lab.conversations.tts_manager import TTSTaskManager

if TYPE_CHECKING:
    from lab.agent.input_types import BatchInput
    from lab.conversations.types import WebSocketSend
    from lab.service_context import ServiceContext


async def process_single_conversation(
    context: ServiceContext,
    websocket_send: WebSocketSend,
    client_uid: str,
    user_input: str | np.ndarray[Any, Any],
    images: list[dict[str, Any]] | None = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
) -> str:
    """Process a single-user conversation turn

    Args:
        context: Service context containing all configurations and engines
        websocket_send: WebSocket send function
        client_uid: Client unique identifier
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation

    Returns:
        str: Complete response text
    """
    # Create TTSTaskManager for this conversation
    turn_id = create_turn_id()
    tts_manager = TTSTaskManager(turn_id=turn_id, lab_setting=context.lab_setting)

    try:
        # Send initial signals
        await send_conversation_start_signals_for_turn(
            websocket_send,
            turn_id,
            service_context=context,
        )
        logger.info(f"New Conversation Chain {session_emoji} started!")

        # Process user input

        input_text = await process_user_input(user_input, websocket_send, lab_setting=context.lab_setting)

        # Create batch input
        # TODO: 检查 context 的初始化，并且提前做好默认值
        if context.character_config is None:
            logger.error("character_config is None, cannot create batch input")
            raise ValueError("character_config cannot be None")
        batch_input = create_batch_input(
            input_text=input_text,
            images=images,
            from_name=context.character_config.human_name,
        )

        if images:
            logger.debug(f"With {len(images)} images")

        # Process agent response
        full_response = await process_agent_response(
            context=context,
            batch_input=batch_input,
            websocket_send=websocket_send,
            client_uid=client_uid,
            tts_manager=tts_manager,
        )

        await context.send_current_mood(websocket_send)

        if tts_manager.has_output():
            logger.debug("Conversation queued response payloads; waiting for frontend playback handshake")
        else:
            logger.debug("No TTS tasks to wait for")

        await finalize_conversation_turn(
            tts_manager=tts_manager,
            websocket_send=websocket_send,
            client_uid=client_uid,
            turn_id=turn_id,
            service_context=context,
        )

        agent_core = getattr(context.agent_engine, "core", None)
        hook_manager = getattr(agent_core, "_hook_manager", None)
        agent_context = getattr(agent_core, "agent_context", None)
        if hook_manager is not None and agent_context is not None:
            await hook_manager.after_playback(input_text, full_response, agent_context)

        return full_response

    except asyncio.CancelledError:
        logger.info(f"🤡👍 Conversation {session_emoji} cancelled because interrupted.")
        raise
    except Exception as e:
        logger.error(f"Error in conversation chain: {e}")
        await websocket_send(json.dumps({"type": "error", "message": f"Conversation error: {str(e)}"}))
        raise
    finally:
        cleanup_conversation(tts_manager, session_emoji)


async def process_agent_response(
    context: ServiceContext,
    batch_input: BatchInput,
    websocket_send: WebSocketSend,
    client_uid: str,
    tts_manager: TTSTaskManager,
) -> str:
    """Process agent response and generate output

    Args:
        context: Service context containing all configurations and engines
        batch_input: Input data for the agent
        websocket_send: WebSocket send function
        tts_manager: TTSTaskManager for the conversation

    Returns:
        str: The complete response text
    """
    full_response = ""
    try:
        # agent 记忆和输入是分开的。
        if context.agent_engine is None:
            logger.error("agent_engine is None, cannot process agent response")
            raise ValueError("agent_engine cannot be None")
        agent_core = getattr(context.agent_engine, "core", None)
        if isinstance(agent_core, AgentCore) and agent_core.agent_context is not None:
            agent_core.agent_context.extra["websocket_send"] = websocket_send
            agent_core.agent_context.extra["client_uid"] = client_uid
            agent_core.agent_context.extra["service_context"] = context
        agent_output = context.agent_engine.chat(batch_input)
        async for output in agent_output:  # type: ignore
            if isinstance(output, ToolCallEvent):
                await send_tool_call_event(output, websocket_send, context)
                continue
            logger.debug(output)
            response_part = await process_agent_output(
                output=output,
                lab_settings=context.lab_setting,
                character_config=context.character_config,
                live2d_model=context.live2d_model,
                service_context=context,
                # tts_engine=context.tts_engine,
                websocket_send=websocket_send,
                tts_manager=tts_manager,
                translate_engine=context.translate_engine,
            )
            full_response += response_part

    except Exception as e:
        logger.error(f"Error processing agent response: {e}")
        raise
    logger.debug("Returning full_response")
    return full_response
