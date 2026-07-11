from __future__ import annotations

import asyncio
import json
import re
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, ConfigDict, ValidationError

from lab.agent.agents.memory_agent.user_prompt_block import UserPromptBlock
from lab.config_manager.vtuber import scan_bg_directory
from lab.conversations.chat_group import (
    ChatGroupManager,
    handle_client_disconnect,
    handle_group_operation,
)
from lab.conversations.chat_history_manager import (
    HistoryMessage,
    create_new_history,
    delete_history,
    get_history,
    get_history_list,
)
from lab.conversations.conversation_handler import (
    handle_conversation_trigger,
    handle_group_interrupt,
    handle_individual_interrupt,
)
from lab.message_handler import message_handler
from lab.service_context import ServiceContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from lab.agent.output_types import DisplayTextDict


class MessageType(Enum):
    """Enum for WebSocket message types"""

    GROUP = ["add-client-to-group", "remove-client-from-group"]
    HISTORY = [
        "fetch-history-list",
        "fetch-and-set-history",
        "create-new-history",
        "delete-history",
    ]
    CONVERSATION = ["mic-audio-end", "text-input", "ai-speak-signal"]
    CONFIG = ["fetch-configs", "switch-config"]
    CONTROL = ["interrupt-signal", "audio-play-start", "audio-play-began", "frontend-playback-complete"]
    DATA = ["mic-audio-data"]


class WSMessage(TypedDict, total=False):
    """Type definition for WebSocket messages"""

    type: str
    action: str | None
    text: str | None
    audio: list[float] | None
    images: list[str] | None
    history_uid: str | None
    file: str | None
    display_text: DisplayTextDict | None
    turn_id: str | None


class DisplayHistoryMessage(BaseModel):
    """Pydantic model for history messages sent to frontend."""

    model_config = ConfigDict(extra="allow")

    role: Literal["human", "ai", "system", "user", "assistant", "tool", "developer"]
    timestamp: str
    content: str
    name: str | None = None
    avatar: str | None = None


_TASK_PROMPT_PATTERN = re.compile(r"\[Task / User Prompt\]\s*(.*?)(?:\n\s*###|$)", re.DOTALL)


def _extract_user_prompt_for_display(content: str) -> str:
    """Extract user-visible text from packed prompt content for frontend history display."""
    if UserPromptBlock.is_block_content(content):
        try:
            block = UserPromptBlock.from_storage_content(content)
        except Exception:
            logger.warning("Failed to parse structured user prompt block for display; fallback to raw content")
            return content
        return block.user_text.strip() or content

    match = _TASK_PROMPT_PATTERN.search(content)
    if not match:
        return content
    return match.group(1).strip() or content


def _format_history_message_for_display(message: HistoryMessage) -> dict[str, Any]:
    """Return a display-safe history message without mutating stored history data."""
    try:
        display_message = DisplayHistoryMessage.model_validate(message)
    except ValidationError:
        logger.warning("Failed to validate history message for display; fallback to raw message")
        return dict(message)

    if display_message.role in {"user", "human"}:
        display_message.content = _extract_user_prompt_for_display(display_message.content)

    return display_message.model_dump(exclude_none=True)


