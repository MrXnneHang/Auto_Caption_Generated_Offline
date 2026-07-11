from __future__ import annotations

import asyncio
import os
import pickle
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

import lab.api.logic.gsv_lite as gsv_lite_module


def _fake_settings(*_args: object, **_kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        package=SimpleNamespace(gsv_lite=True),
        agent=SimpleNamespace(tts=SimpleNamespace(provider="gsv_lite", gsv_lite=SimpleNamespace(use_bert=False))),
    )


def _spec(character_name: str) -> gsv_lite_module.GSVLiteModelSpec:
    return gsv_lite_module.GSVLiteModelSpec(
        character_name=character_name,
        character_dir=Path(f"./models/gsv-tts-lite/{character_name}"),
        reference_dir=Path(f"./models/gsv-tts-lite/{character_name}"),
        gpt_path=Path(f"./models/gsv-tts-lite/{character_name}/model.ckpt"),
        sovits_path=Path(f"./models/gsv-tts-lite/{character_name}/model.pth"),
        models_dir=Path("./models/GSVLiteData"),
    )


def _fake_none() -> None:
    return None


def test_get_gsv_lite_model_raises_when_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_configured_model_spec(*_args: object, **_kwargs: object) -> gsv_lite_module.GSVLiteModelSpec:
        return _spec("baoqiao")

    monkeypatch.setattr(gsv_lite_module, "load_settings_file", _fake_settings)
    monkeypatch.setattr(gsv_lite_module, "_get_configured_model_spec", fake_get_configured_model_spec)
    monkeypatch.setattr(gsv_lite_module, "_gsv_lite_engine", None)
    monkeypatch.setattr(gsv_lite_module, "_loaded_model_spec", None)

    with pytest.raises(HTTPException) as exc_info:
        gsv_lite_module.get_gsv_lite_model()

    assert exc_info.value.status_code == 503
    assert "not initialized" in str(exc_info.value.detail)


def test_get_gsv_lite_model_raises_when_loaded_model_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_configured_model_spec(*_args: object, **_kwargs: object) -> gsv_lite_module.GSVLiteModelSpec:
        return _spec("elaina")

    monkeypatch.setattr(gsv_lite_module, "load_settings_file", _fake_settings)
    monkeypatch.setattr(gsv_lite_module, "_get_configured_model_spec", fake_get_configured_model_spec)
    monkeypatch.setattr(gsv_lite_module, "_gsv_lite_engine", object())
    monkeypatch.setattr(gsv_lite_module, "_loaded_model_spec", _spec("baoqiao"))

    with pytest.raises(HTTPException) as exc_info:
        gsv_lite_module.get_gsv_lite_model()

    assert exc_info.value.status_code == 503
    assert "Currently loaded character: 'baoqiao'" in str(exc_info.value.detail)


def test_load_gsv_lite_model_uses_extended_gpt_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeTTS:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def load_gpt_model(self, *_args: object) -> None:
            return None

        def load_sovits_model(self, *_args: object) -> None:
            return None

    def fake_get_configured_model_spec(*_args: object, **_kwargs: object) -> gsv_lite_module.GSVLiteModelSpec:
        return _spec("luoqixi")

    def fake_get_gsv_lite_settings() -> SimpleNamespace:
        return SimpleNamespace(
            package=SimpleNamespace(gsv_lite=True),
            agent=SimpleNamespace(tts=SimpleNamespace(provider="gsv_lite", gsv_lite=SimpleNamespace(use_bert=True))),
            root=SimpleNamespace(root_dir="."),
        )

    monkeypatch.setattr(gsv_lite_module, "_get_gsv_lite_settings", fake_get_gsv_lite_settings)
    monkeypatch.setattr(gsv_lite_module, "_get_configured_model_spec", fake_get_configured_model_spec)
    monkeypatch.setattr(gsv_lite_module, "_apply_gsv_lite_monkey_patch", _fake_none)
    monkeypatch.setattr(gsv_lite_module, "_gsv_lite_engine", None)
    monkeypatch.setattr(gsv_lite_module, "_loaded_model_spec", None)

    gsv_tts_module = ModuleType("gsv_tts")
    cast("Any", gsv_tts_module).TTS = FakeTTS
    monkeypatch.setitem(sys.modules, "gsv_tts", gsv_tts_module)

    status = gsv_lite_module.load_gsv_lite_model(force_reload=True)

    assert status["loaded"] is True
    assert captured["gpt_cache"] == [(1, 512), (1, 1024), (1, 2048), (4, 512), (4, 1024)]
    assert captured["use_bert"] is True
    assert Path(cast("str", captured["models_dir"])) == Path("models/GSVLiteData")


