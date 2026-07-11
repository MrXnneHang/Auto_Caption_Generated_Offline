"""Visual Observer 插件。

游戏陪伴模式下后台定时截图 + RapidOCR 文字提取 + 累积变化触发 LLM 摘要，
输出 ctx.extra["visual_digest"] 供 mood_chat 使用。
"""

# ruff: noqa: PLE1205 — loguru {} 格式与标准 logging %s 冲突，属误报

from __future__ import annotations

import asyncio
import time
from collections import deque
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Annotated, Any

from loguru import logger
from pydantic import Field

from lab.plugin.config import PluginConfigModel
from lab.plugin.hook import HookPlugin

if TYPE_CHECKING:
    from PIL import Image as PILImage

    from lab.agent.stateless_llm.openai_compatible_llm import AsyncLLM
    from lab.tools.types import AgentContext

plugin_logger = logger.bind(group="visual_observer")

SUMMARY_SYSTEM_PROMPT = "你是游戏画面叙述者。用1-3句简洁中文概括最近画面中发生了什么。"


class VisualObserverPluginConfig(PluginConfigModel):
    poll_interval_s: Annotated[float, Field(1.0, ge=0.5, le=30.0, description="截图轮询间隔（秒）")]
    diff_ocr_threshold: Annotated[int, Field(20, ge=2, le=100, description="累积多少条新 OCR 后触发摘要")]
    ocr_max_items: Annotated[int, Field(10, ge=5, le=50, description="每帧保留面积最大的前 N 条 OCR")]
    ocr_min_confidence: Annotated[float, Field(0.6, ge=0.1, le=1.0, description="OCR 置信度过滤阈值")]
    ocr_min_length: Annotated[int, Field(2, ge=1, le=10, description="OCR 最短文字长度")]
    vision_boost: Annotated[bool, Field(False, description="触发摘要时同时发送最新截图给 VLM")]


PLUGIN_CONFIG_MODEL = VisualObserverPluginConfig


