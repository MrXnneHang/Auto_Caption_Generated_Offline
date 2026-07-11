from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import TYPE_CHECKING, Any, cast

import httpx
from loguru import logger
from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError

from lab.agent.types import OpenAIMessage

from .message_factory import MessageFactory
from .types import ImagePayload, VisionAnalysisOutcome, VisionAnalysisStatus, VisionSummaryResult

if TYPE_CHECKING:
    from lab.agent.stateless_llm.openai_compatible_llm import AsyncLLM
    from lab.agent.types import ConversationState

_MAX_SINGLE_SUMMARY_LEN = 400


class VisionSummarizer:
    """vision_model 摘要服务：缓存、并发、解析、统一输出结构。"""

    def __init__(
        self,
        *,
        vision_llm: AsyncLLM,
        vision_system_prompt: str,
        state: ConversationState,
        max_concurrency: int = 3,
    ) -> None:
        self.vision_llm = vision_llm
        self.vision_system_prompt = vision_system_prompt
        self.state = state
        self.max_concurrency = max_concurrency

    @staticmethod
    def _snip(s: str, n: int = 1200) -> str:
        ss = (s or "").strip()
        if len(ss) <= n:
            return ss
        return ss[:n] + f"\n...(preview truncated, {len(ss)} chars total)..."

    @staticmethod
    def _img_ref_from_b64(b64: str, mime: str) -> str:
        """生成稳定 cache key，避免重复 summary。"""
        h = hashlib.sha1()
        h.update(mime.encode("utf-8"))
        h.update(str(len(b64)).encode("utf-8"))
        h.update(b64[:8192].encode("utf-8"))
        return h.hexdigest()

    @staticmethod
    def _failure(status: VisionAnalysisStatus, detail: str) -> VisionAnalysisOutcome:
        if status == "unavailable":
            logger.warning("[VISION] vision analysis unavailable: {}", detail)
        elif status in ("empty", "invalid"):
            logger.warning("[VISION] vision summary {}: {}", status, detail)
        else:
            logger.warning("[VISION] vision analysis failed: status={} detail={}", status, detail)
        return VisionAnalysisOutcome.failure(status, detail=detail)

    @staticmethod
    def _normalize_brief(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        brief = " ".join(value.strip().splitlines()).strip()
        return brief or None

    @classmethod
    def _parse_single_summary_json(cls, raw: str) -> tuple[str, str] | None:
        s = (raw or "").strip()
        if not s:
            return None

        if s.startswith("`"):
            s = re.sub(r"^`{3,}(?:json|JSON)?\s*\n?", "", s)
            s = re.sub(r"\n?`{3,}\s*$", "", s)
            s = s.strip()

        try:
            obj: dict[str, Any] = json.loads(s)
        except Exception:
            return None

        scene = obj.get("scene")
        if not isinstance(scene, str) or not scene.strip():
            return None

        # New compact format has no "summary" field; accept if scene + brief exist
        summary = obj.get("summary")
        if summary is not None:
            if not isinstance(summary, str) or not summary.strip():
                return None
            if len(summary.strip()) > _MAX_SINGLE_SUMMARY_LEN:
                return None

        brief = cls._normalize_brief(obj.get("brief"))
        if brief is None:
            brief = cls._normalize_brief(scene)
        if brief is None:
            return None
        return s, brief

    async def summarize_single(
        self,
        *,
        user_input: str,
        img_ref: str,
        b64: str,
        mime: str,
    ) -> VisionAnalysisOutcome:
        """对单张图做摘要（带缓存），仅接受可验证的 JSON 成功结果。"""
        cache_key = f"vision_summary::{img_ref}"
        cached = self.state.slots.get(cache_key)
        if isinstance(cached, str) and cached.strip():
            parsed = self._parse_single_summary_json(cached)
            if parsed is not None:
                full, brief = parsed
                return VisionAnalysisOutcome.success(summary=full, brief=brief)
            logger.warning("[VISION] cached vision summary invalid, cache_key={}", cache_key)
            self.state.slots.pop(cache_key, None)

        if not self.vision_llm:
            return self._failure("unavailable", "No vision model is configured for image analysis.")

        vision_system = self.vision_system_prompt
        msgs: list[OpenAIMessage] = [
            OpenAIMessage(role="system", content=vision_system),
            MessageFactory.user_msg_with_image_from_screen_shoot(
                f"用户问题：{user_input}\n请抽取与问题最相关的信息。",
                b64=b64,
                mime=mime,
            ),
        ]

        try:
            text_summary = await self.vision_llm.vision_completion_once(
                messages=msgs,
                system=vision_system,
            )
        except (TimeoutError, APITimeoutError, httpx.TimeoutException) as exc:
            return self._failure("timeout", f"{type(exc).__name__}: {exc}")
        except (APIError, APIConnectionError, RateLimitError) as exc:
            return self._failure("provider_error", f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            return self._failure("exception", f"{type(exc).__name__}: {exc}")

        text_summary = (text_summary or "").strip()
        if not text_summary:
            return self._failure("empty", f"Vision model returned empty output for img_ref={img_ref}.")

        parsed = self._parse_single_summary_json(text_summary)
        if parsed is None:
            return self._failure("invalid", f"Vision model returned non-parseable output for img_ref={img_ref}.")

        self.state.slots[cache_key] = text_summary
        logger.info("[VISION] cached vision summary for img_ref={}: {}", img_ref, self._snip(text_summary))
        full, brief = parsed
        return VisionAnalysisOutcome.success(summary=full, brief=brief)

    async def summarize_tool_image(
        self,
        *,
        user_input_text: str,
        tool_image: ImagePayload | None,
    ) -> VisionAnalysisOutcome:
        """tool 回调图像默认单张，返回显式 outcome。"""
        if not tool_image:
            return self._failure("invalid", "Tool image payload is missing.")
        if not self.vision_llm:
            return self._failure("unavailable", "No vision model is available for tool callback images.")

        img_ref = self._img_ref_from_b64(tool_image.b64, tool_image.mime)
        return await self.summarize_single(
            user_input=f"{user_input_text}\n(来源:tool_callback)",
            img_ref=img_ref,
            b64=tool_image.b64,
            mime=tool_image.mime,
        )

    async def summarize_upload_images_by_mode(
        self,
        *,
        user_input_text: str,
        upload_images: list[tuple[str, str]],
        require_detailed: bool,
    ) -> dict[str, VisionAnalysisOutcome]:
        """根据 require_detailed 选择逐图并发或一次多图。"""
        if not upload_images:
            return {}

        if not self.vision_llm:
            return {
                f"p{i + 1}": self._failure("unavailable", "No vision model is configured for uploaded images.")
                for i, _ in enumerate(upload_images)
            }

        if require_detailed:
            return await self._summaries_parallel(
                user_input=user_input_text,
                images=upload_images,
                prefix="p",
                max_concurrency=self.max_concurrency,
            )
        return await self._summaries_multi_once(
            user_input=user_input_text,
            images=upload_images,
            prefix="p",
        )

    async def summarize_all(
        self,
        *,
        user_input_text: str,
        tool_image: ImagePayload | None,
        upload_images: list[tuple[str, str]],
        require_detailed: bool,
    ) -> VisionSummaryResult:
        """统一入口：同时生成 tool + upload 的显式结果。"""
        tool_outcome = await self.summarize_tool_image(user_input_text=user_input_text, tool_image=tool_image)
        upload_outcomes = await self.summarize_upload_images_by_mode(
            user_input_text=user_input_text,
            upload_images=upload_images,
            require_detailed=require_detailed,
        )
        return VisionSummaryResult(tool_image=tool_outcome, upload_images=upload_outcomes)

    async def _summaries_parallel(
        self,
        *,
        user_input: str,
        images: list[tuple[str, str]],
        prefix: str,
        max_concurrency: int,
    ) -> dict[str, VisionAnalysisOutcome]:
        """逐图并发摘要。"""
        if not images or not self.vision_llm:
            return {}

        sem = asyncio.Semaphore(max_concurrency)

        async def _one(i: int, b64: str, mime: str) -> tuple[str, VisionAnalysisOutcome]:
            label = f"{prefix}{i + 1}"
            img_ref = self._img_ref_from_b64(b64, mime)
            async with sem:
                outcome = await self.summarize_single(
                    user_input=f"{user_input}\n(图像标签：{label})",
                    img_ref=img_ref,
                    b64=b64,
                    mime=mime,
                )
            return label, outcome

        tasks = [_one(i, b64, mime) for i, (b64, mime) in enumerate(images)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: dict[str, VisionAnalysisOutcome] = {}
        for i, item in enumerate(results):
            label = f"{prefix}{i + 1}"
            if isinstance(item, Exception):
                logger.exception("[VISION] {} 并发摘要失败：{}", label, item)
                out[label] = self._failure("exception", f"{label} parallel summarize exception: {item}")
                continue
            if not isinstance(item, tuple) or len(item) != 2:
                logger.error("[VISION] {} 并发摘要返回异常项：{}", label, item)
                out[label] = self._failure("invalid", f"{label} parallel summarize returned invalid structure.")
                continue

            _label, outcome = item
            if _label != label:
                logger.warning("[VISION] label 不一致：预期 {}，实际 {}", label, _label)
            out[label] = outcome

        return out

    async def _summaries_multi_once(
        self,
        *,
        user_input: str,
        images: list[tuple[str, str]],
        prefix: str,
    ) -> dict[str, VisionAnalysisOutcome]:
        """一次调用处理多图，返回 label -> outcome。"""
        if not images:
            return {}

        if not self.vision_llm:
            return {
                f"{prefix}{i + 1}": self._failure(
                    "unavailable", "No vision model is configured for multi-image analysis."
                )
                for i, _ in enumerate(images)
            }

        labeled_images = [
            ImagePayload(label=f"{prefix}{i + 1}", b64=b64, mime=mime, source="upload")
            for i, (b64, mime) in enumerate(images)
        ]

        instruction = (
            "你是一个视觉信息抽取器。请根据用户问题，对每张图片分别抽取与问题最相关的信息。\n"
            "要求：\n"
            "1) 必须按图片标签逐张输出，不要混在一起\n"
            "2) 输出必须是严格 JSON，不要 markdown，不要额外说明\n"
            '3) JSON 格式：{"items": [{"id": "p1", "scene": "一句话概述", "summary": "..."}, ...]}\n'
            "4) scene 和 summary 都必须是非空字符串\n"
        )

        msg = MessageFactory.user_msg_with_labeled_images(
            text=f"{instruction}\n用户问题：{user_input}",
            labeled_images=labeled_images,
        )

        msgs: list[OpenAIMessage] = [
            OpenAIMessage(role="system", content=self.vision_system_prompt),
            msg,
        ]

        try:
            raw = await self.vision_llm.vision_completion_once(
                messages=msgs,
                system=self.vision_system_prompt,
            )
        except (TimeoutError, APITimeoutError, httpx.TimeoutException) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            return {f"{prefix}{i + 1}": self._failure("timeout", detail) for i, _ in enumerate(images)}
        except (APIError, APIConnectionError, RateLimitError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            return {f"{prefix}{i + 1}": self._failure("provider_error", detail) for i, _ in enumerate(images)}
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            return {f"{prefix}{i + 1}": self._failure("exception", detail) for i, _ in enumerate(images)}

        raw = (raw or "").strip()
        if not raw:
            detail = "Vision model returned empty output for multi-image analysis."
            return {f"{prefix}{i + 1}": self._failure("empty", detail) for i, _ in enumerate(images)}

        return self._parse_labeled_summaries(raw, prefix=prefix, expected_count=len(images))

    @staticmethod
    def _parse_labeled_summaries(raw: str, *, prefix: str, expected_count: int) -> dict[str, VisionAnalysisOutcome]:
        """严格解析多图 JSON 输出；任何缺失或非法项都按失败处理。"""
        s = (raw or "").strip()
        if not s:
            return {
                f"{prefix}{i + 1}": VisionAnalysisOutcome.failure(
                    "empty",
                    detail="Vision model returned empty output for multi-image analysis.",
                )
                for i in range(expected_count)
            }

        try:
            parsed: dict[str, Any] = json.loads(s)
        except Exception:
            logger.warning("[VISION] vision summary invalid: multi-image output is not valid JSON.")
            return {
                f"{prefix}{i + 1}": VisionAnalysisOutcome.failure(
                    "invalid",
                    detail="Vision model returned non-JSON output for multi-image analysis.",
                )
                for i in range(expected_count)
            }

        items = parsed.get("items")
        if not isinstance(items, list):
            logger.warning("[VISION] vision summary invalid: multi-image JSON missing items array.")
            return {
                f"{prefix}{i + 1}": VisionAnalysisOutcome.failure(
                    "invalid",
                    detail="Vision model returned JSON without a valid items array.",
                )
                for i in range(expected_count)
            }

        by_label: dict[str, VisionAnalysisOutcome] = {}
        for it in cast("list[object]", items):
            if not isinstance(it, dict):
                continue
            it_typed = cast("dict[str, Any]", it)
            raw_id = it_typed.get("id")
            raw_summary = it_typed.get("summary")
            raw_scene = it_typed.get("scene")
            if not isinstance(raw_id, str) or not raw_id.strip():
                continue

            label = raw_id.strip()
            if (
                not isinstance(raw_scene, str)
                or not raw_scene.strip()
                or not isinstance(raw_summary, str)
                or not raw_summary.strip()
            ):
                by_label[label] = VisionAnalysisOutcome.failure(
                    "invalid",
                    detail=f"Vision model returned incomplete JSON for label={label}.",
                )
                continue

            brief = VisionSummarizer._normalize_brief(it_typed.get("brief"))
            if brief is None:
                brief = VisionSummarizer._normalize_brief(raw_scene)
            if brief is None:
                by_label[label] = VisionAnalysisOutcome.failure(
                    "invalid",
                    detail=f"Vision model returned invalid brief for label={label}.",
                )
                continue

            item_for_storage = dict(it_typed)
            item_for_storage["id"] = label
            item_for_storage["scene"] = raw_scene.strip()
            item_for_storage["summary"] = raw_summary.strip()
            if "brief" in item_for_storage:
                item_for_storage["brief"] = brief

            by_label[label] = VisionAnalysisOutcome.success(
                summary=json.dumps(item_for_storage, ensure_ascii=False),
                brief=brief,
            )

        out: dict[str, VisionAnalysisOutcome] = {}
        for i in range(expected_count):
            label = f"{prefix}{i + 1}"
            if label in by_label:
                out[label] = by_label[label]
                continue
            logger.warning("[VISION] vision summary invalid: missing labeled item {}", label)
            out[label] = VisionAnalysisOutcome.failure(
                "invalid",
                detail=f"Vision model did not return a valid entry for {label}.",
            )
        return out