def test_load_gsv_lite_model_configures_local_english_nltk_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    models_dir = (tmp_path / "models" / "GSVLiteData").resolve()
    en_dir = models_dir / "g2p" / "en"
    nltk_dir = models_dir / "g2p" / "en" / "nltk"
    nltk_dir.mkdir(parents=True)
    expected_cmudict = {"desk": [["D", "EH1", "S", "K"]]}
    (en_dir / "engdict_cache.pickle").write_bytes(pickle.dumps(expected_cmudict))

    captured: dict[str, object] = {}

    class FakeTTS:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            fake_nltk = cast("Any", sys.modules["nltk"])
            captured["nltk_data_path"] = list(fake_nltk.data.path)
            captured["nltk_data_env"] = os.environ.get("NLTK_DATA")
            fake_cmudict = cast("Any", sys.modules["nltk.corpus"]).cmudict
            captured["cmudict"] = fake_cmudict.dict()

        def load_gpt_model(self, *_args: object) -> None:
            return None

        def load_sovits_model(self, *_args: object) -> None:
            return None

    def fake_get_gsv_lite_settings() -> SimpleNamespace:
        return SimpleNamespace(
            package=SimpleNamespace(gsv_lite=True),
            agent=SimpleNamespace(tts=SimpleNamespace(provider="gsv_lite", gsv_lite=SimpleNamespace(use_bert=False))),
            root=SimpleNamespace(root_dir=str(tmp_path)),
        )

    spec = gsv_lite_module.GSVLiteModelSpec(
        character_name="baoqiao",
        character_dir=(tmp_path / "models" / "gsv-tts-lite" / "baoqiao").resolve(),
        reference_dir=(tmp_path / "models" / "gsv-tts-lite" / "baoqiao").resolve(),
        gpt_path=(tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "model.ckpt").resolve(),
        sovits_path=(tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "model.pth").resolve(),
        models_dir=models_dir,
    )

    def fake_get_configured_model_spec(*_args: object, **_kwargs: object) -> gsv_lite_module.GSVLiteModelSpec:
        return spec

    fake_nltk = ModuleType("nltk")
    cast("Any", fake_nltk).data = SimpleNamespace(path=["/existing/nltk"])
    fake_cmudict = SimpleNamespace(dict=lambda: {"fallback": [["F", "AE1", "L", "B", "AE2", "K"]]})
    fake_nltk_corpus = ModuleType("nltk.corpus")
    cast("Any", fake_nltk_corpus).cmudict = fake_cmudict

    gsv_tts_module = ModuleType("gsv_tts")
    cast("Any", gsv_tts_module).TTS = FakeTTS

    monkeypatch.setattr(gsv_lite_module, "_get_gsv_lite_settings", fake_get_gsv_lite_settings)
    monkeypatch.setattr(gsv_lite_module, "_get_configured_model_spec", fake_get_configured_model_spec)
    monkeypatch.setattr(gsv_lite_module, "_apply_gsv_lite_monkey_patch", _fake_none)
    monkeypatch.setattr(gsv_lite_module, "_gsv_lite_engine", None)
    monkeypatch.setattr(gsv_lite_module, "_loaded_model_spec", None)
    monkeypatch.setitem(sys.modules, "nltk", fake_nltk)
    monkeypatch.setitem(sys.modules, "nltk.corpus", fake_nltk_corpus)
    monkeypatch.setitem(sys.modules, "gsv_tts", gsv_tts_module)
    monkeypatch.setenv("NLTK_DATA", "/existing/nltk")

    gsv_lite_module.load_gsv_lite_model(force_reload=True)

    assert captured["nltk_data_path"] == [str(nltk_dir), "/existing/nltk"]
    assert captured["nltk_data_env"] == os.pathsep.join([str(nltk_dir), "/existing/nltk"])
    assert captured["cmudict"] == expected_cmudict


