from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

import lab.api.clients as api_clients_module
import lab.conversations.tts_manager as tts_manager_module
from lab.config_manager.vtuber import CharacterSettings, TTSConfig
from lab.conversations.tts_manager import TTSTaskManager


def test_generate_audio_uses_gsv_lite_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref_audio: Path = tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "emotions" / "neutral.wav"
    ref_audio.parent.mkdir(parents=True)
    ref_audio.write_bytes(b"wav")
    speaker_audio: Path = tmp_path / "models" / "gsv-tts-lite" / "baoqiao" / "speaker" / "neutral_speaker.wav"
    speaker_audio.parent.mkdir(parents=True)
    speaker_audio.write_bytes(b"wav")
    monkeypatch.chdir(tmp_path)

    def fake_load_settings_file(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            agent=SimpleNamespace(
                tts=SimpleNamespace(provider="gsv_lite"),
                speaker_lang="ZH",
            )
        )

    monkeypatch.setattr(tts_manager_module, "load_settings_file", fake_load_settings_file)

    captured_requests: list[dict[str, Any]] = []

    class FakeGSVLiteClient:
        last_error: str | None = None

        async def asyncpost(self, request: Any) -> dict[str, object]:
            captured_requests.append(request.model_dump())
            return {
                "audio_type": "wav",
                "audio_rate": 32000,
                "audio_byte": b"RIFFfakewav",
            }

    monkeypatch.setattr(api_clients_module, "GSVLiteClient", FakeGSVLiteClient)

    manager = TTSTaskManager()
    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            emotions={
                "default": {
                    "path": "emotions/neutral.wav",
                    "ref_text": "neutral ref",
                    "speaker_audio_path": "speaker/neutral_speaker.wav",
                }
            },
        )
    )

    result = asyncio.run(manager._generate_audio("test", character_config=character))

    assert result is not None
    assert result.exists()
    assert result.suffix == ".wav"
    assert len(captured_requests) == 1
    assert captured_requests[0]["text"] == "test"
    assert Path(captured_requests[0]["ref_audio_path"]) == Path("models/gsv-tts-lite/baoqiao/emotions/neutral.wav")
    assert captured_requests[0]["ref_text"] == "neutral ref"
    assert Path(captured_requests[0]["speaker_audio_path"]) == Path(
        "models/gsv-tts-lite/baoqiao/speaker/neutral_speaker.wav"
    )


def test_generate_audio_uses_voice_directory_and_voice_toml_for_gsv_lite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config" / "voices"
    voice_assets_root = tmp_path / "voice-assets"
    voice_dir = voice_assets_root / "baoqiao-assets"
    emotions_dir = voice_dir / "emotions"
    speaker_dir = voice_dir / "speaker"
    config_dir.mkdir(parents=True)
    emotions_dir.mkdir(parents=True)
    speaker_dir.mkdir(parents=True)
    (emotions_dir / "default.wav").write_bytes(b"wav")
    (emotions_dir / "default.txt").write_text("voice ref text", encoding="utf-8")
    (speaker_dir / "default.wav").write_bytes(b"wav")
    (config_dir / "baoqiao-soft.toml").write_text(
        """
[voice]
name = "baoqiao-soft"
asset_bundle = "baoqiao-assets"
preferred_engine = "gsv_lite"

[engine_params.gsv_lite]
top_k = 7
speed = 1.25
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    def fake_load_settings_file(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            agent=SimpleNamespace(
                tts=SimpleNamespace(provider="genie_tts", voice_assets_root="./voice-assets"),
                speaker_lang="ZH",
            ),
            root=SimpleNamespace(root_dir=str(tmp_path)),
        )

    monkeypatch.setattr(tts_manager_module, "load_settings_file", fake_load_settings_file)

    captured_requests: list[dict[str, Any]] = []

    class FakeGSVLiteClient:
        last_error: str | None = None

        async def asyncpost(self, request: Any) -> dict[str, object]:
            captured_requests.append(request.model_dump())
            return {
                "audio_type": "wav",
                "audio_rate": 32000,
                "audio_byte": b"RIFFfakewav",
            }

    monkeypatch.setattr(api_clients_module, "GSVLiteClient", FakeGSVLiteClient)

    manager = TTSTaskManager()
    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            voice="baoqiao-soft",
        )
    )

    result = asyncio.run(manager._generate_audio("test", character_config=character))

    assert result is not None
    assert result.exists()
    assert len(captured_requests) == 1
    assert Path(captured_requests[0]["ref_audio_path"]) == Path("voice-assets/baoqiao-assets/emotions/default.wav")
    assert captured_requests[0]["ref_text"] == "voice ref text"
    assert Path(captured_requests[0]["speaker_audio_path"]) == Path("voice-assets/baoqiao-assets/speaker/default.wav")
    assert captured_requests[0]["top_k"] == 7
    assert captured_requests[0]["speed"] == 1.25