class VisualObserverPlugin(HookPlugin):
    """后台视觉轮询插件，由 game_companion_active 信号控制启停。"""

    def __init__(
        self,
        poll_interval_s: float = 1.0,
        diff_ocr_threshold: int = 20,
        ocr_max_items: int = 10,
        ocr_min_confidence: float = 0.6,
        ocr_min_length: int = 2,
        vision_boost: bool = False,
    ) -> None:
        self._poll_interval_s = poll_interval_s
        self._diff_ocr_threshold = diff_ocr_threshold
        self._ocr_max_items = ocr_max_items
        self._ocr_min_confidence = ocr_min_confidence
        self._ocr_min_length = ocr_min_length
        self._vision_boost = vision_boost

        # OCR state
        self._ocr_engine: Any = None
        self._ocr_history: deque[set[str]] = deque(maxlen=3)
        self._accumulated_new_ocr: list[str] = []
        self._accumulated_normalized: set[str] = set()
        self._new_ocr_count: int = 0
        self._scene_change_threshold = 5
        self._active_threshold = diff_ocr_threshold

        # Polling
        self._poll_task: asyncio.Task[None] | None = None
        self._poll_lock = asyncio.Lock()
        self._stopped = False
        self._total_captures = 0
        self._speaking = False
        self._latest_frame: Any = None

        # Summary / output
        self._summary_llm: AsyncLLM | None = None
        self._vision_llm: AsyncLLM | None = None
        self._chat_supports_vision: bool = False
        self._ctx: AgentContext | None = None
        self._agent_bound = False
        self._latest_summary: str | None = None
        self._session_history: list[dict[str, Any]] = []
        self._max_session_history = 5
        self._last_assistant_text: str = ""

    # ------------------------------------------------------------------
    # Public status
    # ------------------------------------------------------------------

    @property
    def observer_status(self) -> dict[str, Any]:
        digest = self._ctx.extra.get("visual_digest") if self._ctx else None
        seen: set[str] = set()
        for s in self._ocr_history:
            seen.update(s)
        return {
            "active": self._poll_task is not None and not self._poll_task.done(),
            "total_captures": self._total_captures,
            "pending_ocr_count": self._new_ocr_count,
            "ocr_threshold": self._active_threshold,
            "speaking": self._speaking,
            "accumulated_ocr": list(self._accumulated_new_ocr),
            "current_frame_ocr": sorted(seen),
            "latest_summary": self._latest_summary,
            "visual_digest": digest,
            "session_history": list(self._session_history),
        }

    # ------------------------------------------------------------------
    # Hook lifecycle
    # ------------------------------------------------------------------

    async def on_before_turn(self, user_text: str, ctx: AgentContext) -> str | None:
        del user_text
        self._ctx = ctx

        if not self._agent_bound:
            agent = ctx.extra.get("agent")
            if agent is not None:
                # 摘要是纯文本调用，优先用 chat LLM；vision LLM 作为 fallback
                self._summary_llm = getattr(agent.core, "chat_llm", None) or getattr(agent.core, "vision_llm", None)
                self._vision_llm = getattr(agent.core, "vision_llm", None)
                self._chat_supports_vision = getattr(agent.core, "chat_supports_vision", False)
                self._agent_bound = True

        if not ctx.extra.get("_mood_chat_internal_turn"):
            self._speaking = True

        return None

    async def on_after_turn(self, user_text: str, assistant_text: str, ctx: AgentContext) -> None:
        self._last_assistant_text = assistant_text or ""

        game_active = ctx.extra.get("game_companion_active", False)
        if game_active:
            self._start_polling()
        else:
            self._stop_polling()

    async def on_after_playback(self, user_text: str, assistant_text: str, ctx: AgentContext) -> None:
        self._speaking = False

    async def stop(self) -> None:
        self._stopped = True
        self._stop_polling()

    # ------------------------------------------------------------------
    # Polling control
    # ------------------------------------------------------------------

    def _start_polling(self) -> None:
        if self._poll_task is not None and not self._poll_task.done():
            return
        self._stopped = False
        self._poll_task = asyncio.create_task(self._run_poll_loop())
        plugin_logger.info("[VISUAL_OBSERVER] polling started: interval={}s", self._poll_interval_s)

    def _stop_polling(self) -> None:
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            plugin_logger.info("[VISUAL_OBSERVER] polling stopped")
        self._poll_task = None
        self._ocr_history.clear()
        self._clear_accumulated()
        self._active_threshold = self._diff_ocr_threshold

    async def _run_poll_loop(self) -> None:
        try:
            while not self._stopped:
                await asyncio.sleep(self._poll_interval_s)
                if self._stopped:
                    break
                asyncio.create_task(self._poll_once())
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Core: capture + OCR + diff + trigger
    # ------------------------------------------------------------------

    async def _poll_once(self) -> None:
        if self._poll_lock.locked():
            return
        async with self._poll_lock:
            try:
                from lab.plugins.screen_shot import ScreenShotPlugin

                frame = ScreenShotPlugin.capture()
            except Exception as exc:
                plugin_logger.debug("[VISUAL_OBSERVER] capture failed: {}", exc)
                return

            self._total_captures += 1
            if self._vision_boost:
                self._latest_frame = frame.pil_image

            if frame.pil_image is None:
                plugin_logger.debug("[VISUAL_OBSERVER] frame has no pil_image, skip OCR")
                return

            curr_ocr = await self._ocr_frame(frame.pil_image)

            if not self._ocr_history and self._total_captures == 1:
                self._ocr_history.append(curr_ocr)
                plugin_logger.info("[VISUAL_OBSERVER] initial frame: {} OCR items", len(curr_ocr))
                return

            seen: set[str] = set()
            for s in self._ocr_history:
                seen.update(s)
            new_texts = curr_ocr - seen
            self._ocr_history.append(curr_ocr)

            # Scene change detection: overlap ratio between current and history
            if len(curr_ocr) >= 3 and len(seen) >= 3:
                overlap = len(curr_ocr & seen) / max(len(curr_ocr), len(seen))
                if overlap < 0.3:
                    plugin_logger.info(
                        "[VISUAL_OBSERVER] scene change detected: overlap={:.0%}, clearing accumulated OCR",
                        overlap,
                    )
                    self._clear_accumulated()
                    self._active_threshold = self._scene_change_threshold

            if not new_texts:
                return

            if self._speaking:
                return

            if self._last_assistant_text:
                # Filter OCR text that overlaps the last assistant reply (>threshold).
                # Filtered items are NOT backfilled: Top-N already selects the
                # largest-area texts; N+1+ are small-area noise (buttons, clutter)
                # with little value. The accumulator reaches threshold (default 20)
                # a few frames later, which doesn't affect trigger frequency.
                filtered = {
                    t for t in new_texts if not self._is_similar_to_assistant_reply(t, self._last_assistant_text)
                }
                if len(filtered) < len(new_texts):
                    plugin_logger.debug(
                        "[VISUAL_OBSERVER] filtered {} OCR items similar to assistant reply",
                        len(new_texts) - len(filtered),
                    )
                new_texts = filtered
                if not new_texts:
                    return

            for text in sorted(new_texts):
                norm = self._strip_whitespace(text)
                if norm in self._accumulated_normalized:
                    continue
                self._accumulated_normalized.add(norm)
                self._accumulated_new_ocr.append(text)
                self._new_ocr_count += 1

            plugin_logger.debug(
                "[VISUAL_OBSERVER] frame #{}: +{} new OCR, accumulated={}",
                self._total_captures,
                len(new_texts),
                self._new_ocr_count,
            )

            if self._new_ocr_count >= self._active_threshold:
                await self._trigger_summary()

    # ------------------------------------------------------------------
    # OCR engine
    # ------------------------------------------------------------------

    def _get_ocr_engine(self) -> Any:
        if self._ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR  # Lazy-import

            self._ocr_engine = RapidOCR(use_cls=False, det_limit_side_len=736)
            plugin_logger.info("[VISUAL_OBSERVER] RapidOCR engine initialized (no_cls, det_limit=736)")
        return self._ocr_engine

    async def _ocr_frame(self, pil_image: PILImage.Image) -> set[str]:
        """在线程池中运行 OCR，按面积 Top-N 过滤，返回文字集合。"""
        import numpy as np

        w, h = pil_image.size
        max_ocr_size = 960
        if max(w, h) > max_ocr_size:
            factor = max_ocr_size / max(w, h)
            pil_image = pil_image.resize((int(w * factor), int(h * factor)))

        img_array = np.array(pil_image)
        engine = self._get_ocr_engine()

        loop = asyncio.get_event_loop()
        result, _elapse = await loop.run_in_executor(None, engine, img_array)

        if result is None:
            return set()

        def _box_area(item: tuple[Any, str, float]) -> float:
            box = item[0]
            import numpy as np

            box = np.array(box)
            xs = box[:, 0]
            ys = box[:, 1]
            return float((xs.max() - xs.min()) * (ys.max() - ys.min()))

        sorted_results = sorted(result, key=_box_area, reverse=True)
        top_results = sorted_results[: self._ocr_max_items]

        texts: set[str] = set()
        for _box, text, score in top_results:
            text = text.strip()
            if text and score >= self._ocr_min_confidence and len(text) >= self._ocr_min_length:
                texts.add(text)
        return texts

    def _clear_accumulated(self) -> None:
        self._accumulated_new_ocr.clear()
        self._accumulated_normalized.clear()
        self._new_ocr_count = 0

    @staticmethod
    def _strip_whitespace(text: str) -> str:
        return "".join(text.split())

    @staticmethod
    def _is_similar_to_assistant_reply(ocr_text: str, assistant_text: str, threshold: float = 0.5) -> bool:
        """Return True if OCR text largely overlaps the last assistant reply.

        Overlap ratio = matched_chars / len(normalized_ocr_text).
        Using per-OCR-text denominator avoids dilution when assistant_text
        is much longer than the OCR fragment.
        """
        ocr = "".join(ocr_text.split())
        assistant = "".join(assistant_text.split())
        if not ocr or not assistant:
            return False
        # Truncate long replies to avoid O(n*m) in the polling hot path.
        if len(assistant) > 2000:
            assistant = assistant[-2000:]
        matcher = SequenceMatcher(None, ocr, assistant, autojunk=False)
        matched = sum(block.size for block in matcher.get_matching_blocks())
        return (matched / len(ocr)) >= threshold

    # ------------------------------------------------------------------
    # Summary (LLM call)
    # ------------------------------------------------------------------

    async def _trigger_summary(self) -> None:
        summary = None
        if self._vision_boost and self._latest_frame is not None:
            if self._chat_supports_vision and self._summary_llm is not None:
                # chat_llm 自带视觉 → 直接用它，快（~2s），失败不 fallback
                summary = await self._call_vision_summary(self._summary_llm)
            elif self._vision_llm is not None:
                # chat_llm 纯文本 → 走 vision_llm，失败回退纯文本
                summary = await self._call_vision_summary(self._vision_llm)
        if summary is None:
            summary = await self._call_summary()
        if summary and self._ctx is not None:
            now = time.time()
            self._latest_summary = summary
            self._ctx.extra["visual_digest"] = {
                "text": summary,
                "accumulated_ocr": list(self._accumulated_new_ocr),
                "ocr_count": self._new_ocr_count,
                "ocr_threshold": self._active_threshold,
                "frame_count": self._total_captures,
                "timestamp": now,
            }
            self._session_history.append(
                {
                    "summary": summary,
                    "accumulated_ocr": list(self._accumulated_new_ocr),
                    "ocr_count": self._new_ocr_count,
                    "timestamp": now,
                }
            )
            if len(self._session_history) > self._max_session_history:
                self._session_history = self._session_history[-self._max_session_history :]
            plugin_logger.info(
                "[VISUAL_OBSERVER] summary triggered: ocr_count={} summary={}",
                self._new_ocr_count,
                summary[:80],
            )
            wake = self._ctx.extra.get("_game_proactive_wake")
            if wake is not None:
                assert callable(wake)
                asyncio.create_task(wake())

        self._clear_accumulated()
        self._active_threshold = self._diff_ocr_threshold

    async def _call_summary(self) -> str | None:
        if self._summary_llm is None or not self._accumulated_new_ocr:
            return None

        from lab.agent.types import OpenAIMessage

        ocr_text = "\n".join(f"- {line}" for line in self._accumulated_new_ocr)
        user_prompt = (
            f"以下是最近从游戏画面中提取的文字（按时间顺序）：\n{ocr_text}\n\n"
            '请概括最近发生了什么。过滤掉 UI 按钮文字（如"设置""返回""确认"等），'
            "保留剧情对话和关键信息。1-3句话，像在给朋友描述游戏里发生了什么。"
        )
        msgs = [
            OpenAIMessage(role="system", content=SUMMARY_SYSTEM_PROMPT),
            OpenAIMessage(role="user", content=user_prompt),
        ]

        try:
            raw = await self._summary_llm.vision_completion_once(messages=msgs, system=SUMMARY_SYSTEM_PROMPT)
        except Exception as exc:
            plugin_logger.warning("[VISUAL_OBSERVER] summary call failed: {}", exc)
            return None

        return raw.strip() if raw else None

    async def _call_vision_summary(self, llm: AsyncLLM) -> str | None:
        """用指定的 LLM 做图文结合摘要。llm 应为支持视觉的模型。"""
        assert self._latest_frame is not None
        if not self._accumulated_new_ocr:
            return None

        import base64
        import io

        from lab.agent.agents.memory_agent.message_factory import MessageFactory
        from lab.agent.types import OpenAIMessage

        # Convert latest frame to base64 JPEG
        buffer = io.BytesIO()
        self._latest_frame.save(buffer, "JPEG", quality=85)
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        ocr_text = "\n".join(f"- {line}" for line in self._accumulated_new_ocr)
        user_prompt = (
            f"以下是本轮从游戏画面中 OCR 提取的文字：\n{ocr_text}\n\n"
            "请结合实际截图画面，概括最近发生了什么。"
            '过滤掉 UI 按钮文字（如"设置""返回""确认"等），'
            "保留剧情对话和关键信息。1-3句话，像在给朋友描述游戏里发生了什么。"
        )
        user_msg = MessageFactory.user_msg_with_image_from_screen_shoot(text=user_prompt, b64=b64)
        msgs = [
            OpenAIMessage(role="system", content=SUMMARY_SYSTEM_PROMPT),
            user_msg,
        ]

        try:
            raw = await llm.vision_completion_once(messages=msgs, system=SUMMARY_SYSTEM_PROMPT)
        except Exception as exc:
            plugin_logger.warning("[VISUAL_OBSERVER] vision summary call failed, fallback to text: {}", exc)
            return None

        return raw.strip() if raw else None
