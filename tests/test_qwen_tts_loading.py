from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import lab.api.logic.faster_qwen_tts as qwen_tts_module


def _fake_settings(*, configured_model: str = "0.6b") -> SimpleNamespace:
    return SimpleNamespace(
        package=SimpleNamespace(qwen_tts=True),
        root=SimpleNamespace(root_dir="."),
        agent=SimpleNamespace(
            tts=SimpleNamespace(provider="qwen_tts"),
            qwen_tts=SimpleNamespace(
                model_name=configured_model,
                model_0_6b_path="./models/Qwen3-TTS-12Hz-0.6B-Base",
                model_1_7b_path="./models/Qwen3-TTS-12Hz-1.7B-Base",
                device="cpu",
                warmup_cuda_graphs=False,
            ),
        ),
    )


def _fake_load_settings_file(*_args: object, **_kwargs: object) -> SimpleNamespace:
    return _fake_settings()


def test_get_qwen_tts_model_raises_when_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qwen_tts_module, "load_settings_file", _fake_load_settings_file)
    monkeypatch.setattr(qwen_tts_module, "_qwen_tts_engine", None)
    monkeypatch.setattr(qwen_tts_module, "_loaded_model_name", None)

    with pytest.raises(HTTPException) as exc_info:
        qwen_tts_module.get_qwen_tts_model()

    assert exc_info.value.status_code == 503
    assert "not loaded" in str(exc_info.value.detail)


def test_get_qwen_tts_model_raises_when_loaded_model_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qwen_tts_module, "load_settings_file", _fake_load_settings_file)
    monkeypatch.setattr(qwen_tts_module, "_qwen_tts_engine", object())
    monkeypatch.setattr(qwen_tts_module, "_loaded_model_name", "1.7b")

    with pytest.raises(HTTPException) as exc_info:
        qwen_tts_module.get_qwen_tts_model()

    assert exc_info.value.status_code == 503
    assert "Currently loaded model: '1.7b'" in str(exc_info.value.detail)
