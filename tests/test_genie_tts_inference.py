from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def inference_module() -> Generator[ModuleType, None, None]:
    module_name = "genie_tts.Core.Inference"
    inference_path = (
        Path(__file__).resolve().parents[1] / "packages" / "Genie-TTS" / "src" / "genie_tts" / "Core" / "Inference.py"
    )

    sentinel = object()
    originals: dict[str, object] = {}

    def _set_module(name: str, module: ModuleType) -> None:
        originals[name] = sys.modules.get(name, sentinel)
        sys.modules[name] = module

    genie_pkg = ModuleType("genie_tts")
    genie_pkg.__path__ = []
    _set_module("genie_tts", genie_pkg)

    core_pkg = ModuleType("genie_tts.Core")
    core_pkg.__path__ = []
    _set_module("genie_tts.Core", core_pkg)

    audio_pkg = ModuleType("genie_tts.Audio")
    audio_pkg.__path__ = []
    _set_module("genie_tts.Audio", audio_pkg)

    onnxruntime_stub = ModuleType("onnxruntime")

    class InferenceSession:
        """Stub inference session."""

    onnxruntime_stub.InferenceSession = InferenceSession
    _set_module("onnxruntime", onnxruntime_stub)

    ref_audio_stub = ModuleType("genie_tts.Audio.ReferenceAudio")

    class ReferenceAudio:
        """Stub reference audio."""

    ref_audio_stub.ReferenceAudio = ReferenceAudio
    _set_module("genie_tts.Audio.ReferenceAudio", ref_audio_stub)

    g2p_stub = ModuleType("genie_tts.GetPhonesAndBert")

    def fake_get_phones_and_bert(
        *_args: object, **_kwargs: object
    ) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
        return np.array([[1]], dtype=np.int64), np.zeros((1, 1), dtype=np.float32)

    g2p_stub.get_phones_and_bert = fake_get_phones_and_bert
    _set_module("genie_tts.GetPhonesAndBert", g2p_stub)

    spec = importlib.util.spec_from_file_location(module_name, inference_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    originals[module_name] = sys.modules.get(module_name, sentinel)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, previous in originals.items():
            if previous is sentinel:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_extract_generated_semantic_tokens_keeps_only_generated_suffix(inference_module: ModuleType) -> None:
    y = np.array([[11, 22, 33, 44]], dtype=np.int64)

    extracted = inference_module._extract_generated_semantic_tokens(y, generated_steps=1)

    assert extracted.shape == (1, 1, 1)
    assert extracted[0, 0, 0] == 44


def test_extract_generated_semantic_tokens_rejects_zero_generated_steps(inference_module: ModuleType) -> None:
    y = np.array([[11, 22, 33, 44]], dtype=np.int64)

    with pytest.raises(RuntimeError, match="zero generated semantic steps"):
        inference_module._extract_generated_semantic_tokens(y, generated_steps=0)


def test_t2s_cpu_does_not_return_full_prompt_when_decoder_stops_immediately(inference_module: ModuleType) -> None:
    class _FakeEncoder:
        def run(self, *_args: object, **_kwargs: object) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
            return np.array([[1.0]], dtype=np.float32), np.array([[2.0]], dtype=np.float32)

    class _FakeFirstStageDecoder:
        def run(
            self, *_args: object, **_kwargs: object
        ) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
            return (
                np.array([[10, 20, 30]], dtype=np.int64),
                np.array([[1.0]], dtype=np.float32),
                np.array([123.0], dtype=np.float32),
            )

    class _FakeStageDecoder:
        def get_inputs(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(name="y"),
                SimpleNamespace(name="y_emb"),
                SimpleNamespace(name="present"),
            ]

        def run(
            self, *_args: object, **_kwargs: object
        ) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
            return (
                np.array([[10, 20, 30, 40]], dtype=np.int64),
                np.array([[1.0]], dtype=np.float32),
                np.array([True]),
                np.array([456.0], dtype=np.float32),
            )

    genie = inference_module.GENIE()
    semantic_tokens = genie.t2s_cpu(
        ref_seq=np.array([[1]], dtype=np.int64),
        ref_bert=np.zeros((1, 1), dtype=np.float32),
        text_seq=np.array([[2]], dtype=np.int64),
        text_bert=np.zeros((1, 1), dtype=np.float32),
        ssl_content=np.zeros((1, 1, 1), dtype=np.float32),
        encoder=_FakeEncoder(),
        first_stage_decoder=_FakeFirstStageDecoder(),
        stage_decoder=_FakeStageDecoder(),
    )

    assert semantic_tokens is not None
    assert semantic_tokens.shape == (1, 1, 1)
    assert semantic_tokens[0, 0, 0] == 0
