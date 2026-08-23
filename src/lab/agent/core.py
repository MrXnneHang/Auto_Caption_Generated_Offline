from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from lab.agent.agents.memory_agent.message_factory import MessageFactory
from lab.agent.agents.memory_agent.prompt_builder import PromptBuilder
from lab.agent.agents.memory_agent.types import DEFAULT_TOOL_IMAGE_LABEL, ImagePayload, VisionAnalysisOutcome
from lab.agent.agents.memory_agent.vision_summarizer import VisionSummarizer
from lab.agent.output_types import ToolCallEvent
from lab.agent.types import ConversationState, OpenAIMessage, ScreenShotResult
from lab.tools.types import ToolResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from lab.agent.agents.memory_agent.user_prompt_block import ContextEntry
    from lab.agent.hook_manager import HookManager
    from lab.agent.stateless_llm.openai_compatible_llm import AsyncLLM
    from lab.agent.storage import ConversationStorage
    from lab.profile.context_injector import ContextInjector
    from lab.tools import AgentContext, ToolManager


_TOOL_STATUS_ARG_KEYS: dict[str, tuple[str, ...]] = {
    "list_dir": ("path", "show_hidden"),
    "read_file": ("path", "start_line", "end_line"),
    "write_file": ("path", "append"),
    "edit_file": ("path", "count"),
    "set_live2d_appearance": ("appearance_key",),
}
_DEFAULT_TOOL_STATUS_ARG_KEYS = ("path", "query", "q", "url")
_MAX_TOOL_STATUS_FIELDS = 2
_MAX_TOOL_STATUS_VALUE_LEN = 48


def _normalize_tool_call_record(idx: int, tc: dict[str, str]) -> dict[str, str] | None:
    name = tc["name"].strip()
    if not name:
        logger.warning("[TOOLS] skipping incomplete tool call at index {} because function name is empty", idx)
        return None

    tool_call_id = tc["id"].strip() or f"call_{idx}"
    arguments = tc["arguments"].strip()
    if not arguments:
        logger.warning("[TOOLS] skipping incomplete tool call at index {} because arguments are empty", idx)
        return None

    try:
        parsed_arguments = json.loads(arguments)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[TOOLS] skipping incomplete tool call at index {} because arguments are not valid JSON: {}",
            idx,
            exc,
        )
        return None

    if not isinstance(parsed_arguments, dict):
        logger.warning(
            "[TOOLS] skipping incomplete tool call at index {} because arguments JSON is not an object",
            idx,
        )
        return None

    return {"id": tool_call_id, "name": name, "arguments": arguments}


def _ordered_complete_tool_calls(tool_calls_buf: dict[int, dict[str, str]]) -> list[dict[str, str]]:
    ordered: list[dict[str, str]] = []
    for idx in sorted(tool_calls_buf):
        normalized = _normalize_tool_call_record(idx, tool_calls_buf[idx])
        if normalized is not None:
            ordered.append(normalized)
    return ordered


def _should_execute_tool_calls(finish_reason: str | None, ordered_tool_calls: list[dict[str, str]]) -> bool:
    if not ordered_tool_calls:
        return False

    if finish_reason in (None, "tool_calls"):
        return True

    if finish_reason == "stop":
        logger.warning("[TOOLS] tool calls detected with finish_reason=stop; executing validated tool calls")
        return True

    if finish_reason in {"length", "content_filter"}:
        logger.warning(
            "[TOOLS] tool calls detected but skipping execution because finish_reason={} suggests incomplete output",
            finish_reason,
        )
        return False

    logger.warning(
        "[TOOLS] tool calls detected with non-standard finish_reason={}; skipping execution",
        finish_reason,
    )
    return False


