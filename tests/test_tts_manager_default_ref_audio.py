from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import lab.conversations.tts_manager as tts_manager_module
from lab.config_manager.vtuber import CharacterSettings, TTSConfig
from lab.conversations.tts_manager import (
    TTSDispatcher,
    _load_voice_config,
    _require_voice_ref_audio_and_text,
    _resolve_gsv_lite_speaker_audio_path,
    _resolve_ref_audio_and_text,
    _resolve_voice_ref_audio_and_text,
)
from lab.profile.schema import TTSConfig as ProfileTTSConfig


def test_resolve_ref_audio_and_text_prefers_matching_emotion(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "models" / "genie-tts" / "baoqiao" / "emotions"
    model_dir.mkdir(parents=True)
    happy_ref = model_dir / "happy.wav"
    happy_ref.write_bytes(b"wav")
    default_ref = model_dir / "neutral.wav"
    default_ref.write_bytes(b"wav")

    monkeypatch.chdir(tmp_path)

    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            emotions={
                "default": {"path": "emotions/neutral.wav", "ref_text": ""},
                "happy": {"path": "emotions/happy.wav", "ref_text": "happy ref text"},
            },
        )
    )

    ref_audio, ref_text = _resolve_ref_audio_and_text(character, emotion_keys=["happy"])

    assert ref_audio == str(Path("models/genie-tts/baoqiao/emotions/happy.wav"))
    assert ref_text == "happy ref text"


def test_resolve_ref_audio_and_text_uses_gsv_lite_reference_directory(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "emotions"
    model_dir.mkdir(parents=True)
    happy_ref = model_dir / "happy.wav"
    happy_ref.write_bytes(b"wav")

    monkeypatch.chdir(tmp_path)

    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            emotions={
                "default": {"path": "emotions/neutral.wav", "ref_text": ""},
                "happy": {"path": "emotions/happy.wav", "ref_text": "happy ref text"},
            },
        )
    )

    ref_audio, ref_text = _resolve_ref_audio_and_text(character, emotion_keys=["happy"], tts_provider="gsv_lite")

    assert ref_audio == str(Path("models/gsv-tts-lite/baoqiao/emotions/happy.wav"))
    assert ref_text == "happy ref text"


def test_resolve_ref_audio_and_text_falls_back_to_first_emotion_without_ref_text(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "models" / "genie-tts" / "baoqiao" / "emotions"
    model_dir.mkdir(parents=True)
    first_ref = model_dir / "neutral.wav"
    first_ref.write_bytes(b"wav")

    monkeypatch.chdir(tmp_path)

    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            emotions={
                "neutral": "emotions/neutral.wav",
                "sad": {"path": "emotions/sad.wav", "ref_text": "sad ref text"},
            },
        )
    )

    ref_audio, ref_text = _resolve_ref_audio_and_text(character, emotion_keys=["happy"])

    assert ref_audio == str(Path("models/genie-tts/baoqiao/emotions/neutral.wav"))
    assert ref_text is None


def test_resolve_ref_audio_and_text_returns_none_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            emotions={"default": "emotions/neutral.wav"},
        )
    )

    ref_audio, ref_text = _resolve_ref_audio_and_text(character, emotion_keys=["happy"])

    assert ref_audio is None
    assert ref_text is None


def test_resolve_ref_audio_and_text_returns_none_when_emotions_empty() -> None:
    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            emotions={},
        )
    )

    ref_audio, ref_text = _resolve_ref_audio_and_text(character, emotion_keys=["happy"])

    assert ref_audio is None
    assert ref_text is None


def test_profile_tts_config_accepts_legacy_and_structured_emotions() -> None:
    config = ProfileTTSConfig.model_validate(
        {
            "character_name": "baoqiao",
            "voice": "baoqiao-soft",
            "emotions": {
                "default": "emotions/neutral.wav",
                "happy": {
                    "path": "emotions/happy.wav",
                    "ref_text": "happy ref text",
                    "speaker_audio_path": "speaker/happy.wav",
                },
            },
        }
    )

    assert config.voice == "baoqiao-soft"
    assert config.emotions["default"].path == "emotions/neutral.wav"
    assert config.emotions["default"].ref_text == ""
    assert config.emotions["default"].speaker_audio_path == ""
    assert config.emotions["happy"].path == "emotions/happy.wav"
    assert config.emotions["happy"].ref_text == "happy ref text"
    assert config.emotions["happy"].speaker_audio_path == "speaker/happy.wav"


def test_profile_tts_config_defaults_emotions_to_empty_dict() -> None:
    config = ProfileTTSConfig.model_validate(
        {
            "character_name": "baoqiao",
            "voice": "baoqiao-soft",
        }
    )

    assert config.voice == "baoqiao-soft"
    assert config.emotions == {}


