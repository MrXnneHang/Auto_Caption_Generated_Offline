from __future__ import annotations

from typing import TYPE_CHECKING

from lab.config_manager import XnneHangLabSettings, load_settings_file
from lab.config_manager.agent import PromptSettings
from lab.profile.system_prompt_builder import SystemPromptBuilder
from lab.tools import GetDatetimeTool, ToolManager
from lab.tools.plugin import PromptSegment

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_prompt_settings_no_longer_exposes_legacy_tool_prompt() -> None:
    assert "tool_prompt" not in PromptSettings.model_fields


def test_load_settings_file_parses_legacy_tool_prompt_without_rewriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "lab.toml").write_text(
        """
[agent.prompts]
vision_prompt = "./prompts/vision_prompt.txt"
tool_prompt = "./prompts/tool_prompt.txt"
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings_file("lab.toml", XnneHangLabSettings)

    assert settings.agent.prompts.vision_prompt == "./prompts/vision_prompt.txt"
    assert not hasattr(settings.agent.prompts, "tool_prompt")
    assert (
        (config_dir / "lab.toml")
        .read_text(encoding="utf-8")
        .strip()
        .endswith('tool_prompt = "./prompts/tool_prompt.txt"')
    )


def test_system_prompt_builder_uses_current_tool_prompt_chain(tmp_path: Path) -> None:
    persona_path = "prompts/characters/test.md"
    format_path = "prompts/formats/test.md"
    persona_file = tmp_path / persona_path
    format_file = tmp_path / format_path
    persona_file.parent.mkdir(parents=True)
    format_file.parent.mkdir(parents=True)
    persona_file.write_text("persona block", encoding="utf-8")
    format_file.write_text("format block", encoding="utf-8")

    tool_manager = ToolManager()
    tool_manager.register_builtin(GetDatetimeTool())
    tool_prompt_segments = [PromptSegment(name="runtime tool prompt", content="segment block", priority=10)]

    prompt = SystemPromptBuilder(tmp_path).build(
        persona_path=persona_path,
        format_path=format_path,
        skills=[],
        tool_manager=tool_manager,
        tool_prompt_segments=tool_prompt_segments,
        character_name="tester",
    )

    assert "persona block" in prompt
    assert "format block" in prompt
    assert "runtime tool prompt" in prompt
    assert "segment block" in prompt
    assert "你可以使用工具来查询信息" in prompt
    assert "get_datetime" in prompt