def test_resolve_warmup_inputs_prefers_character_dir_and_speaker_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config" / "voices"
    ref_audio = tmp_path / "voices" / "luming" / "平静" / "1.wav"
    speaker_audio = tmp_path / "voices" / "luming" / "speaker" / "default.wav"
    ref_text = tmp_path / "voices" / "luming" / "平静" / "1.txt"
    config_dir.mkdir(parents=True)
    ref_audio.parent.mkdir(parents=True)
    speaker_audio.parent.mkdir(parents=True)
    ref_audio.write_bytes(b"wav")
    speaker_audio.write_bytes(b"wav")
    ref_text.write_text("default ref", encoding="utf-8")
    (config_dir / "luming.toml").write_text(
        """
[voice]
name = "luming"
asset_bundle = "luming"
default_emotion = "平静"

[emotions."平静"]
speaker_audio = "speaker/default.wav"

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
    settings = SimpleNamespace(
        agent=SimpleNamespace(tts=SimpleNamespace(voice_assets_root="./voices")),
        root=SimpleNamespace(root_dir=str(tmp_path)),
    )
    spec = gsv_lite_module.GSVLiteModelSpec(
        character_name="baoqiao",
        character_dir=(tmp_path / "models" / "gsv-tts-lite" / "baoqiao").resolve(),
        reference_dir=(tmp_path / "models" / "gsv-tts-lite" / "baoqiao").resolve(),
        gpt_path=tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "model.ckpt",
        sovits_path=tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "model.pth",
        models_dir=(tmp_path / "models" / "GSVLiteData").resolve(),
    )

    def fake_resolve_active_profile(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return profile

    monkeypatch.setattr(gsv_lite_module, "_resolve_active_profile", fake_resolve_active_profile)

    resolved_ref_audio, resolved_ref_text, resolved_speaker_audio = gsv_lite_module._resolve_warmup_inputs(
        cast("Any", settings),
        spec,
    )

    assert resolved_ref_audio == ref_audio.resolve()
    assert resolved_ref_text == "default ref"
    assert resolved_speaker_audio == speaker_audio.resolve()


def test_warmup_gsv_lite_model_uses_ref_text_for_real_warmup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = SimpleNamespace(
        package=SimpleNamespace(gsv_lite=True),
        agent=SimpleNamespace(tts=SimpleNamespace(provider="gsv_lite", gsv_lite=SimpleNamespace(use_bert=False))),
        root=SimpleNamespace(root_dir=str(tmp_path)),
    )
    spec = gsv_lite_module.GSVLiteModelSpec(
        character_name="baoqiao",
        character_dir=(tmp_path / "models" / "gsv-tts-lite" / "baoqiao").resolve(),
        reference_dir=(tmp_path / "models" / "gsv-tts-lite" / "baoqiao").resolve(),
        gpt_path=tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "model.ckpt",
        sovits_path=tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "model.pth",
        models_dir=(tmp_path / "models" / "GSVLiteData").resolve(),
    )
    ref_audio = (tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "ref.wav").resolve()
    speaker_audio = (tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "speaker.wav").resolve()
    ref_audio.parent.mkdir(parents=True, exist_ok=True)
    speaker_audio.parent.mkdir(parents=True, exist_ok=True)
    ref_audio.write_bytes(b"wav")
    speaker_audio.write_bytes(b"wav")

    captured: dict[str, object] = {}

    async def _fake_synthesize_once(
        *,
        text: str,
        ref_audio: Path | None,
        ref_text: str | None,
        speaker_audio: Path | None = None,
        **_kwargs: object,
    ) -> bytes:
        captured["text"] = text
        captured["ref_audio"] = ref_audio
        captured["ref_text"] = ref_text
        captured["speaker_audio"] = speaker_audio
        return b"RIFFfake"

    def fake_get_gsv_lite_settings() -> SimpleNamespace:
        return settings

    def fake_get_configured_model_spec(*_args: object, **_kwargs: object) -> gsv_lite_module.GSVLiteModelSpec:
        return spec

    def fake_resolve_warmup_inputs(*_args: object, **_kwargs: object) -> tuple[Path, str, Path]:
        return ref_audio, "default ref", speaker_audio

    def fake_get_gsv_lite_status() -> dict[str, bool]:
        return {"loaded": True}

    monkeypatch.setattr(gsv_lite_module, "_get_gsv_lite_settings", fake_get_gsv_lite_settings)
    monkeypatch.setattr(gsv_lite_module, "_get_configured_model_spec", fake_get_configured_model_spec)
    monkeypatch.setattr(
        gsv_lite_module,
        "_resolve_warmup_inputs",
        fake_resolve_warmup_inputs,
    )
    monkeypatch.setattr(gsv_lite_module, "synthesize_once", _fake_synthesize_once)
    monkeypatch.setattr(gsv_lite_module, "get_gsv_lite_status", fake_get_gsv_lite_status)

    status = asyncio.run(gsv_lite_module.warmup_gsv_lite_model())

    assert status == {"loaded": True}
    assert captured["text"] == "default ref"
    assert captured["ref_audio"] == ref_audio
    assert captured["ref_text"] == "default ref"
    assert captured["speaker_audio"] == speaker_audio


def test_get_gsv_lite_use_bert_defaults_to_false_when_missing() -> None:
    settings = SimpleNamespace(agent=SimpleNamespace(tts=SimpleNamespace()))

    assert gsv_lite_module._get_gsv_lite_use_bert(settings) is False


def test_resolve_character_dir_prefers_gsv_tts_lite_root(tmp_path: Path) -> None:
    settings = SimpleNamespace(root=SimpleNamespace(root_dir=str(tmp_path)))
    preferred = tmp_path / "models" / "gsv-tts-lite" / "baoqiao"
    preferred.mkdir(parents=True)

    resolved = gsv_lite_module._resolve_character_dir(cast("Any", settings), "baoqiao")

    assert resolved == preferred.resolve()


def test_resolve_gsv_lite_data_dir_prefers_gsv_lite_data_root(tmp_path: Path) -> None:
    settings = SimpleNamespace(root=SimpleNamespace(root_dir=str(tmp_path)))
    preferred = tmp_path / "models" / "GSVLiteData"
    legacy = tmp_path / "models" / "g2p"
    preferred.mkdir(parents=True)
    legacy.mkdir(parents=True)

    resolved = gsv_lite_module._resolve_gsv_lite_data_dir(cast("Any", settings))

    assert resolved == preferred.resolve()


def test_resolve_gsv_lite_data_dir_falls_back_to_models_root(tmp_path: Path) -> None:
    settings = SimpleNamespace(root=SimpleNamespace(root_dir=str(tmp_path)))
    legacy = tmp_path / "models" / "g2p"
    legacy.mkdir(parents=True)

    resolved = gsv_lite_module._resolve_gsv_lite_data_dir(cast("Any", settings))

    assert resolved == (tmp_path / "models").resolve()


def test_configure_gsv_lite_openjtalk_uses_local_ja_resources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    models_dir = tmp_path / "models" / "GSVLiteData"
    ja_dir = models_dir / "g2p" / "ja"
    openjtalk_dir = ja_dir / "open_jtalk_dic_utf_8-1.11"
    user_dict_bin = ja_dir / "user.dict"
    openjtalk_dir.mkdir(parents=True)
    user_dict_bin.write_bytes(b"dict")

    calls: list[tuple[str, str | None]] = []

    pyopenjtalk_module = ModuleType("pyopenjtalk")

    def fake_unset_user_dict() -> None:
        calls.append(("unset", None))

    def fake_update_global_jtalk_with_user_dict(path: str) -> None:
        calls.append(("update", path))

    def fake_mecab_dict_index(_src: str, _dst: str) -> None:
        calls.append(("build", None))

    cast("Any", pyopenjtalk_module).unset_user_dict = fake_unset_user_dict
    cast("Any", pyopenjtalk_module).update_global_jtalk_with_user_dict = fake_update_global_jtalk_with_user_dict
    cast("Any", pyopenjtalk_module).mecab_dict_index = fake_mecab_dict_index

    monkeypatch.setitem(sys.modules, "pyopenjtalk", pyopenjtalk_module)
    monkeypatch.delenv("OPEN_JTALK_DICT_DIR", raising=False)

    gsv_lite_module._configure_gsv_lite_openjtalk(models_dir)

    assert os.environ["OPEN_JTALK_DICT_DIR"] == str(openjtalk_dir)
    assert pyopenjtalk_module.OPEN_JTALK_DICT_DIR == str(openjtalk_dir).encode("utf-8")
    assert calls == [("unset", None), ("update", str(user_dict_bin))]
