from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from lab.plugin.config import (
    build_default_plugin_config,
    build_plugin_config_schema,
    get_plugin_config_model,
    import_plugin_module,
)
from lab.plugin.loader import PluginLoader

PLUGIN_DIR = Path("src/lab/plugins")
BUILTIN_PLUGIN_IDS = [
    "web_search_ddg",
    "web_search_searxng",
    "web_fetch",
    "screen_shot",
    "diary",
    "wikimem",
    "live2d_control",
]


def _load_plugin_meta(plugin_id: str) -> dict[str, object]:
    with (PLUGIN_DIR / plugin_id / "plugin.toml").open("rb") as f:
        return tomllib.load(f)


def _load_plugin_config_model(plugin_id: str):
    plugin_dir = PLUGIN_DIR / plugin_id
    meta = _load_plugin_meta(plugin_id)
    module = import_plugin_module(plugin_id, plugin_dir)
    config_model = get_plugin_config_model(module, meta)
    assert config_model is not None
    return config_model, meta


def test_builtin_plugin_toml_matches_pydantic_models() -> None:
    for plugin_id in BUILTIN_PLUGIN_IDS:
        config_model, meta = _load_plugin_config_model(plugin_id)
        expected_config = build_default_plugin_config(config_model)
        expected_schema = build_plugin_config_schema(config_model)

        assert meta.get("config", {}) == expected_config
        assert meta.get("config_schema", {}) == expected_schema


def test_builtin_plugins_define_config_schema() -> None:
    for plugin_id in BUILTIN_PLUGIN_IDS:
        meta = _load_plugin_meta(plugin_id)
        assert "config_schema" in meta, f"{plugin_id} is missing [config_schema]"
        assert isinstance(meta["config_schema"], dict), f"{plugin_id} config_schema must be a table"


def test_plugin_loader_validates_profile_overrides() -> None:
    with pytest.raises(ValidationError):
        asyncio.run(PluginLoader().load("wikimem", profile_overrides={"search_limit": 0}))


def test_live2d_control_schema_exposes_list_of_objects() -> None:
    config_model, _ = _load_plugin_config_model("live2d_control")

    schema = build_plugin_config_schema(config_model)

    assert schema["appearance_presets"]["type"] == "list"
    assert schema["appearance_presets"]["items"]["type"] == "object"
    assert schema["appearance_presets"]["items"]["properties"]["key"]["type"] == "str"
    assert schema["appearance_presets"]["items"]["properties"]["description"]["type"] == "str"