def _stringify_tool_status_value(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = str(value)
    elif isinstance(value, str):
        text = " ".join(value.split())
    else:
        return None

    if not text:
        return None

    text = text.replace("[", "(").replace("]", ")")
    if len(text) > _MAX_TOOL_STATUS_VALUE_LEN:
        text = text[: _MAX_TOOL_STATUS_VALUE_LEN - 3] + "..."
    return text


def _extract_tool_status_args(tool_name: str, args_json: str) -> list[str]:
    if not args_json.strip():
        return []

    try:
        args = json.loads(args_json)
    except json.JSONDecodeError:
        return []

    if not isinstance(args, dict):
        return []

    preferred_keys = _TOOL_STATUS_ARG_KEYS.get(tool_name, _DEFAULT_TOOL_STATUS_ARG_KEYS)
    parts: list[str] = []

    for key in preferred_keys:
        if key not in args:
            continue
        value_text = _stringify_tool_status_value(args[key])
        if value_text is None:
            continue
        parts.append(f"{key}={value_text}")
        if len(parts) >= _MAX_TOOL_STATUS_FIELDS:
            break

    return parts


def _format_tool_status_token(tool_name: str, args_json: str = "") -> str:
    """Emit a display-only marker so the UI can show tool activity immediately."""
    name = tool_name.strip() or "tool"
    arg_parts = _extract_tool_status_args(name, args_json)
    suffix = f" {' '.join(arg_parts)}" if arg_parts else ""
    return f"<tool>[🔧 {name}{suffix}]</tool>"


format_tool_status_token = _format_tool_status_token


def _tool_result_to_text(result: ToolResult) -> str:
    return result.text if result.ok else f"Error: {result.error}"


def extract_tool_image_payload(tool_name: str, result: ToolResult) -> ImagePayload | None:
    if not result.ok or not isinstance(result.data, dict):
        return None

    data = result.data
    image_b64: str | None = None
    mime = "image/jpeg"

    try:
        if tool_name == "screen_shot":
            parsed = ScreenShotResult.model_validate(data)
            image_b64 = parsed.image_b64.strip()
            mime = parsed.mime
            logger.info(
                "[TOOL_IMAGE] screenshot tool returned image data: tool={} mime={} b64_len={}",
                tool_name,
                mime,
                len(image_b64),
            )
        else:
            raw_b64 = data.get("image_b64") or data.get("b64")
            if not isinstance(raw_b64, str) or not raw_b64.strip():
                return None
            image_b64 = raw_b64.strip()
            raw_mime = data.get("mime")
            if isinstance(raw_mime, str) and raw_mime.strip():
                mime = raw_mime.strip()
            logger.info(
                "[TOOL_IMAGE] tool returned image data: tool={} mime={} b64_len={}",
                tool_name,
                mime,
                len(image_b64),
            )
    except Exception as exc:  # pragma: no cover - defensive path
        logger.warning("[TOOL_IMAGE] failed to parse tool image payload for tool={}: {}", tool_name, exc)
        return None

    tool_image = ImagePayload(
        label=DEFAULT_TOOL_IMAGE_LABEL,
        b64=image_b64,
        mime=mime,
        source="tool",
    )
    logger.info(
        "[TOOL_IMAGE] tool_image handoff created: tool={} label={} source={} mime={}",
        tool_name,
        tool_image.label,
        tool_image.source,
        tool_image.mime,
    )
    return tool_image


class AgentCore:
    """统一封装 Agent 的 tool loop、vision 和 chat 主流程。"""

    def __init__(
        self,
        *,
        chat_llm: AsyncLLM,
        vision_llm: AsyncLLM | None,
        tool_manager: ToolManager | None,
        agent_context: AgentContext | None,
        context_injector: ContextInjector | None,
        storage: ConversationStorage,
        chat_system_prompt: str,
        vision_system_prompt: str = "",
        enable_tool: bool = False,
        max_vision_concurrency: int = 4,
        require_detailed: bool = True,
        hook_manager: HookManager | None = None,
    ) -> None:
        """初始化 AgentCore。

        Args:
            chat_llm: 最终回复使用的聊天模型。
            vision_llm: 图片摘要使用的视觉模型。
            tool_manager: 工具管理器。
            agent_context: 工具运行上下文。
            context_injector: 上下文注入器。
            storage: 会话存储抽象。
            chat_system_prompt: Chat 模型系统提示词。
            vision_system_prompt: Vision 模型系统提示词。
            enable_tool: 是否启用工具调用。
            max_vision_concurrency: Vision 摘要最大并发数。
            require_detailed: 是否启用逐图详细摘要。

        Returns:
            None。
        """
        self.chat_llm = chat_llm
        self.vision_llm = vision_llm
        self.tool_manager = tool_manager
        self.agent_context = agent_context
        self.context_injector = context_injector
        self.storage = storage
        self.chat_system_prompt = chat_system_prompt
        self.vision_system_prompt = vision_system_prompt
        self.enable_tool = enable_tool
        self.max_vision_concurrency = max_vision_concurrency
        self.require_detailed = require_detailed
        self._hook_manager = hook_manager
        self.chat_supports_vision = False
        self.write_back = True  # 设为 False 时 run_turn 不写回 storage（由外层调用方负责）

        self.state = ConversationState()
        self.msg = MessageFactory()
        self.prompt = PromptBuilder()
        self.vision = (
            VisionSummarizer(
                vision_llm=vision_llm,
                vision_system_prompt=vision_system_prompt,
                state=self.state,
                max_concurrency=max_vision_concurrency,
            )
            if vision_llm is not None
            else None
        )

    def _append_context_entry(self, base: ContextEntry | None, extra: ContextEntry) -> ContextEntry:
        if base is None:
            return extra

        full = f"{base.full}\n\n{extra.full}"
        if base.brief and extra.brief:
            brief = f"{base.brief}; {extra.brief}"
        else:
            brief = base.brief or extra.brief
        return self.prompt.make_context_entry(full, brief=brief)

    def _make_vision_failure_entry(
        self,
        *,
        source_kind: str,
        source_label: str,
        status: str,
        detail: str | None,
    ) -> ContextEntry:
        detail_text = detail or "No additional failure detail was returned."
        full = "\n".join(
            [
                "[Vision Failure State]",
                f"source={source_kind}",
                f"label={source_label}",
                f"status={status}",
                "- The screenshot/image was captured or provided, but vision analysis did not succeed.",
                "- There is not enough verified visual evidence to answer questions about the image content.",
                "- Do not pretend to have seen, read, or recognized anything inside the image.",
                "- Do not describe code content, window layout, people, model positions, screen regions, or small objects.",
                "- Do not treat 'screenshot captured' as 'image understood'.",
                "- If the user asks about the screenshot/image, explicitly say that you cannot analyze the screenshot content right now.",
                f"- failure_detail={detail_text}",
            ]
        )
        brief = f"Vision {status}; no verified {source_kind} content."
        return self.prompt.make_context_entry(full, brief=brief)

    def _inject_vision_failure_entry(
        self,
        base: ContextEntry | None,
        *,
        source_kind: str,
        source_label: str,
        status: str,
        detail: str | None,
    ) -> ContextEntry:
        logger.warning(
            "[VISION] anti-hallucination fallback injected: source={} label={} status={}",
            source_kind,
            source_label,
            status,
        )
        return self._append_context_entry(
            base,
            self._make_vision_failure_entry(
                source_kind=source_kind,
                source_label=source_label,
                status=status,
                detail=detail,
            ),
        )

    @staticmethod
    def _split_vision_outcomes(
        outcomes: dict[str, VisionAnalysisOutcome],
    ) -> tuple[dict[str, str], dict[str, str | None], dict[str, VisionAnalysisOutcome]]:
        successes = {label: outcome.summary for label, outcome in outcomes.items() if outcome.succeeded}
        briefs = {label: outcome.brief for label, outcome in outcomes.items() if outcome.succeeded}
        failures = {label: outcome for label, outcome in outcomes.items() if not outcome.succeeded}
        return successes, briefs, failures

    def _make_grouped_failure_entry(
        self,
        *,
        source_kind: str,
        outcomes: dict[str, VisionAnalysisOutcome],
    ) -> ContextEntry | None:
        if not outcomes:
            return None

        labels = ",".join(sorted(outcomes))
        statuses = ",".join(sorted({outcome.status for outcome in outcomes.values()}))
        detail = " | ".join(
            f"{label}:{outcome.status}:{outcome.detail or 'no_detail'}" for label, outcome in sorted(outcomes.items())
        )
        return self._make_vision_failure_entry(
            source_kind=source_kind,
            source_label=labels,
            status=statuses,
            detail=detail,
        )

    async def run_turn(
        self,
        *,
        user_text: str,
        user_images: list[ImagePayload] | None = None,
        memory_context: str | None = None,
    ) -> AsyncIterator[str | ToolCallEvent]:
        """运行一轮完整的 Agent 对话流程。

        Args:
            user_text: 用户输入文本。
            user_images: 用户上传图片列表。
            memory_context: 外部检索到的记忆上下文，由调用方负责检索后传入。

        Returns:
            流式输出的回复 token 和 tool call 事件（ToolCallEvent）。
        """
        history = self.storage.load()
        user_images = user_images or []
        tool_image = None

        if self._hook_manager is not None and self.agent_context is not None:
            hook_memory = await self._hook_manager.before_turn(user_text, self.agent_context)
            if hook_memory:
                memory_context = f"{memory_context}\n\n{hook_memory}" if memory_context else hook_memory

        # —— 背景上下文 ContextEntry（brief 由调用方提供；暂无则为 None）——
        mem_entry = self.prompt.make_context_entry(memory_context, brief=None) if memory_context else None

        # —— Vision summary ContextEntry ——
        vision_tool_entry: ContextEntry | None = None
        vision_upload_entry: ContextEntry | None = None

        if not self.chat_supports_vision:
            has_images = bool(user_images)
            if has_images and self.vision is None:
                logger.warning(
                    "[VISION] vision analysis unavailable: chat_supports_vision=false and no vision summarizer is available for uploaded images."
                )
                mem_entry = self._inject_vision_failure_entry(
                    mem_entry,
                    source_kind="uploaded image",
                    source_label="user_upload",
                    status="unavailable",
                    detail="chat_supports_vision=false and no vision summarizer is available for uploaded images.",
                )
            elif self.vision is not None and has_images:
                upload_outcomes = await self.vision.summarize_upload_images_by_mode(
                    user_input_text=user_text,
                    upload_images=[(img.b64, img.mime) for img in user_images],
                    require_detailed=self.require_detailed,
                )
                upload_summaries, upload_briefs, upload_failures = self._split_vision_outcomes(upload_outcomes)
                if upload_summaries:
                    vision_upload_entry = self.prompt.make_vision_upload_summary(
                        upload_summaries,
                        upload_briefs,
                    )
                grouped_failure = self._make_grouped_failure_entry(
                    source_kind="uploaded image",
                    outcomes=upload_failures,
                )
                if grouped_failure is not None:
                    logger.warning(
                        "[VISION] anti-hallucination fallback injected: source=uploaded image label={} status={}",
                        ",".join(sorted(upload_failures)),
                        ",".join(sorted({outcome.status for outcome in upload_failures.values()})),
                    )
                    mem_entry = self._append_context_entry(mem_entry, grouped_failure)

        # —— 组装 UserPromptBlock ——
        user_block = self.prompt.build(
            user_text=user_text,
            memory_context=mem_entry,
            vision_tool_summary=vision_tool_entry,
            vision_upload_summary=vision_upload_entry,
        )

        # —— 构建发往 LLM 的消息列表 ——
        rendered_user_content = user_block.render(condensed=False)

        if self.chat_supports_vision:
            if user_images:
                current_user_msg = self.msg.user_msg_with_labeled_images(rendered_user_content, user_images)
            else:
                current_user_msg = OpenAIMessage(role="user", content=rendered_user_content)
        else:
            current_user_msg = OpenAIMessage(role="user", content=rendered_user_content)

        final_messages: list[OpenAIMessage] = [*history, current_user_msg]
        tools_schema = self.tool_manager.list_tools_schema() if (self.enable_tool and self.tool_manager) else None
        last_tool_image_handoff_b64: str | None = None

        # —— 调用 chat LLM（原生 streaming tool-calling）——
        complete_response = ""
        max_rounds = 6

        for _ in range(max_rounds):
            text_buf = ""
            reasoning_buf = ""
            tool_calls_buf: dict[int, dict[str, str]] = {}
            finish_reason: str | None = None

            async for chunk in self.chat_llm.stream_with_tools(
                final_messages,
                system=self.chat_system_prompt,
                tools=tools_schema,
            ):
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta

                # Capture reasoning/thinking content for pass-back to API on next round.
                reasoning_content = getattr(delta, "reasoning_content", None)
                if reasoning_content:
                    reasoning_buf += reasoning_content

                if delta.content:
                    text_buf += delta.content
                    complete_response += delta.content
                    yield delta.content

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_buf:
                            tool_calls_buf[idx] = {"id": tc_delta.id or "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_calls_buf[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_buf[idx]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_buf[idx]["arguments"] += tc_delta.function.arguments

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

            ordered_tool_calls = _ordered_complete_tool_calls(tool_calls_buf)
            if ordered_tool_calls:
                assistant_payload: dict[str, Any] = {
                    "role": "assistant",
                    "content": text_buf or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                        for tc in ordered_tool_calls
                    ],
                }
                if reasoning_buf:
                    assistant_payload["reasoning_content"] = reasoning_buf
                assistant_msg = OpenAIMessage.model_validate(assistant_payload)
            else:
                assistant_msg = OpenAIMessage(
                    role="assistant",
                    content=text_buf or " ",
                    reasoning_content=reasoning_buf or None,
                )
            final_messages.append(assistant_msg)

            if not _should_execute_tool_calls(finish_reason, ordered_tool_calls):
                break

            tool_manager = self.tool_manager
            agent_context = self.agent_context
            if tool_manager is None or agent_context is None:
                break
            active_tool_manager = tool_manager
            active_agent_context = agent_context

            for tc in ordered_tool_calls:
                yield ToolCallEvent(
                    tool_id=tc["id"],
                    tool_name=tc["name"],
                    args=tc["arguments"],
                    status="running",
                )

            async def _exec_tool(
                tc_info: dict[str, str],
                bound_tool_manager: ToolManager,
                bound_agent_context: AgentContext,
            ) -> ToolResult:
                name = tc_info["name"]
                args_json = tc_info["arguments"]
                try:
                    return await bound_tool_manager.call_tool(name, args_json, bound_agent_context)
                except Exception as exc:  # pragma: no cover - defensive path
                    return ToolResult(ok=False, text="", error=f"tool_error: {type(exc).__name__}: {exc}")

            results = await asyncio.gather(
                *(_exec_tool(tc, active_tool_manager, active_agent_context) for tc in ordered_tool_calls)
            )

            for tc_info, result in zip(ordered_tool_calls, results, strict=False):
                tool_name = tc_info["name"]
                result_text = _tool_result_to_text(result)
                tool_msg = OpenAIMessage.model_validate(
                    {
                        "role": "tool",
                        "tool_call_id": tc_info["id"],
                        "content": result_text,
                        "name": tool_name,
                    }
                )
                final_messages.append(tool_msg)

                yield ToolCallEvent(
                    tool_id=tc_info["id"],
                    tool_name=tool_name,
                    args=tc_info["arguments"],
                    status="completed" if result.ok else "error",
                    result=result_text,
                )

                extracted_tool_image = extract_tool_image_payload(tool_name, result)
                if extracted_tool_image is not None:
                    tool_image = extracted_tool_image

            if tool_image is not None and tool_image.b64 != last_tool_image_handoff_b64:
                if self.chat_supports_vision:
                    final_messages.append(
                        self.msg.user_msg_with_labeled_images(
                            self.msg.tool_image_handoff_text(tool_image.label),
                            [tool_image],
                        )
                    )
                    last_tool_image_handoff_b64 = tool_image.b64
                    logger.info(
                        "[TOOL_IMAGE] tool_image attached to chat model: label={} mime={} source={}",
                        tool_image.label,
                        tool_image.mime,
                        tool_image.source,
                    )
                elif self.vision is not None:
                    logger.info(
                        "[TOOL_IMAGE] tool_image sent to vision summarizer: label={} mime={} source={}",
                        tool_image.label,
                        tool_image.mime,
                        tool_image.source,
                    )
                    tool_outcome = await self.vision.summarize_tool_image(
                        user_input_text=user_text,
                        tool_image=tool_image,
                    )
                    if tool_outcome.succeeded:
                        tool_entry = self.prompt.make_vision_tool_summary(
                            tool_outcome.summary,
                            brief=tool_outcome.brief,
                        )
                        vision_tool_entry = self._append_context_entry(vision_tool_entry, tool_entry)
                        summary_text = tool_entry.render(condensed=False)
                        if summary_text is not None:
                            final_messages.append(
                                OpenAIMessage(
                                    role="user",
                                    content=self.msg.tool_image_summary_handoff_text(tool_image.label, summary_text),
                                )
                            )
                            last_tool_image_handoff_b64 = tool_image.b64
                    else:
                        failure_entry = self._make_vision_failure_entry(
                            source_kind="screenshot",
                            source_label=tool_image.label,
                            status=tool_outcome.status,
                            detail=tool_outcome.detail,
                        )
                        vision_tool_entry = self._append_context_entry(vision_tool_entry, failure_entry)
                        failure_notice = failure_entry.render(condensed=False)
                        final_messages.append(
                            OpenAIMessage(
                                role="user",
                                content=self.msg.tool_image_failure_handoff_text(
                                    tool_image.label, failure_notice or ""
                                ),
                            )
                        )
                        last_tool_image_handoff_b64 = tool_image.b64
                        logger.warning(
                            "[VISION] anti-hallucination fallback injected: source=screenshot label={} status={}",
                            tool_image.label,
                            tool_outcome.status,
                        )
                else:
                    logger.warning(
                        "[VISION] vision analysis unavailable: chat_supports_vision=false and no vision summarizer is available for tool callback images."
                    )
                    logger.warning(
                        "[TOOL_IMAGE] tool image handoff blocked: chat_supports_vision=false and no vision summarizer"
                    )
                    failure_entry = self._make_vision_failure_entry(
                        source_kind="screenshot",
                        source_label=tool_image.label,
                        status="unavailable",
                        detail="chat_supports_vision=false and no vision summarizer is available for tool callback images.",
                    )
                    vision_tool_entry = self._append_context_entry(vision_tool_entry, failure_entry)
                    failure_notice = failure_entry.render(condensed=False)
                    final_messages.append(
                        OpenAIMessage(
                            role="user",
                            content=self.msg.tool_image_failure_handoff_text(tool_image.label, failure_notice or ""),
                        )
                    )
                    last_tool_image_handoff_b64 = tool_image.b64
                    logger.warning(
                        "[VISION] anti-hallucination fallback injected: source=screenshot label={} status={}",
                        tool_image.label,
                        "unavailable",
                    )

            tools_schema = active_tool_manager.list_tools_schema() if self.enable_tool else None

        # —— 写回存储 ——
        if self.write_back:
            user_block.vision_tool_summary = vision_tool_entry
            user_block.validate()
            self.storage.append_turn(user_block, complete_response)
        if self._hook_manager is not None and self.agent_context is not None:
            await self._hook_manager.after_turn(user_text, complete_response, self.agent_context)
