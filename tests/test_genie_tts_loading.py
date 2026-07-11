from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

import lab.api.logic.genie_tts as genie_tts_module


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        package=SimpleNamespace(genie_tts=True),
        agent=SimpleNamespace(
            speaker_lang="ZH",
            tts=SimpleNamespace(provider="genie_tts", genie_tts=SimpleNamespace(use_roberta=False, language="")),
        ),
        root=SimpleNamespace(root_dir="."),
    )


def _spec(character_name: str) -> genie_tts_module.GenieTTSModelSpec:
    return genie_tts_module.GenieTTSModelSpec(
        character_name=character_name,
        character_dir=Path(f"./models/genie-tts/{character_name}"),
        onnx_model_dir=Path(f"./models/genie-tts/{character_name}/tts_models"),
        language="Chinese",
        use_roberta=False,
    )


def _fake_load_settings_file(*_args: object, **_kwargs: object) -> SimpleNamespace:
    return _fake_settings()


def _fake_spec_for(character_name: str) -> object:
    def _fake_get_configured_model_spec(*_args: object, **_kwargs: object) -> genie_tts_module.GenieTTSModelSpec:
        return _spec(character_name)

    return _fake_get_configured_model_spec


def test_get_genie_tts_model_raises_when_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(genie_tts_module, "load_settings_file", _fake_load_settings_file)
    monkeypatch.setattr(genie_tts_module, "_get_configured_model_spec", _fake_spec_for("baoqiao"))
    monkeypatch.setattr(genie_tts_module, "_genie_tts_module", None)
    monkeypatch.setattr(genie_tts_module, "_loaded_model_spec", None)

    with pytest.raises(HTTPException) as exc_info:
        genie_tts_module.get_genie_tts_model()

    assert exc_info.value.status_code == 503
    assert "not initialized" in str(exc_info.value.detail)


def test_get_genie_tts_model_raises_when_loaded_model_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(genie_tts_module, "load_settings_file", _fake_load_settings_file)
    monkeypatch.setattr(genie_tts_module, "_get_configured_model_spec", _fake_spec_for("elaina"))
    monkeypatch.setattr(genie_tts_module, "_genie_tts_module", object())
    monkeypatch.setattr(genie_tts_module, "_loaded_model_spec", _spec("baoqiao"))

    with pytest.raises(HTTPException) as exc_info:
        genie_tts_module.get_genie_tts_model()

    assert exc_info.value.status_code == 503
    assert "Currently loaded character: 'baoqiao'" in str(exc_info.value.detail)


def test_resolve_model_dir_prefers_infer_config_key(tmp_path: Path) -> None:
    character_dir = tmp_path / "models" / "genie-tts" / "baoqiao"
    model_dir = character_dir / "custom_genie"
    model_dir.mkdir(parents=True)

    resolved = genie_tts_module._resolve_model_dir_from_infer_config(
        character_dir,
        {"genie_model_dir": "custom_genie"},
    )

    assert resolved == model_dir.resolve()


def test_resolve_default_model_dir_accepts_character_root_when_onnx_files_are_in_root(tmp_path: Path) -> None:
    character_dir = tmp_path / "models" / "genie-tts" / "baoqiao"
    character_dir.mkdir(parents=True)
    (character_dir / "vits_fp32.onnx").write_bytes(b"onnx")
    (character_dir / "t2s_encoder_fp32.onnx").write_bytes(b"onnx")

    resolved = genie_tts_module._resolve_default_model_dir(character_dir)

    assert resolved == character_dir.resolve()


def test_get_genie_tts_use_roberta_defaults_to_false_when_missing() -> None:
    settings = SimpleNamespace(agent=SimpleNamespace(tts=SimpleNamespace()))

    assert genie_tts_module._get_genie_tts_use_roberta(settings) is False


def test_resolve_language_prefers_lab_toml_override() -> None:
    settings = SimpleNamespace(
        agent=SimpleNamespace(
            speaker_lang="ZH",
            tts=SimpleNamespace(genie_tts=SimpleNamespace(language="Japanese")),
        )
    )

    resolved = genie_tts_module._resolve_language({"language": "English"}, cast("Any", settings))

    assert resolved == "Japanese"


