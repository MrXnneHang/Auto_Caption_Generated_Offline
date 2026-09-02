"""MoodChat 主动对话插件。

该模块提供一个基于心情分数的 HookPlugin，在用户长时间没有继续对话时，
按当前心情状态主动触发一轮对话，并在用户回应、超时未回应和自然回归之间
调整内部心情值。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, cast

from loguru import logger
from pydantic import Field

from lab.agent.input_types import BatchInput, TextData, TextSource
from lab.agent.output_types import SentenceOutput, ToolCallEvent
from lab.conversations.conversation_utils import (
    create_turn_id,
    process_agent_output,
    send_conversation_end_signal,
    send_conversation_start_signals_for_turn,
    send_tool_call_event,
    wait_for_frontend_playback_completion,
)
from lab.conversations.tts_manager import TTSTaskManager
from lab.message_handler import message_handler
from lab.plugin.config import PluginConfigModel
from lab.plugin.hook import HookPlugin

if TYPE_CHECKING:
    from lab.agent.agents.memory_agent.agent import MemoryAgent
    from lab.conversations.types import WebSocketSend
    from lab.service_context import ServiceContext
    from lab.tools.types import AgentContext


plugin_logger = logger.bind(group="dialog")


@dataclass
class _ProactiveRuntimeContext:
    websocket_send: WebSocketSend
    service_context: ServiceContext
    client_uid: str


class MoodChatPluginConfig(PluginConfigModel):
    """MoodChatPlugin 的可视化配置模型。

    该配置模型用于为 admin/web-tool 生成逐字段可编辑的插件表单，并约束
    主动对话提示词、心情阈值、时间间隔和心情增减规则的取值范围。
    """

    prompt: Annotated[
        str,
        Field(
            "\u8bf7\u6839\u636e\u4e0a\u4e0b\u6587\uff0c\u4e3b\u52a8\u8bf4\u4e9b\u4ec0\u4e48\u3002",
            description="主动对话时发送给 agent 的提示词",
        ),
    ]
    initial_mood: Annotated[int, Field(80, ge=0, le=100, description="启动后的初始心情分")]
    target_mood: Annotated[int, Field(80, ge=0, le=100, description="心情自然回归的目标分数")]
    response_timeout_s: Annotated[float, Field(10.0, ge=0.0, description="主动发言后等待用户回应的超时时间（秒）")]
    interval_excited_s: Annotated[float, Field(5.0, ge=0.0, description="心情 >= 90 时的主动发言间隔（秒）")]
    interval_normal_s: Annotated[float, Field(30.0, ge=0.0, description="心情 >= 80 时的主动发言间隔（秒）")]
    interval_low_s: Annotated[float, Field(120.0, ge=0.0, description="心情 >= 60 时的主动发言间隔（秒）")]
    mood_increase: Annotated[int, Field(5, ge=0, le=100, description="用户发言后增加的心情分")]
    mood_decrease: Annotated[int, Field(10, ge=0, le=100, description="主动发言后超时未回应时扣除的心情分")]
    game_companion_mode: Annotated[bool, Field(False, description="启用游戏陪伴模式")]
    game_mood_decrease: Annotated[int, Field(2, ge=0, le=100, description="游戏模式下超时扣除的心情分")]
    game_interval_s: Annotated[
        float, Field(1.0, ge=0.5, description="游戏模式下检查视觉摘要的间隔（秒），有摘要才发言")
    ]
    game_prompt_suffix: Annotated[
        str,
        Field(
            "根据视觉摘要简短评论，不超过两句话。不要提问。",
            description="游戏模式下追加到 prompt 的后缀",
        ),
    ]
    game_require_visual_change: Annotated[bool, Field(True, description="游戏模式下是否要求有视觉变化才发言")]


PLUGIN_CONFIG_MODEL = MoodChatPluginConfig


class MoodChatPlugin(HookPlugin):
    """基于心情分数调度主动对话的 Hook 插件。

    插件会在首次真实用户回合时绑定当前 agent，并启动两个后台任务：
    一个根据心情值决定是否主动发话，另一个让心情缓慢回归到目标值。

    同一进程内只允许存在一个 MoodChatPlugin 实例。尝试创建第二个实例时会立即
    抛出 RuntimeError，以防止多实例并发运行时 ctx.extra flag 冲突导致难以排查的 bug。

    Attributes:
        mood_score: 当前心情分，范围为 0 到 100。
    """

    _instance_count: int = 0

    def __init__(
        self,
        prompt: str = "\u8bf7\u6839\u636e\u4e0a\u4e0b\u6587\uff0c\u4e3b\u52a8\u8bf4\u4e9b\u4ec0\u4e48\u3002",
        initial_mood: int = 80,
        target_mood: int = 80,
        response_timeout_s: float = 10.0,
        interval_excited_s: float = 5.0,
        interval_normal_s: float = 30.0,
        interval_low_s: float = 120.0,
        mood_increase: int = 5,
        mood_decrease: int = 10,
        game_companion_mode: bool = False,
        game_mood_decrease: int = 2,
        game_interval_s: float = 1.0,
        game_prompt_suffix: str = "根据视觉摘要简短评论，不超过两句话。不要提问。",
        game_require_visual_change: bool = True,
    ) -> None:
        """初始化主动对话插件。

        Args:
            prompt: 主动发话时伪造给 agent 的输入文本。
            initial_mood: 插件启动后的初始心情分。
            target_mood: 心情自然漂移时要回归到的目标分数。
            response_timeout_s: 主动发话结束后等待用户回应的超时时间，单位为秒。
            interval_excited_s: 心情大于等于 90 时的主动发话间隔，单位为秒。
            interval_normal_s: 心情大于等于 80 时的主动发话间隔，单位为秒。
            interval_low_s: 心情大于等于 60 时的主动发话间隔，单位为秒。
            mood_increase: 用户真实发言后增加的心情分。
            mood_decrease: 主动发话后超时未得到用户回应时减少的心情分。

        Raises:
            RuntimeError: 当进程内已存在一个 MoodChatPlugin 实例时抛出。
        """
        if MoodChatPlugin._instance_count > 0:
            raise RuntimeError(
                "MoodChatPlugin 不支持多实例：进程内已存在一个 MoodChatPlugin 实例。"
                "请检查 profile 配置，确保 mood_chat 只被启用一次。"
            )
        MoodChatPlugin._instance_count += 1
        self._prompt = prompt
        self._target_mood = self._clamp_mood(target_mood)
        self._response_timeout_s = response_timeout_s
        self._interval_excited_s = interval_excited_s
        self._interval_normal_s = interval_normal_s
        self._interval_low_s = interval_low_s
        self._mood_increase = mood_increase
        self._mood_decrease = mood_decrease
        self._game_companion_mode = game_companion_mode
        self._game_mood_decrease = game_mood_decrease
        self._game_interval_s = game_interval_s
        self._game_prompt_suffix = game_prompt_suffix
        self._game_require_visual_change = game_require_visual_change

        self._mood_score = self._clamp_mood(initial_mood)
        self._mood_lock = asyncio.Lock()
        self._startup_lock = asyncio.Lock()

        self._agent: MemoryAgent | None = None
        self._ctx: AgentContext | None = None
        self._proactive_timer_task: asyncio.Task[None] | None = None
        self._mood_drift_task: asyncio.Task[None] | None = None
        self._response_timeout_task: asyncio.Task[None] | None = None
        self._active_turn_task: asyncio.Task[bool] | None = None

        self._internal_turn_flag = "_mood_chat_internal_turn"
        self._external_turn_active = False
        self._stopped = False

    @property
    def mood_score(self) -> int:
        """返回当前心情分。"""
        return self._mood_score

    async def on_before_turn(self, user_text: str, ctx: AgentContext) -> str | None:
        """在每轮对话开始前更新插件状态。

        真实用户回合进入时会确保后台任务已启动，取消正在等待的回应超时计时，
        并将当前心情分上调；若当前回合是插件内部主动触发的回合，则跳过加分逻辑。

        Args:
            user_text: 当前回合的用户输入文本。
            ctx: 当前 agent 的运行时上下文。

        Returns:
            可注入到主对话中的额外上下文。该插件不注入额外文本，因此返回 `None`。
        """
        del user_text
        await self._ensure_started(ctx)

        ctx.extra["game_companion_active"] = self._game_companion_mode

        if ctx.extra.get(self._internal_turn_flag):
            return None

        self._external_turn_active = True
        self._cancel_response_timeout()
        self._cancel_proactive_timer()
        await self._cancel_active_turn()
        await self._change_mood(self._mood_increase)
        return None

    async def on_after_turn(self, user_text: str, assistant_text: str, ctx: AgentContext) -> None:
        """在每轮对话结束后执行收尾逻辑。

        MoodChatPlugin 不需要在回合结束时额外写入记忆或修改状态，因此这里保留为空实现。

        Args:
            user_text: 当前回合的用户输入文本。
            assistant_text: 当前回合的助手输出文本。
            ctx: 当前 agent 的运行时上下文。
        """
        del user_text, assistant_text, ctx
        return

    async def on_after_playback(self, user_text: str, assistant_text: str, ctx: AgentContext) -> None:
        del user_text, assistant_text
        if not ctx.extra.get(self._internal_turn_flag):
            self._external_turn_active = False
            self._arm_proactive_timer()
        return

    async def stop(self) -> None:
        """停止插件内部的所有后台任务。

        该方法会取消主动调度任务、心情漂移任务、当前主动发话任务以及等待回应超时任务，
        以确保 agent 关闭或运行时切换时不会遗留悬空任务。
        """
        self._stopped = True
        MoodChatPlugin._instance_count = max(0, MoodChatPlugin._instance_count - 1)
        if self._ctx is not None:
            self._ctx.extra.pop(self._internal_turn_flag, None)

        tasks: list[asyncio.Task[Any]] = []
        for task in (
            self._response_timeout_task,
            self._active_turn_task,
            self._proactive_timer_task,
            self._mood_drift_task,
        ):
            if task is not None and not task.done():
                tasks.append(task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._response_timeout_task = None
        self._active_turn_task = None
        self._proactive_timer_task = None
        self._mood_drift_task = None
        self._external_turn_active = False

    async def _cancel_active_turn(self) -> None:
        task = self._active_turn_task
        if task is None or task.done():
            self._active_turn_task = None
            return

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if self._active_turn_task is task:
            self._active_turn_task = None

    async def _ensure_started(self, ctx: AgentContext) -> None:
        async with self._startup_lock:
            self._ctx = ctx
            agent = ctx.extra.get("agent")
            if agent is None:
                return
            self._agent = agent
            self._stopped = False

            if self._mood_drift_task is None or self._mood_drift_task.done():
                self._mood_drift_task = asyncio.create_task(self._run_mood_drift())

    async def _run_proactive_cycle(
        self,
        *,
        agent: MemoryAgent,
        ctx: AgentContext,
        mood: int,
        interval: float,
    ) -> bool:
        plugin_logger.info(
            f"[MOOD_CHAT] proactive chat triggered: mood={mood} interval_s={interval} prompt={self._prompt}"
        )

        interrupt_task: asyncio.Task[dict[Any, Any] | None] | None = None
        client_uid = self._get_client_uid(ctx)
        if client_uid is not None:
            message_handler.clear_pending_messages(client_uid, "interrupt-signal")
            interrupt_task = asyncio.create_task(message_handler.wait_for_response(client_uid, "interrupt-signal"))

        turn_task = asyncio.create_task(self._run_proactive_turn(agent=agent, ctx=ctx))
        self._active_turn_task = turn_task

        try:
            if interrupt_task is None:
                return await turn_task

            done, pending = await asyncio.wait(
                {turn_task, interrupt_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if interrupt_task in done and interrupt_task.result():
                plugin_logger.info(f"[MOOD_CHAT] proactive chat interrupted by user: client_uid={client_uid}")
                turn_task.cancel()
                await asyncio.gather(turn_task, return_exceptions=True)
                return True

            for pending_task in pending:
                pending_task.cancel()
            if interrupt_task in pending:
                await asyncio.gather(interrupt_task, return_exceptions=True)

            return await turn_task
        finally:
            if interrupt_task is not None and not interrupt_task.done():
                interrupt_task.cancel()
                await asyncio.gather(interrupt_task, return_exceptions=True)
            if self._active_turn_task is turn_task:
                self._active_turn_task = None

    async def _run_proactive_turn(self, *, agent: MemoryAgent, ctx: AgentContext) -> bool:
        if self._game_companion_mode:
            visual_digest = ctx.extra.get("visual_digest")
            if self._game_require_visual_change and not visual_digest:
                plugin_logger.debug("[MOOD_CHAT] game mode: no visual change, skipping proactive turn")
                return False
            digest_text = visual_digest.get("text", "") if visual_digest else ""
            digest_ocr: list[str] = visual_digest.get("accumulated_ocr", []) if visual_digest else []
            digest_count = visual_digest.get("ocr_count", 0) if visual_digest else 0
            digest_threshold = visual_digest.get("ocr_threshold", 0) if visual_digest else 0
            if digest_ocr:
                ocr_preview = "原文片段：\n" + "\n".join(f"  · {line}" for line in digest_ocr[-3:])
            else:
                ocr_preview = ""
            prompt_text = (
                (
                    f"[视觉轮询 - {digest_count}/{digest_threshold}]\n"
                    f"摘要：{digest_text}\n"
                    f"{ocr_preview}\n\n"
                    f"{self._game_prompt_suffix}"
                )
                if digest_text
                else self._game_prompt_suffix
            )
            ctx.extra.pop("visual_digest", None)
        else:
            prompt_text = self._prompt

        fake_input = BatchInput(
            texts=[TextData(source=TextSource.INPUT, content=prompt_text)],
        )
        ctx.extra[self._internal_turn_flag] = True

        runtime = self._get_runtime_context(ctx)
        try:
            if runtime is None:
                async for _ in agent.chat(fake_input):
                    pass
                return False

            turn_id = create_turn_id()
            tts_manager = TTSTaskManager(turn_id=turn_id, lab_setting=runtime.service_context.lab_setting)
            await send_conversation_start_signals_for_turn(
                runtime.websocket_send,
                turn_id,
                service_context=runtime.service_context,
            )
            try:
                async for output in agent.chat(fake_input):
                    if isinstance(output, ToolCallEvent):
                        await send_tool_call_event(output, runtime.websocket_send, runtime.service_context)
                        continue
                    if not isinstance(output, SentenceOutput):
                        continue
                    await process_agent_output(
                        output=output,
                        lab_settings=runtime.service_context.lab_setting,
                        character_config=runtime.service_context.character_config,
                        live2d_model=runtime.service_context.live2d_model,
                        service_context=runtime.service_context,
                        websocket_send=runtime.websocket_send,
                        tts_manager=tts_manager,
                        translate_engine=runtime.service_context.translate_engine,
                    )

                tts_manager_any: Any = tts_manager
                raw_tts_tasks: Any = tts_manager_any.task_list
                tts_tasks = cast("list[asyncio.Task[Any]]", raw_tts_tasks)
                if tts_manager.has_output():
                    if tts_tasks:
                        plugin_logger.debug(
                            f"[MOOD_CHAT] waiting for queued payloads to reach frontend: count={len(tts_tasks)}"
                        )
                    await tts_manager.wait_until_all_payloads_sent()
                    await runtime.websocket_send(json.dumps({"type": "backend-synth-complete", "turn_id": turn_id}))
                    playback_timeout = tts_manager.playback_completion_timeout_s()
                    response = await wait_for_frontend_playback_completion(
                        runtime.client_uid,
                        turn_id=turn_id,
                        timeout=playback_timeout,
                    )
                    if not response:
                        plugin_logger.warning(
                            f"[MOOD_CHAT] no frontend playback completion response: "
                            f"client_uid={runtime.client_uid} timeout_s={playback_timeout:.2f}; continuing"
                        )

                await runtime.websocket_send(json.dumps({"type": "force-new-message"}))
                await send_conversation_end_signal(
                    runtime.websocket_send,
                    None,
                    service_context=runtime.service_context,
                )
                return False
            finally:
                tts_manager.clear()
        finally:
            ctx.extra.pop(self._internal_turn_flag, None)

    def _cancel_proactive_timer(self) -> None:
        task = self._proactive_timer_task
        if task is not None and not task.done():
            task.cancel()
        self._proactive_timer_task = None

    def _arm_proactive_timer(self) -> None:
        if self._stopped or self._external_turn_active or self._active_turn_task is not None:
            return

        agent = self._agent
        ctx = self._ctx
        if agent is None or ctx is None:
            return

        mood = self._mood_score
        interval = self._interval_for_mood(mood)
        if interval is None:
            plugin_logger.info(f"[MOOD_CHAT] proactive chat paused: mood={mood} next_interval=paused")
            return

        self._cancel_proactive_timer()
        self._proactive_timer_task = asyncio.create_task(
            self._run_proactive_timer(agent=agent, ctx=ctx, mood=mood, interval=interval)
        )

    async def _run_proactive_timer(
        self,
        *,
        agent: MemoryAgent,
        ctx: AgentContext,
        mood: int,
        interval: float,
    ) -> None:
        current_task = asyncio.current_task()
        try:
            await asyncio.sleep(interval)
            if self._stopped or self._external_turn_active or self._active_turn_task is not None:
                return

            interrupted = await self._run_proactive_cycle(
                agent=agent,
                ctx=ctx,
                mood=mood,
                interval=interval,
            )
            if interrupted or self._stopped:
                return

            if self._proactive_timer_task is current_task:
                self._proactive_timer_task = None
            self._start_response_timeout()
            self._arm_proactive_timer()
        except asyncio.CancelledError:
            raise
        except Exception:
            plugin_logger.exception("[MOOD_CHAT] proactive turn failed")
            if self._proactive_timer_task is current_task:
                self._proactive_timer_task = None
            if not self._stopped:
                self._arm_proactive_timer()
        finally:
            if self._proactive_timer_task is current_task:
                self._proactive_timer_task = None

    async def _run_mood_drift(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                current_mood = await self._get_mood_score()
                if current_mood < self._target_mood:
                    await self._change_mood(1)
                elif current_mood > self._target_mood:
                    await self._change_mood(-1)
        except asyncio.CancelledError:
            return

    async def _handle_response_timeout(self) -> None:
        await asyncio.sleep(self._response_timeout_s)
        penalty = self._game_mood_decrease if self._game_companion_mode else self._mood_decrease
        await self._change_mood(-penalty)
        if not self._external_turn_active and self._active_turn_task is None:
            self._arm_proactive_timer()

    async def _get_mood_score(self) -> int:
        async with self._mood_lock:
            return self._mood_score

    async def _change_mood(self, delta: int) -> None:
        async with self._mood_lock:
            self._mood_score = self._clamp_mood(self._mood_score + delta)
            current_mood = self._mood_score
        interval = self._interval_for_mood(current_mood)
        interval_text = f"{interval}s" if interval is not None else "paused"
        plugin_logger.info(
            f"[MOOD_CHAT] mood changed: delta={delta:+d} mood={current_mood} proactive_interval={interval_text}"
        )
        await self._publish_mood_update(current_mood)

    async def _publish_mood_update(self, mood_score: int | None = None) -> None:
        ctx = self._ctx
        if ctx is None:
            return

        websocket_send = ctx.extra.get("websocket_send")
        if not callable(websocket_send):
            return

        score = self._clamp_mood(self._mood_score if mood_score is None else mood_score)
        try:
            await cast("WebSocketSend", websocket_send)(json.dumps({"type": "mood-update", "score": score}))
        except Exception as exc:
            plugin_logger.warning(f"[MOOD_CHAT] failed to publish mood update: score={score} error={exc}")

    def _cancel_response_timeout(self) -> None:
        task = self._response_timeout_task
        if task is not None and not task.done():
            task.cancel()
        self._response_timeout_task = None

    def _start_response_timeout(self) -> None:
        self._cancel_response_timeout()
        self._response_timeout_task = asyncio.create_task(self._handle_response_timeout())

    def _interval_for_mood(self, mood_score: int) -> float | None:
        if self._game_companion_mode:
            return self._game_interval_s
        if mood_score >= 90:
            return self._interval_excited_s
        if mood_score >= 80:
            return self._interval_normal_s
        if mood_score >= 60:
            return self._interval_low_s
        return None

    @staticmethod
    def _clamp_mood(value: Any) -> int:
        return max(0, min(100, int(value)))

    @staticmethod
    def _get_client_uid(ctx: AgentContext) -> str | None:
        client_uid = ctx.extra.get("client_uid")
        return client_uid if isinstance(client_uid, str) and client_uid else None

    @staticmethod
    def _get_runtime_context(
        ctx: AgentContext,
    ) -> _ProactiveRuntimeContext | None:
        websocket_send = ctx.extra.get("websocket_send")
        service_context = ctx.extra.get("service_context")
        client_uid = ctx.extra.get("client_uid")
        if not callable(websocket_send):
            return None
        if not isinstance(client_uid, str) or not client_uid:
            return None
        if service_context is None:
            return None
        return _ProactiveRuntimeContext(
            websocket_send=cast("WebSocketSend", websocket_send),
            service_context=cast("ServiceContext", service_context),
            client_uid=client_uid,
        )