class WebSocketHandler:
    """Handles WebSocket connections and message routing"""

    def __init__(self, default_context_cache: ServiceContext):
        """Initialize the WebSocket handler with default context"""
        self.client_connections: dict[str, WebSocket] = {}
        self.client_contexts: dict[str, ServiceContext] = {}
        self.chat_group_manager = ChatGroupManager()
        self.current_conversation_tasks: dict[str, asyncio.Task | None] = {}
        self.default_context_cache = default_context_cache
        self.received_data_buffers: dict[str, np.ndarray[Any, Any]] = {}

        # Message handlers mapping
        self._message_handlers = self._init_message_handlers()

    def _init_message_handlers(self) -> dict[str, Callable]:
        """Initialize message type to handler mapping"""
        return {
            "add-client-to-group": self._handle_group_operation,
            "remove-client-from-group": self._handle_group_operation,
            "request-group-info": self._handle_group_info,
            "fetch-history-list": self._handle_history_list_request,
            "fetch-and-set-history": self._handle_fetch_history,
            "create-new-history": self._handle_create_history,
            "delete-history": self._handle_delete_history,
            "interrupt-signal": self._handle_interrupt,
            "mic-audio-data": self._handle_audio_data,
            "mic-audio-end": self._handle_conversation_trigger,
            "raw-audio-data": self._handle_raw_audio_data,
            "text-input": self._handle_conversation_trigger,
            "ai-speak-signal": self._handle_conversation_trigger,
            "fetch-configs": self._handle_fetch_configs,
            "switch-config": self._handle_config_switch,
            "fetch-backgrounds": self._handle_fetch_backgrounds,
            "audio-play-start": self._handle_audio_play_start,
            "audio-play-began": self._handle_audio_play_began,
            "frontend-playback-complete": self._handle_frontend_playback_complete,
        }

    async def handle_new_connection(self, websocket: WebSocket, client_uid: str) -> None:
        """
        Handle new WebSocket connection setup

        Args:
            websocket: The WebSocket connection
            client_uid: Unique identifier for the client

        Raises:
            Exception: If initialization fails
        """
        try:
            session_service_context = await self._init_service_context()

            await self._store_client_data(websocket, client_uid, session_service_context)

            await self._send_initial_messages(websocket, client_uid, session_service_context)

            logger.debug(f"Connection established for client {client_uid}")

        except Exception as e:
            logger.error(f"Failed to initialize connection for client {client_uid}: {e}")
            await self._cleanup_failed_connection(client_uid)
            raise

    async def _cleanup_failed_connection(self, client_uid: str) -> None:
        """Drop any partially stored state for a client whose setup failed"""
        self.client_connections.pop(client_uid, None)
        self.client_contexts.pop(client_uid, None)
        self.received_data_buffers.pop(client_uid, None)
        self.chat_group_manager.client_group_map.pop(client_uid, None)

    async def _store_client_data(
        self,
        websocket: WebSocket,
        client_uid: str,
        session_service_context: ServiceContext,
    ):
        """Store client data and initialize group status"""
        self.client_connections[client_uid] = websocket
        self.client_contexts[client_uid] = session_service_context
        self.received_data_buffers[client_uid] = np.array([])

        self.chat_group_manager.client_group_map[client_uid] = ""
        await self.send_group_update(websocket, client_uid)

    async def _send_initial_messages(
        self,
        websocket: WebSocket,
        client_uid: str,
        session_service_context: ServiceContext,
    ):
        """Send initial connection messages to the client"""
        await websocket.send_text(json.dumps({"type": "full-text", "text": "Connection established"}))

        await websocket.send_text(
            json.dumps(
                {
                    "type": "set-model-and-conf",
                    "model_info": (
                        {
                            **session_service_context.live2d_model.model_info,
                            "renderScale": session_service_context.lab_setting.server.live2d_render_scale,
                        }
                        if session_service_context.live2d_model is not None
                        else None
                    ),
                    "conf_name": (
                        session_service_context.character_config.character_name
                        if session_service_context.character_config is not None
                        else ""
                    ),
                    "conf_uid": (
                        session_service_context.character_config.profile_id
                        if session_service_context.character_config is not None
                        else ""
                    ),
                    "client_uid": client_uid,
                    "asr_enabled": bool(
                        session_service_context.lab_setting.asr.asr_model_provider
                        and session_service_context.lab_setting.asr.asr_model_provider != "none"
                    ),
                }
            )
        )

        # Send initial group status
        await self.send_group_update(websocket, client_uid)

        await session_service_context.send_current_mood(websocket.send_text)

        await session_service_context.send_live2d_runtime_state(websocket.send_text, state="listening")

    async def _init_service_context(self) -> ServiceContext:
        """Initialize service context for a new session by cloning the default context"""
        session_service_context = ServiceContext()
        session_service_context.load_cache(
            lab_setting=self.default_context_cache.lab_setting.model_copy(deep=True),
            server_config=self.default_context_cache.server_config.model_copy(deep=True),  # type: ignore
            character_config=(
                self.default_context_cache.character_config.model_copy(deep=True)
                if self.default_context_cache.character_config is not None
                else None
            ),
            live2d_model=self.default_context_cache.live2d_model,
            agent_engine=self.default_context_cache.agent_engine,  # type: ignore
        )

        return session_service_context

    def refresh_client_contexts_from_default(self) -> int:
        """Refresh all connected session contexts from the shared default context."""
        refreshed = 0
        for context in self.client_contexts.values():
            context.load_cache(
                lab_setting=self.default_context_cache.lab_setting.model_copy(deep=True),
                server_config=self.default_context_cache.server_config.model_copy(deep=True),  # type: ignore
                character_config=(
                    self.default_context_cache.character_config.model_copy(deep=True)
                    if self.default_context_cache.character_config is not None
                    else None
                ),
                live2d_model=self.default_context_cache.live2d_model,
                agent_engine=self.default_context_cache.agent_engine,  # type: ignore
            )
            refreshed += 1
        return refreshed

    async def handle_websocket_communication(self, websocket: WebSocket, client_uid: str) -> None:
        """
        Handle ongoing WebSocket communication

        Args:
            websocket: The WebSocket connection
            client_uid: Unique identifier for the client
        """
        try:
            while True:
                try:
                    data = await websocket.receive_json()
                    message_handler.handle_message(client_uid, data)
                    await self._route_message(websocket, client_uid, data)
                except WebSocketDisconnect:
                    raise
                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                    continue
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
                    continue

        except WebSocketDisconnect:
            logger.info(f"Client {client_uid} disconnected")
            raise
        except Exception as e:
            logger.error(f"Fatal error in WebSocket communication: {e}")
            raise

    async def _route_message(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """
        Route incoming message to appropriate handler

        Args:
            websocket: The WebSocket connection
            client_uid: Client identifier
            data: Message data
        """
        msg_type = data.get("type")
        if not msg_type:
            logger.warning("Message received without type")
            return

        handler = self._message_handlers.get(msg_type)
        if handler:
            await handler(websocket, client_uid, data)
        else:
            logger.warning(f"Unknown message type: {msg_type}")

    async def _handle_group_operation(self, websocket: WebSocket, client_uid: str, data: dict[str, Any]) -> None:
        """Handle group-related operations"""
        operation = data.get("type") or ""
        target_uid = data.get("invitee_uid" if operation == "add-client-to-group" else "target_uid") or ""

        await handle_group_operation(
            operation=operation,
            client_uid=client_uid,
            target_uid=target_uid,
            chat_group_manager=self.chat_group_manager,
            client_connections=self.client_connections,
            send_group_update=self.send_group_update,
        )

    async def handle_disconnect(self, client_uid: str) -> None:
        """Handle client disconnection"""
        group = self.chat_group_manager.get_client_group(client_uid)
        if group:
            await handle_group_interrupt(
                group_id=group.group_id,
            )

        await handle_client_disconnect(
            client_uid=client_uid,
            chat_group_manager=self.chat_group_manager,
            client_connections=self.client_connections,
            send_group_update=self.send_group_update,
        )

        session_context = self.client_contexts.get(client_uid)
        if (
            session_context is not None
            and session_context.agent_engine is not None
            and session_context.agent_engine is not self.default_context_cache.agent_engine
        ):
            try:
                await session_context.agent_engine.close()
            except Exception as exc:
                logger.warning("Failed to close session agent engine for client {}: {}", client_uid, exc)
            finally:
                session_context.agent_engine = None

        # Clean up other client data
        self.client_connections.pop(client_uid, None)
        self.client_contexts.pop(client_uid, None)
        self.received_data_buffers.pop(client_uid, None)
        if client_uid in self.current_conversation_tasks:
            task = self.current_conversation_tasks[client_uid]
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.debug("Conversation task cancelled during disconnect cleanup for {}", client_uid)
                except Exception as exc:
                    logger.warning("Conversation task failed during disconnect cleanup for {}: {}", client_uid, exc)
            self.current_conversation_tasks.pop(client_uid, None)

        logger.info(f"Client {client_uid} disconnected")
        message_handler.cleanup_client(client_uid)

    async def send_group_update(self, websocket: WebSocket, client_uid: str):
        """Sends group information to a client"""
        group = self.chat_group_manager.get_client_group(client_uid)
        if group:
            current_members = self.chat_group_manager.get_group_members(client_uid)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "group-update",
                        "members": current_members,
                        "is_owner": group.owner_uid == client_uid,
                    }
                )
            )
        else:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "group-update",
                        "members": [],
                        "is_owner": False,
                    }
                )
            )

    async def _handle_interrupt(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle conversation interruption"""
        heard_response = data.get("text") or ""
        context = self.client_contexts[client_uid]
        group = self.chat_group_manager.get_client_group(client_uid)

        if group and len(group.members) > 1:
            await handle_group_interrupt(
                group_id=group.group_id,
            )
        else:
            await handle_individual_interrupt(
                client_uid=client_uid,
                current_conversation_tasks=self.current_conversation_tasks,
                context=context,
                heard_response=heard_response,
            )

    async def _handle_history_list_request(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle request for chat history list"""
        context = self.client_contexts[client_uid]
        if context.character_config is None:
            logger.error("character_config is None, cannot create new history")
            raise ValueError("character_config cannot be None")
        raw_histories = get_history_list(context.character_config.profile_id)
        histories: list[dict[str, Any]] = []
        for item in raw_histories:
            history = dict(item)
            latest_message = history.get("latest_message")
            if isinstance(latest_message, dict):
                history["latest_message"] = _format_history_message_for_display(cast("HistoryMessage", latest_message))
            histories.append(history)
        await websocket.send_text(json.dumps({"type": "history-list", "histories": histories}))

    async def _handle_fetch_history(self, websocket: WebSocket, client_uid: str, data: dict[Any, Any]):
        """Handle fetching and setting specific chat history"""
        history_uid = data.get("history_uid")
        if not history_uid:
            return

        context = self.client_contexts[client_uid]
        # Update history_uid in service context
        context.history_uid = history_uid
        # print(context.history_uid)
        if context.agent_engine is None:
            logger.error("agent_engine is None, cannot set memory from history")
            raise ValueError("agent_engine cannot be None")
        if context.character_config is None:
            logger.error("character_config is None, cannot set memory from history")
            raise ValueError("character_config cannot be None")
        context.agent_engine.set_memory_from_history(
            conf_uid=context.character_config.profile_id,
            history_uid=history_uid,
        )
        # if context.character_config is None:
        #     logger.error("character_config is None, cannot create new history")
        #     raise ValueError("character_config cannot be None")
        msgs = get_history(
            context.character_config.profile_id,
            history_uid,
        )
        messages = [_format_history_message_for_display(msg) for msg in msgs if msg["role"] != "system"]
        await websocket.send_text(json.dumps({"type": "history-data", "messages": messages}))

    async def _handle_create_history(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle creation of new chat history"""
        context = self.client_contexts[client_uid]
        if context.character_config is None:
            logger.error("character_config is None, cannot create new history")
            raise ValueError("character_config cannot be None")
        if context.agent_engine is None:
            logger.error("agent_engine is None, cannot create new history")
            raise ValueError("agent_engine cannot be None")
        history_uid = create_new_history(context.character_config.profile_id)
        if history_uid:
            context.history_uid = history_uid
            context.agent_engine.set_memory_from_history(
                conf_uid=context.character_config.profile_id,
                history_uid=history_uid,
            )
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "new-history-created",
                        "history_uid": history_uid,
                    }
                )
            )

    async def _handle_delete_history(self, websocket: WebSocket, client_uid: str, data: dict[Any, Any]) -> None:
        """Handle deletion of chat history"""
        history_uid = data.get("history_uid")
        if not history_uid:
            return
        context = self.client_contexts[client_uid]
        if context.character_config is None:
            logger.error("character_config is None, cannot create new history")
            raise ValueError("character_config cannot be None")
        success = delete_history(
            context.character_config.profile_id,
            history_uid,
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "history-deleted",
                    "success": success,
                    "history_uid": history_uid,
                }
            )
        )
        if history_uid == context.history_uid:
            context.history_uid = ""

    async def _handle_audio_data(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle incoming audio data"""
        audio_data = data.get("audio", [])
        if audio_data:
            self.received_data_buffers[client_uid] = np.append(
                self.received_data_buffers[client_uid],
                np.array(audio_data, dtype=np.float32),
            )

    async def _handle_raw_audio_data(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle incoming raw audio data for VAD processing"""
        # context = self.client_contexts[client_uid]
        logger.debug(f"Received raw audio data for client {client_uid}")
        # chunk = data.get("audio", [])
        # if chunk:
        #     for audio_bytes in context.vad_engine.detect_speech(chunk):
        #         if audio_bytes == b"<|PAUSE|>":
        #             await websocket.send_text(json.dumps({"type": "control", "text": "interrupt"}))
        #         elif audio_bytes == b"<|RESUME|>":
        #             pass
        #         elif len(audio_bytes) > 1024:
        #             # Detected audio activity (voice)
        #             self.received_data_buffers[client_uid] = np.append(
        #                 self.received_data_buffers[client_uid],
        #                 np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32),
        #             )
        #             await websocket.send_text(json.dumps({"type": "control", "text": "mic-audio-end"}))

    async def _handle_conversation_trigger(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle triggers that start a conversation"""
        await handle_conversation_trigger(
            msg_type=data.get("type", ""),
            data=dict(data),
            client_uid=client_uid,
            context=self.client_contexts[client_uid],
            websocket=websocket,
            received_data_buffers=self.received_data_buffers,
            current_conversation_tasks=self.current_conversation_tasks,
        )

    async def _handle_fetch_configs(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle fetching available configurations"""
        context = self.client_contexts[client_uid]
        if context.character_config is None:
            logger.error("character_config is None, cannot fetch config files")
            raise ValueError("character_config cannot be None")
        config_files = [{"filename": "lab.toml", "name": context.character_config.character_name}]
        await websocket.send_text(json.dumps({"type": "config-files", "configs": config_files}))

    async def _handle_config_switch(self, websocket: WebSocket, client_uid: str, data: dict[Any, Any]):
        """Handle switching to a different configuration"""
        config_file_name = data.get("file")
        if config_file_name:
            context = self.client_contexts[client_uid]
            await context.handle_config_switch(websocket, config_file_name)

    async def _handle_fetch_backgrounds(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle fetching available background images"""
        bg_files = scan_bg_directory()
        await websocket.send_text(json.dumps({"type": "background-files", "files": bg_files}))

    async def _handle_audio_play_start(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """
        Handle frontend audio task acceptance notification
        """
        display_text = data.get("display_text") or {}
        text = display_text.get("text")
        logger.debug(
            "[PLAYBACK] frontend accepted audio task: client_uid={} text={}",
            client_uid,
            " ".join(str(text or "").split()),
        )

    async def _handle_audio_play_began(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle actual frontend audio playback begin notification."""
        del websocket
        display_text = data.get("display_text") or {}
        text = display_text.get("text")
        logger.debug(
            "[PLAYBACK] frontend began audible playback: client_uid={} text={}",
            client_uid,
            " ".join(str(text or "").split()),
        )

    async def _handle_frontend_playback_complete(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle frontend playback completion notification."""
        del websocket
        logger.debug(
            "[PLAYBACK] frontend completed queued audio: client_uid={} turn_id={}",
            client_uid,
            data.get("turn_id"),
        )

    async def _handle_group_info(self, websocket: WebSocket, client_uid: str, data: WSMessage) -> None:
        """Handle group info request"""
        await self.send_group_update(websocket, client_uid)
