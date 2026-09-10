from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lab.live2d_model import Live2dModel
from lab.plugin.loader import PluginLoader
from lab.plugins.live2d_control import Live2DControlPluginConfig
from lab.tools.plugin import ToolPlugin
from lab.tools.types import AgentContext


def test_live2d_control_config_rejects_blank_and_duplicate_keys() -> None:
    with pytest.raises(ValidationError):
        Live2DControlPluginConfig.model_validate({"appearance_presets": [{"key": "   ", "description": "blank"}]})

    with pytest.raises(ValidationError):
        Live2DControlPluginConfig.model_validate(
            {
                "appearance_presets": [
                    {"key": "default", "description": "A"},
                    {"key": "default", "description": "B"},
                ]
            }
        )


def test_live2d_control_runtime_reads_appearance_presets() -> None:
    async def _load_plugin() -> ToolPlugin | None:
        loader = PluginLoader()
        ctx = AgentContext(
            workspace_root=Path.cwd(),
            extra={"live2d_emo_map": {"default": "expr_default", "hidden_hair": "expr_hidden"}},
        )
        loaded = await loader.load(
            "live2d_control",
            profile_overrides={
                "appearance_presets": [
                    {"key": "default", "description": "full style"},
                    {"key": "hidden_hair", "description": "clean look"},
                ]
            },
            ctx=ctx,
        )
        if loaded is None:
            return None
        assert isinstance(loaded, ToolPlugin)
        return loaded

    plugin = asyncio.run(_load_plugin())

    assert plugin is not None
    prompt_segments = plugin.get_prompt_segments()
    assert len(prompt_segments) == 1
    assert "full style" in prompt_segments[0].content
    assert "hidden_hair" in prompt_segments[0].content

    tools = {tool.name: tool for tool in plugin.get_tools()}
    result = asyncio.run(
        tools["set_live2d_appearance"].execute(
            {"appearance_key": "hidden_hair"},
            AgentContext(workspace_root=Path.cwd(), extra={}),
        )
    )
    assert result.ok is True
    assert "hidden_hair" in result.text


def test_imported_idle_paths_survive_preset_loading(tmp_path: Path) -> None:
    preset_path = tmp_path / "live2d_presets.json"
    preset_path.write_text(
        json.dumps(
            [
                {
                    "name": "character",
                    "modelPathRelative": "static/live2d-models/full/model.model3.json",
                    "emotionMap": {},
                    "motionAssets": [{"name": "idle1", "file": "idle1.motion3.json"}],
                    "importedMotions": [{"name": "idle1", "path": "static/live2d-models/recorded/idle1.motion3.json"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    model = Live2dModel("character", str(preset_path))
    ctx = AgentContext(
        workspace_root=tmp_path,
        extra={
            "live2d_motion_assets": model.model_info.get("motionAssets", []),
            "live2d_imported_motions": model.model_info.get("importedMotions", []),
        },
    )
    plugin = asyncio.run(
        PluginLoader().load(
            "live2d_control",
            profile_overrides={"states": {"listening": {"mode": "random_no_repeat", "clips": [{"url": "idle1"}]}}},
            ctx=ctx,
        )
    )
    assert plugin is not None
    assert ctx.extra["live2d_idle_banks"]["listening"] == {
        "mode": "random_no_repeat",
        "clips": [{"url": "/live2d-models/recorded/idle1.motion3.json"}],
    }
