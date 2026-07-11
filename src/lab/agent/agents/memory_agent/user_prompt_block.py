from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

_SCHEMA_VERSION = 1
_BLOCK_MARKER = "__upb_v"  # content 前缀，用于区分结构化存储和旧纯文本
_SEP = "\n\n###\n\n"


@dataclass
class ContextEntry:
    """一条可衰减的上下文条目，持有完整版和可选的一句话简要版。

    Args:
        full: 完整版内容，超出保留轮数后被丢弃。
        brief: 一句话简要版；为 None 表示无法生成摘要，condensed 时整条被忽略。
    """

    full: str
    brief: str | None

    def validate(self) -> None:
        """校验 full 非空，若 brief 存在则不含换行。

        Raises:
            ValueError: full 为空，或 brief 包含换行符。
        """
        if not self.full.strip():
            raise ValueError("ContextEntry.full 不能为空")
        if self.brief is not None and "\n" in self.brief:
            raise ValueError(f"ContextEntry.brief 不能包含换行符，当前值：{self.brief!r}")

    def render(self, *, condensed: bool = False) -> str | None:
        """渲染为字符串。

        condensed=True 时：brief 存在则返回 brief，否则返回 None（调用方应忽略整条）。
        condensed=False 时：始终返回 full。

        Args:
            condensed: 为 True 时只保留 brief 版本。

        Returns:
            渲染后的字符串，或 None（condensed 且无 brief 时）。
        """
        if condensed:
            return self.brief  # 可能是 None
        return self.full

    def to_dict(self) -> dict[str, str | None]:
        """序列化为 dict。

        Returns:
            包含 full 和 brief 字段的字典。
        """
        return {"full": self.full, "brief": self.brief}

    @classmethod
    def from_dict(cls, d: dict[str, str | None]) -> ContextEntry:
        """从 dict 反序列化。

        Args:
            d: 包含 full 和 brief 字段的字典。

        Returns:
            ContextEntry 实例。
        """
        return cls(full=d["full"] or "", brief=d.get("brief"))


@dataclass
class UserPromptBlock:
    """一轮对话中用户侧的结构化 prompt，支持按需衰减冗余细节。

    三段式结构：
    - 背景块（Background）：memory_context
    - 用户输入块（User Input）：原始用户文本，永不衰减
    - 工作信息块（Working Context）：vision_tool_summary / vision_upload_summary

    Args:
        user_text: 原始用户输入文本，永不衰减。
        memory_context: 记忆检索上下文。
        vision_tool_summary: 工具截图的视觉摘要。
        vision_upload_summary: 用户上传图片的视觉摘要。
    """

    user_text: str
    memory_context: ContextEntry | None = field(default=None)
    vision_tool_summary: ContextEntry | None = field(default=None)
    vision_upload_summary: ContextEntry | None = field(default=None)

    # ------------------------------------------------------------------ #
    # 校验                                                                  #
    # ------------------------------------------------------------------ #

    def validate(self) -> None:
        """校验所有非 None 的 ContextEntry 字段。

        Raises:
            ValueError: 任意字段的 ContextEntry 校验失败，或 user_text 为空。
        """
        if not self.user_text.strip():
            raise ValueError("UserPromptBlock.user_text 不能为空")
        for attr in ("memory_context", "vision_tool_summary", "vision_upload_summary"):
            entry: ContextEntry | None = getattr(self, attr)
            if entry is not None:
                try:
                    entry.validate()
                except ValueError as exc:
                    raise ValueError(f"UserPromptBlock.{attr} 校验失败：{exc}") from exc

    # ------------------------------------------------------------------ #
    # 渲染                                                                  #
    # ------------------------------------------------------------------ #

    def render(self, *, condensed: bool = False) -> str:
        """将三段式结构渲染为 prompt 字符串。

        Args:
            condensed: 为 True 时所有 ContextEntry 只保留 brief，用于历史轮次压缩。

        Returns:
            可直接传给 LLM 的 prompt 字符串。
        """
        segments: list[str] = []

        # —— 背景块 ——
        bg_lines: list[str] = []
        if self.memory_context is not None:
            rendered = self.memory_context.render(condensed=condensed)
            if rendered is not None:
                bg_lines.append(f"[memory context]\n{rendered}\n[/memory context]")
        if bg_lines:
            segments.append("[Background Context]\n" + "\n\n".join(bg_lines))

        # —— 用户输入块 ——
        segments.append(f"[User Input]\n{self.user_text}")

        # —— 工作信息块 ——
        wk_lines: list[str] = []
        if self.vision_tool_summary is not None:
            rendered = self.vision_tool_summary.render(condensed=condensed)
            if rendered is not None:
                wk_lines.append(f"[Tool Call Image Summary]\n{rendered}")
        if self.vision_upload_summary is not None:
            rendered = self.vision_upload_summary.render(condensed=condensed)
            if rendered is not None:
                wk_lines.append(f"[User Upload Image Summary]\n{rendered}")
        if wk_lines:
            segments.append("[Working Context]\n" + "\n\n".join(wk_lines))

        return _SEP.join(segments)

    # ------------------------------------------------------------------ #
    # 序列化 / 反序列化                                                      #
    # ------------------------------------------------------------------ #

    def to_storage_content(self) -> str:
        """序列化为存储字符串（JSON envelope）。

        存储格式以 `__upb_v<version>:` 为前缀，接 JSON payload。
        读取时通过前缀区分新格式与旧纯文本，确保向后兼容。

        Returns:
            可写入 ConversationStore / MemoryStore 的字符串。
        """
        payload: dict[str, Any] = {
            "v": _SCHEMA_VERSION,
            "user_text": self.user_text,
        }
        for attr in ("memory_context", "vision_tool_summary", "vision_upload_summary"):
            entry: ContextEntry | None = getattr(self, attr)
            if entry is not None:
                payload[attr] = entry.to_dict()
        return f"{_BLOCK_MARKER}{_SCHEMA_VERSION}:" + json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_storage_content(cls, content: str) -> UserPromptBlock:
        """从存储字符串反序列化。

        Args:
            content: `to_storage_content()` 生成的字符串。

        Returns:
            UserPromptBlock 实例。

        Raises:
            ValueError: content 不是合法的 UserPromptBlock 存储格式。
        """
        prefix = f"{_BLOCK_MARKER}{_SCHEMA_VERSION}:"
        if not content.startswith(prefix):
            raise ValueError(f"content 不是 UserPromptBlock 格式（期望前缀 {prefix!r}）")
        payload = json.loads(content[len(prefix) :])
        kwargs: dict[str, Any] = {"user_text": payload["user_text"]}
        for attr in ("memory_context", "vision_tool_summary", "vision_upload_summary"):
            if attr in payload:
                kwargs[attr] = ContextEntry.from_dict(payload[attr])
        return cls(**kwargs)

    # ------------------------------------------------------------------ #
    # 辅助                                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_block_content(content: str) -> bool:
        """判断一个 content 字符串是否是 UserPromptBlock 格式。

        Args:
            content: 待检测字符串。

        Returns:
            True 表示是结构化格式，False 表示是旧纯文本。
        """
        return content.startswith(f"{_BLOCK_MARKER}{_SCHEMA_VERSION}:")
