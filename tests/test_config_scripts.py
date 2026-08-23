from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def _load_script_module(script_name: str):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / script_name
    module_name = f"test_script_{script_name.replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reload_lab_setting_resets_to_seeded_providers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "lab.toml").write_text(
        """
[agent.chat_model]
llm_provider = "custom"
llm_model_name = "custom-chat"

[[agent.llm.providers]]
name = "custom"
llm_api_key = "secret"
llm_base_url = "https://custom.example/v1"
api_format = "chat_completion"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    module = _load_script_module("reload_lab_setting.py")
    module.main()

    with (config_dir / "lab.toml").open("rb") as file:
        saved = tomllib.load(file)

    assert saved["agent"]["chat_model"] == {
        "llm_provider": "deepseek",
        "llm_model_name": "deepseek-v4-flash-vision-exp",
        "support_vision": True,
        "thinking_mode": "disabled",
    }
    assert saved["agent"]["require_detailed"] is False
    assert saved["agent"]["llm"]["providers"] == [
        {
            "name": "deepseek",
            "llm_api_key": "",
            "llm_base_url": "https://api.deepseek.com",
            "api_format": "chat_completion",
        },
        {
            "name": "openai",
            "llm_api_key": "",
            "llm_base_url": "https://api.openai.com/v1",
            "api_format": "chat_completion",
        },
        {
            "name": "google",
            "llm_api_key": "",
            "llm_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_format": "chat_completion",
        },
    ]


def test_sync_apikey_updates_chat_thinking_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "lab.toml").write_text(
        """
[agent.chat_model]
llm_provider = "custom"
llm_model_name = "old-model"
support_vision = false

[agent.vision_model]
llm_provider = "custom"
llm_model_name = "vision-model"

[[agent.llm.providers]]
name = "custom"
llm_api_key = "secret"
llm_base_url = "https://custom.example/v1"
api_format = "chat_completion"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHAT_MODEL_PROVIDER", "custom")
    monkeypatch.setenv("CHAT_MODEL_NAME", "deepseek-v4-flash-vision-exp")
    monkeypatch.setenv("CHAT_MODEL_SUPPORT_VISION", "true")
    monkeypatch.setenv("CHAT_MODEL_THINKING_MODE", "disabled")
    monkeypatch.delenv("LLM_PROVIDERS_JSON", raising=False)
    monkeypatch.delenv("VISION_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("VISION_MODEL_NAME", raising=False)

    module = _load_script_module("sync_apikey.py")
    module.main()

    with (config_dir / "lab.toml").open("rb") as file:
        saved = tomllib.load(file)

    assert saved["agent"]["chat_model"] == {
        "llm_provider": "custom",
        "llm_model_name": "deepseek-v4-flash-vision-exp",
        "support_vision": True,
        "thinking_mode": "disabled",
    }