def test_resolve_language_falls_back_to_auto_without_lab_toml_or_infer_json() -> None:
    settings = SimpleNamespace(
        agent=SimpleNamespace(
            speaker_lang="ZH",
            tts=SimpleNamespace(genie_tts=SimpleNamespace(language="")),
        )
    )

    resolved = genie_tts_module._resolve_language({}, cast("Any", settings))

    assert resolved == "auto"


def test_resolve_warmup_ref_audio_and_text_prefers_default_emotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        agent=SimpleNamespace(tts=SimpleNamespace(voice_assets_root="./voices")),
        root=SimpleNamespace(root_dir=str(tmp_path)),
    )
    config_dir = tmp_path / "config" / "voices"
    ref_audio = tmp_path / "voices" / "luming" / "平静" / "1.wav"
    ref_text = tmp_path / "voices" / "luming" / "平静" / "1.txt"
    config_dir.mkdir(parents=True)
    ref_audio.parent.mkdir(parents=True)
    ref_audio.write_bytes(b"wav")
    ref_text.write_text("default ref", encoding="utf-8")
    (config_dir / "luming.toml").write_text(
        """
[voice]
name = "luming"
asset_bundle = "luming"
default_emotion = "平静"

[emotions."平静"]

[[emotions."平静".clips]]
id = "1"
ref_audio = "平静/1.wav"
ref_text_file = "平静/1.txt"
""".strip(),
        encoding="utf-8",
    )

    profile = SimpleNamespace(
        character=SimpleNamespace(
            tts=SimpleNamespace(
                voice="luming",
                emotions={},
            )
        )
    )

    def fake_resolve_active_profile(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return profile

    monkeypatch.setattr(genie_tts_module, "_resolve_active_profile", fake_resolve_active_profile)

    resolved_audio, resolved_text = genie_tts_module._resolve_warmup_ref_audio_and_text(
        cast("Any", settings), "baoqiao"
    )

    assert resolved_audio == ref_audio.resolve()
    assert resolved_text == "default ref"


def test_warmup_genie_tts_model_uses_ref_text_for_warmup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = SimpleNamespace(
        package=SimpleNamespace(genie_tts=True),
        agent=SimpleNamespace(
            speaker_lang="ZH",
            tts=SimpleNamespace(genie_tts=SimpleNamespace(use_roberta=False, language="auto")),
        ),
        root=SimpleNamespace(root_dir=str(tmp_path)),
    )
    spec = genie_tts_module.GenieTTSModelSpec(
        character_name="baoqiao",
        character_dir=tmp_path / "models" / "genie-tts" / "baoqiao",
        onnx_model_dir=tmp_path / "models" / "genie-tts" / "baoqiao",
        language="auto",
        use_roberta=False,
    )
    ref_audio = tmp_path / "models" / "genie-tts" / "baoqiao" / "ref_audios" / "default.wav"
    ref_audio.parent.mkdir(parents=True)
    ref_audio.write_bytes(b"wav")

    captured: dict[str, object] = {}

    async def _fake_synthesize_once(*, text: str, ref_audio: Path | None, ref_text: str | None) -> bytes:
        captured["text"] = text
        captured["ref_audio"] = ref_audio
        captured["ref_text"] = ref_text
        return b"RIFFfake"

    def fake_get_genie_tts_settings() -> SimpleNamespace:
        return settings

    def fake_get_configured_model_spec(*_args: object, **_kwargs: object) -> genie_tts_module.GenieTTSModelSpec:
        return spec

    def fake_resolve_warmup_ref_audio_and_text(*_args: object, **_kwargs: object) -> tuple[Path, str]:
        return ref_audio.resolve(), "default ref"

    def fake_read_wav_sample_rate(_wav_bytes: bytes) -> int:
        return 32000

    def fake_get_genie_tts_status() -> dict[str, bool]:
        return {"loaded": True}

    monkeypatch.setattr(genie_tts_module, "_get_genie_tts_settings", fake_get_genie_tts_settings)
    monkeypatch.setattr(genie_tts_module, "_get_configured_model_spec", fake_get_configured_model_spec)
    monkeypatch.setattr(
        genie_tts_module,
        "_resolve_warmup_ref_audio_and_text",
        fake_resolve_warmup_ref_audio_and_text,
    )
    monkeypatch.setattr(genie_tts_module, "synthesize_once", _fake_synthesize_once)
    monkeypatch.setattr(genie_tts_module, "read_wav_sample_rate", fake_read_wav_sample_rate)
    monkeypatch.setattr(genie_tts_module, "get_genie_tts_status", fake_get_genie_tts_status)

    status = asyncio.run(genie_tts_module.warmup_genie_tts_model())

    assert status == {"loaded": True}
    assert captured["text"] == "default ref"
    assert captured["ref_audio"] == ref_audio.resolve()
    assert captured["ref_text"] == "default ref"


def test_resolve_genie_tts_submodule_src_dir(tmp_path: Path) -> None:
    settings = SimpleNamespace(root=SimpleNamespace(root_dir=str(tmp_path)))

    resolved = genie_tts_module._resolve_genie_tts_submodule_src_dir(cast("Any", settings))

    assert resolved == (tmp_path / "packages" / "Genie-TTS" / "src").resolve()


def test_resolve_character_dir_prefers_genie_tts_root(tmp_path: Path) -> None:
    settings = SimpleNamespace(root=SimpleNamespace(root_dir=str(tmp_path)))
    preferred = tmp_path / "models" / "genie-tts" / "baoqiao"
    preferred.mkdir(parents=True)

    resolved = genie_tts_module._resolve_character_dir(cast("Any", settings), "baoqiao")

    assert resolved == preferred.resolve()


def test_resolve_genie_tts_resource_paths_prefers_geniedata_layout(tmp_path: Path) -> None:
    genie_data_dir = tmp_path / "models" / "geniedata"
    (genie_data_dir / "G2P" / "EnglishG2P").mkdir(parents=True)
    (genie_data_dir / "G2P" / "ChineseG2P").mkdir(parents=True)
    roberta_dir = genie_data_dir / "roberta-wwm-ext-large-onnx"
    roberta_dir.mkdir(parents=True)
    (roberta_dir / "model.onnx").write_bytes(b"onnx")
    (roberta_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    settings = SimpleNamespace(root=SimpleNamespace(root_dir=str(tmp_path)))

    resources = genie_tts_module._resolve_genie_tts_resource_paths(cast("Any", settings))

    assert resources.genie_data_dir == genie_data_dir.resolve()
    assert resources.english_g2p_dir == (genie_data_dir / "G2P" / "EnglishG2P").resolve()
    assert resources.chinese_g2p_dir == (genie_data_dir / "G2P" / "ChineseG2P").resolve()
    assert resources.roberta_model_dir == roberta_dir.resolve()
    assert resources.roberta_model_path == (roberta_dir / "model.onnx").resolve()


def test_configure_genie_tts_environment_disables_auto_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    genie_data_dir = tmp_path / "models" / "geniedata"
    (genie_data_dir / "G2P" / "EnglishG2P").mkdir(parents=True)
    (genie_data_dir / "G2P" / "ChineseG2P").mkdir(parents=True)
    hubert_dir = genie_data_dir / "chinese-hubert-base"
    hubert_dir.mkdir(parents=True)
    (hubert_dir / "chinese-hubert-base.onnx").write_bytes(b"onnx")
    (hubert_dir / "chinese-hubert-base_weights_fp16.bin").write_bytes(b"bin")
    sv_model = genie_data_dir / "speaker_encoder.onnx"
    sv_model.write_bytes(b"onnx")
    roberta_dir = genie_data_dir / "roberta-wwm-ext-large-onnx"
    roberta_dir.mkdir(parents=True)
    (roberta_dir / "model.onnx").write_bytes(b"onnx")
    (roberta_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    settings = SimpleNamespace(
        root=SimpleNamespace(root_dir=str(tmp_path)),
        agent=SimpleNamespace(tts=SimpleNamespace(genie_tts=SimpleNamespace(onnx_intra_threads=4))),
    )
    spec = genie_tts_module.GenieTTSModelSpec(
        character_name="baoqiao",
        character_dir=tmp_path / "models" / "genie-tts" / "baoqiao",
        onnx_model_dir=tmp_path / "models" / "genie-tts" / "baoqiao" / "tts_models",
        language="Chinese",
        use_roberta=False,
    )

    monkeypatch.delenv("GENIE_DATA_DIR", raising=False)
    monkeypatch.delenv("GENIE_SKIP_RESOURCE_CHECK", raising=False)
    monkeypatch.delenv("English_G2P_DIR", raising=False)
    monkeypatch.delenv("Chinese_G2P_DIR", raising=False)
    monkeypatch.delenv("HUBERT_MODEL_DIR", raising=False)
    monkeypatch.delenv("SV_MODEL", raising=False)
    monkeypatch.delenv("ROBERTA_MODEL_DIR", raising=False)
    monkeypatch.delenv("XH_ONNX_INTRA_THREADS", raising=False)

    resources = genie_tts_module._configure_genie_tts_environment(cast("Any", settings), spec)

    assert resources.hubert_onnx_path == hubert_dir / "chinese-hubert-base.onnx"
    assert genie_tts_module.os.environ["GENIE_DATA_DIR"] == str(genie_data_dir)
    assert genie_tts_module.os.environ["GENIE_SKIP_RESOURCE_CHECK"] == "1"
    assert genie_tts_module.os.environ["English_G2P_DIR"] == str(genie_data_dir / "G2P" / "EnglishG2P")
    assert genie_tts_module.os.environ["Chinese_G2P_DIR"] == str(genie_data_dir / "G2P" / "ChineseG2P")
    assert genie_tts_module.os.environ["HUBERT_MODEL_DIR"] == str(hubert_dir)
    assert genie_tts_module.os.environ["SV_MODEL"] == str(sv_model)
    assert genie_tts_module.os.environ["ROBERTA_MODEL_DIR"] == str(roberta_dir)
    assert genie_tts_module.os.environ["XH_ONNX_INTRA_THREADS"] == "4"


def test_validate_genie_tts_resources_reports_missing_files(tmp_path: Path) -> None:
    settings = SimpleNamespace(root=SimpleNamespace(root_dir=str(tmp_path)))
    spec = genie_tts_module.GenieTTSModelSpec(
        character_name="baoqiao",
        character_dir=tmp_path / "models" / "genie-tts" / "baoqiao",
        onnx_model_dir=tmp_path / "models" / "genie-tts" / "baoqiao" / "tts_models",
        language="Chinese",
        use_roberta=True,
    )

    with pytest.raises(FileNotFoundError) as exc_info:
        genie_tts_module._validate_genie_tts_resources(cast("Any", settings), spec)

    message = str(exc_info.value)
    assert "Automatic download is disabled here" in message
    assert "Chinese HuBERT ONNX" in message


@pytest.mark.anyio
async def test_synthesize_once_waits_for_model_lock_without_blocking_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"fake")

    configured = genie_tts_module.GenieTTSModelSpec(
        character_name="baoqiao",
        character_dir=tmp_path / "models" / "genie-tts" / "baoqiao",
        onnx_model_dir=tmp_path / "models" / "genie-tts" / "baoqiao",
        language="Chinese",
        use_roberta=False,
    )

    class _FakeGenie:
        def set_reference_audio(self, **kwargs: object) -> None:
            del kwargs

        async def tts_async(self, **kwargs: object):
            del kwargs
            yield b"\x00\x00"

    monkeypatch.setattr(genie_tts_module, "_loaded_model_spec", configured)
    monkeypatch.setattr(genie_tts_module, "get_genie_tts_model", lambda: _FakeGenie())
    lock = threading.Lock()
    monkeypatch.setattr(genie_tts_module, "_model_lock", lock)

    acquired = lock.acquire(timeout=1.0)
    assert acquired

    synth_task = asyncio.create_task(
        genie_tts_module.synthesize_once(
            text="hello",
            ref_audio=ref_audio,
            ref_text="ref text",
        )
    )
    try:
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.1)
    finally:
        lock.release()
    wav_bytes = await asyncio.wait_for(synth_task, timeout=0.5)
    assert wav_bytes


def test_stop_genie_tts_synthesis_calls_upstream_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    class _FakeGenie:
        def stop(self) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(genie_tts_module, "_genie_tts_module", _FakeGenie())

    genie_tts_module.stop_genie_tts_synthesis()

    assert called is True