def test_resolve_gsv_lite_speaker_audio_path_prefers_matching_emotion(tmp_path: Path, monkeypatch) -> None:
    speaker_dir = tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "speaker"
    speaker_dir.mkdir(parents=True)
    happy_speaker = speaker_dir / "happy.wav"
    happy_speaker.write_bytes(b"wav")

    monkeypatch.chdir(tmp_path)

    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            emotions={
                "default": {
                    "path": "emotions/neutral.wav",
                    "ref_text": "",
                    "speaker_audio_path": "speaker/default.wav",
                },
                "happy": {
                    "path": "emotions/happy.wav",
                    "ref_text": "happy ref text",
                    "speaker_audio_path": "speaker/happy.wav",
                },
            },
        )
    )

    speaker_audio = _resolve_gsv_lite_speaker_audio_path(character, emotion_keys=["happy"], tts_provider="gsv_lite")

    assert speaker_audio == str(Path("models/gsv-tts-lite/baoqiao/speaker/happy.wav"))


def test_resolve_voice_ref_audio_and_text_uses_voice_directory_default_emotion(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "voices"
    voice_assets_root = tmp_path / "voice-assets"
    voice_dir = voice_assets_root / "baoqiao-assets"
    emotions_dir = voice_dir / "emotions"
    speaker_dir = voice_dir / "speaker"
    config_dir.mkdir(parents=True)
    emotions_dir.mkdir(parents=True)
    speaker_dir.mkdir(parents=True)
    (emotions_dir / "calm.wav").write_bytes(b"wav")
    (emotions_dir / "calm.txt").write_text("calm ref text", encoding="utf-8")
    (speaker_dir / "default.wav").write_bytes(b"wav")
    (config_dir / "baoqiao.toml").write_text(
        """
[voice]
name = "baoqiao"
asset_bundle = "baoqiao-assets"
default_emotion = "calm"
""".strip(),
        encoding="utf-8",
    )

    voice_config = _load_voice_config("baoqiao", tmp_path.resolve())
    ref_audio, ref_text, speaker_audio = _resolve_voice_ref_audio_and_text(
        voice_config,
        voice_assets_root.resolve(),
        emotion_keys=["happy"],
    )

    assert ref_audio == "voice-assets/baoqiao-assets/emotions/calm.wav"
    assert ref_text == "calm ref text"
    assert speaker_audio == "voice-assets/baoqiao-assets/speaker/default.wav"


def test_resolve_voice_ref_audio_and_text_supports_explicit_emotion_clips_in_voice_toml(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config" / "voices"
    voice_assets_root = tmp_path / "voices"
    calm_dir = voice_assets_root / "luming" / "平静"
    happy_dir = voice_assets_root / "luming" / "愉快"
    speaker_dir = voice_assets_root / "luming" / "speaker"
    config_dir.mkdir(parents=True)
    calm_dir.mkdir(parents=True)
    happy_dir.mkdir(parents=True)
    speaker_dir.mkdir(parents=True)
    (calm_dir / "1.wav").write_bytes(b"wav")
    (calm_dir / "1.txt").write_text("平静 ref text", encoding="utf-8")
    (happy_dir / "1.wav").write_bytes(b"wav")
    (happy_dir / "1.txt").write_text("愉快 ref text 1", encoding="utf-8")
    (happy_dir / "2.wav").write_bytes(b"wav")
    (happy_dir / "2.txt").write_text("愉快 ref text 2", encoding="utf-8")
    (speaker_dir / "happy.wav").write_bytes(b"wav")
    (config_dir / "luming.toml").write_text(
        """
[voice]
name = "luming"
asset_bundle = "luming"
default_emotion = "平静"
selection = "random"

[emotions."愉快"]
speaker_audio = "speaker/happy.wav"

[[emotions."愉快".clips]]
id = "1"
ref_audio = "愉快/1.wav"
ref_text_file = "愉快/1.txt"

[[emotions."愉快".clips]]
id = "2"
ref_audio = "愉快/2.wav"
ref_text_file = "愉快/2.txt"
""".strip(),
        encoding="utf-8",
    )

    def choose_last(items: list[object]) -> object:
        return items[-1]

    monkeypatch.setattr(tts_manager_module.random, "choice", choose_last)

    voice_config = _load_voice_config("luming", tmp_path.resolve())
    ref_audio, ref_text, speaker_audio = _resolve_voice_ref_audio_and_text(
        voice_config,
        voice_assets_root.resolve(),
        emotion_keys=["愉快"],
    )

    assert ref_audio == "voices/luming/愉快/2.wav"
    assert ref_text == "愉快 ref text 2"
    assert speaker_audio == "voices/luming/speaker/happy.wav"


def test_tts_dispatcher_prefers_profile_engine_over_voice_toml_and_lab_provider(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "voices"
    voice_assets_root = tmp_path / "voice-assets"
    voice_dir = voice_assets_root / "baoqiao-assets"
    emotions_dir = voice_dir / "emotions"
    config_dir.mkdir(parents=True)
    emotions_dir.mkdir(parents=True)
    (emotions_dir / "happy.wav").write_bytes(b"wav")
    (emotions_dir / "happy.txt").write_text("happy ref text", encoding="utf-8")
    (config_dir / "baoqiao-soft.toml").write_text(
        """
[voice]
name = "baoqiao-soft"
asset_bundle = "baoqiao-assets"
preferred_engine = "gsv_lite"
default_emotion = "default"
""".strip(),
        encoding="utf-8",
    )

    settings = SimpleNamespace(
        agent=SimpleNamespace(tts=SimpleNamespace(provider="genie_tts", voice_assets_root="./voice-assets")),
        root=SimpleNamespace(root_dir=str(tmp_path)),
    )
    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            engine="qwen_tts",
            voice="baoqiao-soft",
        )
    )

    dispatch = TTSDispatcher(settings, character).resolve("hello", emotion_keys=["happy"])

    assert dispatch.engine == "qwen_tts"
    assert dispatch.request_payload["ref_audio_path"] == "voice-assets/baoqiao-assets/emotions/happy.wav"
    assert dispatch.request_payload["ref_text"] == "happy ref text"


def test_tts_dispatcher_uses_nested_luming_layout(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "voices"
    voice_assets_root = tmp_path / "voices"
    calm_dir = voice_assets_root / "luming" / "平静"
    config_dir.mkdir(parents=True)
    calm_dir.mkdir(parents=True)
    (calm_dir / "1.wav").write_bytes(b"wav")
    (calm_dir / "1.txt").write_text("平静 ref text", encoding="utf-8")
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

    settings = SimpleNamespace(
        agent=SimpleNamespace(tts=SimpleNamespace(provider="genie_tts", voice_assets_root="./voices")),
        root=SimpleNamespace(root_dir=str(tmp_path)),
    )
    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="luming",
            voice="luming",
        )
    )

    dispatch = TTSDispatcher(settings, character).resolve("hello")

    assert dispatch.engine == "genie_tts"
    assert dispatch.request_payload["ref_audio_path"] == "voices/luming/平静/1.wav"
    assert dispatch.request_payload["ref_text"] == "平静 ref text"


