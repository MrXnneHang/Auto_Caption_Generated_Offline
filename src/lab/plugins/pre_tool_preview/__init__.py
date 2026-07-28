from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from lab.plugin.config import PluginConfigModel
from lab.plugin.hook import PolicyPlugin
from lab.tools.plugin import PromptInjectionPosition, PromptSegment


class PreToolPreviewPluginConfig(PluginConfigModel):
    preview_max_chars: Annotated[int, Field(30, ge=10, le=80, description="工具调用前预告的最大字数")]
    preview_when_latency_over_ms: Annotated[
        int,
        Field(3000, ge=0, le=60000, description="仅在预计等待达到该毫秒数时更强地倾向输出预告"),
    ]
    allow_skip_on_user_request: Annotated[
        bool,
        Field(True, description="用户明确要求直接执行时是否允许跳过预告"),
    ]
    injection_position: Annotated[
        Literal["before_tools", "after_tools"],
        Field("before_tools", description="提示词注入位置，可选 before_tools 或 after_tools"),
    ]


PLUGIN_CONFIG_MODEL = PreToolPreviewPluginConfig


class PreToolPreviewPlugin(PolicyPlugin):
    def __init__(
        self,
        *,
        preview_max_chars: int = 30,
        preview_when_latency_over_ms: int = 3000,
        allow_skip_on_user_request: bool = True,
        injection_position: Literal["before_tools", "after_tools"] = "before_tools",
    ) -> None:
        self._preview_max_chars = preview_max_chars
        self._preview_when_latency_over_ms = preview_when_latency_over_ms
        self._allow_skip_on_user_request = allow_skip_on_user_request
        self._injection_position = PromptInjectionPosition(injection_position)

    def get_prompt_segments(self) -> list[PromptSegment]:
        lines = [
            "当你判断下一步需要调用任意工具或插件时，先向用户输出一条简短前置说明，再发起工具调用。",
            "这条规则对每一次工具调用都成立：本次回复里第二次、第三次调用工具时同样要先说一句，不要因为开头说过就一路沉默。",
            "前置说明必须面向用户可读，不要暴露内部工具名、函数名、插件标识、参数结构或系统实现细节。",
            "前置说明围绕你接下来要检查、搜索、读取或执行什么，不要提前承诺尚未确认的结果。",
            f"前置说明控制在 1 句话内，尽量不超过 {self._preview_max_chars} 个汉字，避免重复和寒暄。",
            "如果这不是本次回复的第一次工具调用，这句话要同时做两件事：用半句话交代上一步的结果，再说明接下来要做什么；不要重复上一条的措辞。",
            f"当任务预计等待可能达到约 {self._preview_when_latency_over_ms} 毫秒或更久时，更应优先给出前置说明或“请稍等”之类提示。",
            "输出前置说明后，再继续发起所需工具调用；不要把前置说明写成长段分析。",
        ]
        if self._allow_skip_on_user_request:
            lines.append("如果用户明确要求“直接执行”“别解释”或等价意图，可以跳过前置说明。")
        return [
            PromptSegment(
                name="工具调用前预告",
                content="\n".join(lines),
                priority=10,
                position=self._injection_position,
            )
        ]
