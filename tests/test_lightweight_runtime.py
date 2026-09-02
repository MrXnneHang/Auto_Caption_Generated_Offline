from __future__ import annotations

import builtins

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lab.api.routes.status import router
from lab.config_manager import XnneHangLabSettings, load_settings_file
from lab.runtime.capabilities import build_runtime_capabilities
from lab.server import lifespan


def test_missing_settings_file_returns_lightweight_defaults_without_creating_files(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    settings = load_settings_file("lab.toml", XnneHangLabSettings)

    assert settings.asr.asr_model_provider == "none"
    assert settings.agent.tts.provider == "none"
    assert not (tmp_path / "config").exists()


@pytest.mark.anyio
async def test_lightweight_lifespan_never_imports_voice_implementations(monkeypatch) -> None:
    settings = XnneHangLabSettings.model_validate({"agent": {"enable_tool": False, "memory_chat_profile": ""}})
    app = FastAPI()
    app.state.runtime_settings = settings
    app.state.runtime_capabilities = build_runtime_capabilities(settings)

    real_import = builtins.__import__

    def reject_voice_import(name, *args, **kwargs):
        if name in {
            "lab.api.logic.sherpa_asr",
            "lab.api.logic.qwen_asr",
            "lab.api.logic.faster_qwen_tts",
            "lab.api.logic.genie_tts",
            "lab.api.logic.gsv_lite",
        }:
            raise AssertionError(f"lightweight startup imported {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_voice_import)

    async with lifespan(app):
        pass


def test_lightweight_capability_status_contract() -> None:
    settings = XnneHangLabSettings()
    app = FastAPI()
    app.state.runtime_capabilities = build_runtime_capabilities(settings)
    app.include_router(router)

    client = TestClient(app)
    payload = client.get("/status/capabilities").json()

    assert payload == {
        "schema_version": 1,
        "voice": {
            "asr": {
                "enabled": False,
                "provider": None,
                "state": "disabled",
                "reason": "disabled_by_config",
                "endpoints": [],
            },
            "tts": {
                "enabled": False,
                "provider": None,
                "state": "disabled",
                "reason": "disabled_by_config",
                "endpoints": [],
            },
        },
    }


def test_provider_without_package_is_unavailable() -> None:
    settings = XnneHangLabSettings.model_validate({"asr": {"asr_model_provider": "qwen"}})

    capability = build_runtime_capabilities(settings).voice["asr"]

    assert capability.model_dump() == {
        "enabled": False,
        "provider": "qwen",
        "state": "unavailable",
        "reason": "package_disabled",
        "endpoints": [],
    }

    settings = XnneHangLabSettings.model_validate(
        {
            "asr": {"asr_model_provider": "qwen"},
            "agent": {"tts": {"provider": "gsv_lite"}},
            "package": {"qwen_asr": True, "gsv_lite": True},
        }
    )

    capabilities = build_runtime_capabilities(settings)

    assert capabilities.voice["asr"].model_dump() == {
        "enabled": True,
        "provider": "qwen",
        "state": "available",
        "reason": None,
        "endpoints": ["/asr/reload", "/asr/qwen-asr/{model}/transcribe"],
    }
    assert capabilities.voice["tts"].model_dump() == {
        "enabled": True,
        "provider": "gsv_lite",
        "state": "available",
        "reason": None,
        "endpoints": ["/tts/gsv-lite/health", "/tts/gsv-lite/generate"],
    }