def test_tts_dispatcher_requires_explicit_voice_config_to_exist(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        agent=SimpleNamespace(tts=SimpleNamespace(provider="genie_tts", voice_assets_root="./voices")),
        root=SimpleNamespace(root_dir=str(tmp_path)),
    )
    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            voice="missing-voice",
        )
    )

    try:
        TTSDispatcher(settings, character)
    except FileNotFoundError as exc:
        assert "missing-voice" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError for missing explicit voice config")


def test_require_voice_ref_audio_and_text_does_not_fall_back_to_profile_emotions(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "voices"
    voice_assets_root = tmp_path / "voice-assets"
    config_dir.mkdir(parents=True)
    (config_dir / "baoqiao-soft.toml").write_text(
        """
[voice]
name = "baoqiao-soft"
asset_bundle = "baoqiao-assets"
default_emotion = "default"
""".strip(),
        encoding="utf-8",
    )

    voice_config = _load_voice_config("baoqiao-soft", tmp_path.resolve())

    try:
        _require_voice_ref_audio_and_text(
            voice_config,
            voice_assets_root.resolve(),
            emotion_keys=["happy"],
        )
    except FileNotFoundError as exc:
        assert "baoqiao-soft" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError when voice assets are missing")


def test_tts_dispatcher_does_not_fall_back_to_profile_emotions_when_voice_is_configured(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "voices"
    config_dir.mkdir(parents=True)
    (config_dir / "baoqiao-soft.toml").write_text(
        """
[voice]
name = "baoqiao-soft"
asset_bundle = "baoqiao-assets"
default_emotion = "default"
""".strip(),
        encoding="utf-8",
    )

    settings = SimpleNamespace(
        agent=SimpleNamespace(tts=SimpleNamespace(provider="genie_tts", voice_assets_root="./voice-assets")),
        root=SimpleNamespace(root_dir=str(tmp_path)),
    )
    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            voice="baoqiao-soft",
            emotions={"default": {"path": "emotions/neutral.wav", "ref_text": "legacy ref text"}},
        )
    )

    try:
        TTSDispatcher(settings, character).resolve("hello")
    except FileNotFoundError as exc:
        assert "baoqiao-soft" in str(exc)
    else:
        raise AssertionError("expected voice resolution to fail instead of falling back to profile emotions")
