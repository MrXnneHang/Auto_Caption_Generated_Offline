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


def test_generate_audio_uses_genie_tts_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref_audio: Path = tmp_path / "models" / "genie-tts" / "baoqiao" / "emotions" / "neutral.wav"
    ref_audio.parent.mkdir(parents=True)
    ref_audio.write_bytes(b"wav")
    monkeypatch.chdir(tmp_path)

    def fake_load_settings_file(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            agent=SimpleNamespace(
                tts=SimpleNamespace(provider="genie_tts"),
                speaker_lang="ZH",
            )
        )

    monkeypatch.setattr(tts_manager_module, "load_settings_file", fake_load_settings_file)

    captured_requests: list[dict[str, Any]] = []

    class FakeGenieTTSClient:
        last_error: str | None = None

        async def asyncpost(self, request: Any) -> dict[str, object]:
            captured_requests.append(request.model_dump())
            return {
                "audio_type": "wav",
                "audio_rate": 32000,
                "audio_byte": b"RIFFfakewav",
            }

    monkeypatch.setattr(api_clients_module, "GenieTTSClient", FakeGenieTTSClient)

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
