from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from loguru import logger

from lab.agent.agents.agent_interface import AgentInterface
from lab.agent.transformers import actions_extractor, display_processor, sentence_divider, tts_filter

from .memory_store import MemoryStore
from .message_factory import MessageFactory
from .types import ImagePayload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from lab.agent.core import AgentCore
    from lab.agent.input_types import BatchInput
    from lab.agent.output_types import AudioOutput, SentenceOutput, ToolCallEvent
    from lab.agent.types import OpenAIMessage
    from lab.config_manager.config import XnneHangLabSettings
    from lab.config_manager.vtuber import TTSPreprocessorConfig
    from lab.live2d_model import Live2dModel


_TOOL_STATUS_RE = re.compile(r"<tool>\[[^\]]+]</tool>")


def _strip_tool_status_tokens(text: str) -> str:
    return _TOOL_STATUS_RE.sub("", text)


strip_tool_status_tokens = _strip_tool_status_tokens


class MemoryAgent(AgentInterface):
    """Compose AgentCore output into the TTS and Live2D pipeline."""

    def __init__(
        self,
        *,
        lab_settings: XnneHangLabSettings,
        core: AgentCore,
        live2d_model: Live2dModel | None,
        tts_preprocessor_config: TTSPreprocessorConfig | None,
        show_control_tags: bool = False,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        interrupt_method: Literal["system", "user"] = "user",
    ) -> None:
        super().__init__()

        self.lab_settings = lab_settings
        self.core = core
        self.core.write_back = True

        self.msg = MessageFactory()
        self.memory = MemoryStore()
        self.memory.set_interrupt_method(interrupt_method)

        self._live2d_model = live2d_model
        self.tts_preprocessor_config = tts_preprocessor_config
        self.show_control_tags = show_control_tags
        self.faster_first_response = faster_first_response
        self.segment_method = segment_method

        self._bound_chat: Callable[[BatchInput], AsyncIterator[SentenceOutput | AudioOutput | ToolCallEvent]] = (
            self._chat_function_factory(self._core_stream)
        )
        logger.info("MemoryAgent initialized (AgentCore mode).")

    async def connect_mcp_servers(self, servers: list[tuple[str, str]] | None = None) -> None:
        """Compatibility no-op after MCP removal."""
        if servers:
            logger.info("Ignoring %d MCP server(s); MCP support has been removed.", len(servers))

    async def close(self) -> None:
        """No resources to release."""

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        self.memory.set_memory_from_history(conf_uid, history_uid)

    def handle_interrupt(self, heard_response: str) -> None:
        self.memory.handle_interrupt(heard_response)

    def reset_interrupt(self) -> None:
        self.memory.reset_interrupt()

    async def _core_stream(self, messages: list[OpenAIMessage]) -> AsyncIterator[str | ToolCallEvent]:
        assert messages and messages[-1].role == "user", "last message must be user"
        user_text, user_up_images = self.msg.extract_text_and_data_images(messages[-1])
        user_images = [
            ImagePayload(label=f"p{i + 1}", b64=b64, mime=mime, source="upload")
            for i, (b64, mime) in enumerate(user_up_images)
        ]
        async for token in self.core.run_turn(
            user_text=user_text,
            user_images=user_images,
        ):
            yield token

    def _chat_function_factory(
        self,
        chat_func: Callable[[list[OpenAIMessage]], AsyncIterator[str | ToolCallEvent]],
    ) -> Callable[..., AsyncIterator[SentenceOutput | AudioOutput | ToolCallEvent]]:
        @tts_filter(self.tts_preprocessor_config)
        @display_processor(show_control_tags=self.show_control_tags)
        @actions_extractor(
            self._live2d_model,
        )
        @sentence_divider(
            faster_first_response=self.faster_first_response,
            segment_method=self.segment_method,
            valid_tags=["think", "tool"],
        )
        async def chat_with_memory(input_data: BatchInput) -> AsyncIterator[str | ToolCallEvent | AudioOutput]:
            user_msg = self.msg.build_user_message_from_batch(input_data)
            messages: list[OpenAIMessage] = [*self.memory.messages, user_msg]

            token_stream = chat_func(messages)

            async for token in token_stream:
                yield token

        return chat_with_memory

    async def chat(self, input_data: BatchInput) -> AsyncIterator[SentenceOutput | AudioOutput | ToolCallEvent]:  # ty: ignore[invalid-method-override]
        async for chunk in self._bound_chat(input_data):
            yield chunk
