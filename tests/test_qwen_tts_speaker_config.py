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


def test_generate_audio_uses_qwen_tts_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref_audio: Path = tmp_path / "models" / "genie-tts" / "baoqiao" / "emotions" / "neutral.wav"
    ref_audio.parent.mkdir(parents=True)
    ref_audio.write_bytes(b"wav")
    monkeypatch.chdir(tmp_path)

    def fake_load_settings_file(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            agent=SimpleNamespace(
                tts=SimpleNamespace(provider="qwen_tts"),
                speaker_lang="ZH",
            )
        )

    monkeypatch.setattr(tts_manager_module, "load_settings_file", fake_load_settings_file)

    captured_requests: list[dict[str, Any]] = []

    class FakeQwenTTSClient:
        last_error: str | None = None

        async def asyncpost(self, request: Any) -> dict[str, object]:
            captured_requests.append(request.model_dump())
            return {
                "audio_type": "wav",
                "audio_rate": 24000,
                "audio_byte": b"RIFFfakewav",
            }

    monkeypatch.setattr(api_clients_module, "QwenTTSClient", FakeQwenTTSClient)

    manager = TTSTaskManager()
    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            emotions={
                "default": {
                    "path": "emotions/neutral.wav",
                    "ref_text": "neutral ref",
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
    assert Path(captured_requests[0]["ref_audio_path"]) == Path("models/genie-tts/baoqiao/emotions/neutral.wav")
    assert captured_requests[0]["ref_text"] == "neutral ref"


def test_generate_audio_prefers_profile_engine_over_voice_toml_and_lab_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config" / "voices"
    voice_assets_root = tmp_path / "voice-assets"
    voice_dir = voice_assets_root / "baoqiao-assets"
    emotions_dir = voice_dir / "emotions"
    config_dir.mkdir(parents=True)
    emotions_dir.mkdir(parents=True)
    (emotions_dir / "default.wav").write_bytes(b"wav")
    (emotions_dir / "default.txt").write_text("voice ref text", encoding="utf-8")
    (config_dir / "baoqiao-soft.toml").write_text(
        """
[voice]
name = "baoqiao-soft"
asset_bundle = "baoqiao-assets"
preferred_engine = "gsv_lite"
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

    class FakeQwenTTSClient:
        last_error: str | None = None

        async def asyncpost(self, request: Any) -> dict[str, object]:
            captured_requests.append(request.model_dump())
            return {
                "audio_type": "wav",
                "audio_rate": 24000,
                "audio_byte": b"RIFFfakewav",
            }

    monkeypatch.setattr(api_clients_module, "QwenTTSClient", FakeQwenTTSClient)

    manager = TTSTaskManager()
    character = CharacterSettings(
        tts_config=TTSConfig(
            character_name="baoqiao",
            engine="qwen_tts",
            voice="baoqiao-soft",
        )
    )

    result = asyncio.run(manager._generate_audio("test", character_config=character))

    assert result is not None
    assert result.exists()
    assert len(captured_requests) == 1
    assert Path(captured_requests[0]["ref_audio_path"]) == Path("voice-assets/baoqiao-assets/emotions/default.wav")
    assert captured_requests[0]["ref_text"] == "voice ref text"
