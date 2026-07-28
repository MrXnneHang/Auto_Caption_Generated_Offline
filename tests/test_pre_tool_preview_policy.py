from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from lab.plugin.loader import PluginLoader
from lab.plugins.pre_tool_preview import PreToolPreviewPlugin
from lab.profile.system_prompt_builder import SystemPromptBuilder
from lab.tools import GetDatetimeTool, ToolManager

if TYPE_CHECKING:
    from pathlib import Path


def test_pre_tool_preview_plugin_loads_as_policy() -> None:
    plugin = asyncio.run(PluginLoader().load("pre_tool_preview"))

    assert isinstance(plugin, PreToolPreviewPlugin)
    segments = plugin.get_prompt_segments()
    assert len(segments) == 1
    assert segments[0].name == "工具调用前预告"


def test_preview_rule_is_not_scoped_to_the_first_tool_call() -> None:
    """「本轮首次」易被理解成一个用户 turn 只预告一次，长 tool 链因此从第二步起失声。

    这里禁掉整个「本轮」而不只是「本轮首次」：歧义出在「轮」这个单位上（用户 turn
    还是一次 LLM call），换成「本轮每一次」之类的说法同样会把歧义带回来。要指代
    单次 LLM call，请统一用「本次回复」。
    """
    content = PreToolPreviewPlugin().get_prompt_segments()[0].content

    assert "本轮" not in content
    assert "每一次工具调用都成立" in content


def test_continuation_preview_asks_for_result_recap_and_next_step() -> None:
    content = PreToolPreviewPlugin().get_prompt_segments()[0].content

    assert "如果这不是本次回复的第一次工具调用" in content
    assert "交代上一步的结果" in content
    assert "不要重复上一条的措辞" in content


def test_preview_length_and_latency_hints_follow_config() -> None:
    content = (
        PreToolPreviewPlugin(preview_max_chars=24, preview_when_latency_over_ms=2000).get_prompt_segments()[0].content
    )

    assert "不超过 24 个汉字" in content
    assert "约 2000 毫秒" in content


def test_skip_clause_is_opt_out() -> None:
    skippable = PreToolPreviewPlugin(allow_skip_on_user_request=True).get_prompt_segments()[0].content
    strict = PreToolPreviewPlugin(allow_skip_on_user_request=False).get_prompt_segments()[0].content

    assert "可以跳过前置说明" in skippable
    assert "可以跳过前置说明" not in strict


def test_preview_segment_is_included_in_system_prompt(tmp_path: Path) -> None:
    tool_manager = ToolManager()
    datetime_tool = GetDatetimeTool()
    tool_manager.register_builtin(datetime_tool)
    plugin = PreToolPreviewPlugin()

    prompt = SystemPromptBuilder(tmp_path).build(
        persona_path=None,
        format_path=None,
        skills=[],
        tool_manager=tool_manager,
        tool_prompt_segments=plugin.get_prompt_segments(),
        character_name="tester",
    )

    assert "工具调用前预告" in prompt
    assert "每一次工具调用都成立" in prompt
    # injection_position 决定 segment 插在工具清单前还是后，所以要确认注入没把清单挤掉。
    # 取 tool 实例上的 name，避免内建工具改名时这里莫名其妙红。
    assert datetime_tool.name in prompt
