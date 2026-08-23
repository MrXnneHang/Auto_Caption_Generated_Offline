from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

from lab.config_manager import XnneHangLabSettings, load_settings_file
from lab.config_manager.config import CURRENT_CONF_VERSION

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def test_load_lab_settings_normalizes_conf_version(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    lab_toml = config_dir / "lab.toml"
    lab_toml.write_text('conf_version = "v0.0.1"\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    settings = load_settings_file("lab.toml", XnneHangLabSettings)

    assert settings.conf_version == CURRENT_CONF_VERSION
    assert settings.agent.chat_model.thinking_mode == "default"
    assert settings.agent.require_detailed is False

    with lab_toml.open("rb") as file:
        saved = tomllib.load(file)

    assert saved["conf_version"] == CURRENT_CONF_VERSION
