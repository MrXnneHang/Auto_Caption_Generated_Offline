from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, TypeAlias

import numpy as np
from loguru import logger

from lab.conversations.chat_history_manager import store_message
from lab.conversations.conversation_utils import EMOJI_LIST
from lab.conversations.single_conversation import process_single_conversation

if TYPE_CHECKING:
    from fastapi import WebSocket

    from lab.service_context import ServiceContext


ConversationTask: TypeAlias = asyncio.Task[str]


async def _cancel_client_conversation_task(
    client_uid: str,
    current_conversation_tasks: dict[str, ConversationTask | None],
    *,
    reason: str,
) -> None:
    task = current_conversation_tasks.get(client_uid)
    if task is None:
        return

    if task.done():
        current_conversation_tasks.pop(client_uid, None)
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.debug("Conversation task cancelled for {} ({})", client_uid, reason)
    except Exception as exc:
        logger.warning("Conversation task ended with error for {} during {}: {}", client_uid, reason, exc)
    finally:
        if current_conversation_tasks.get(client_uid) is task:
            current_conversation_tasks.pop(client_uid, None)


async def handle_conversation_trigger(
    msg_type: str,
    data: dict[Any, Any],
    client_uid: str,
    context: ServiceContext,
    websocket: WebSocket,
    received_data_buffers: dict[str, np.ndarray[Any, Any]],
    current_conversation_tasks: dict[str, ConversationTask | None],
) -> None:
    """Handle triggers that start a conversation."""
    existing_task = current_conversation_tasks.get(client_uid)
    if existing_task is not None and not existing_task.done():
        logger.warning("Replacing active conversation task for client {}; cancelling previous turn first", client_uid)
        await _cancel_client_conversation_task(
            client_uid,
            current_conversation_tasks,
            reason="conversation replacement",
        )
    elif existing_task is not None and existing_task.done():
        current_conversation_tasks.pop(client_uid, None)

    if msg_type == "ai-speak-signal":
        user_input = ""
        await websocket.send_text(
            json.dumps(
                {
                    "type": "full-text",
                    "text": "AI wants to speak something...",
                }
            )
        )
    elif msg_type == "text-input":
        user_input = data.get("text", "")
    else:  # mic-audio-end
        user_input = received_data_buffers[client_uid]
        received_data_buffers[client_uid] = np.array([])

    images = data.get("images")
    session_emoji = np.random.choice(EMOJI_LIST)

    logger.debug("Starting new single conversation for {}", client_uid)
    task = asyncio.create_task(
        process_single_conversation(
            context=context,
            websocket_send=websocket.send_text,
            client_uid=client_uid,
            user_input=user_input,
            images=images,
            session_emoji=session_emoji,
        )
    )
    current_conversation_tasks[client_uid] = task

    def _clear_finished_task(completed_task: ConversationTask, *, uid: str = client_uid) -> None:
        current_task = current_conversation_tasks.get(uid)
        if current_task is completed_task:
            current_conversation_tasks.pop(uid, None)
        if not completed_task.cancelled() and completed_task.exception() is not None:
            logger.error("Conversation task for {} failed: {}", uid, completed_task.exception())

    task.add_done_callback(_clear_finished_task)


async def handle_individual_interrupt(
    client_uid: str,
    current_conversation_tasks: dict[str, ConversationTask | None],
    context: ServiceContext,
    heard_response: str,
) -> None:
    await _cancel_client_conversation_task(
        client_uid,
        current_conversation_tasks,
        reason="user interrupt",
    )

    if context.history_uid:
        if context.character_config is None:
            logger.error("character_config is None, cannot store message")
            raise ValueError("character_config cannot be None")
        if heard_response.strip():
            store_message(
                conf_uid=context.character_config.profile_id,
                history_uid=context.history_uid,
                role="assistant",
                content=heard_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
            )
        store_message(
            conf_uid=context.character_config.profile_id,
            history_uid=context.history_uid,
            role="system",
            content="[Interrupted by user]",
        )


async def handle_group_interrupt(
    group_id: str,
) -> None:
    """Handles interruption for a group conversation."""
    logger.debug("handle_group_interrupt called for group {}", group_id)
