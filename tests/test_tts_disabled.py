from __future__ import annotations

import json

import pytest

from lab.agent.output_types import DisplayText
from lab.config_manager import XnneHangLabSettings
from lab.conversations.tts_manager import TTSTaskManager


@pytest.mark.anyio
async def test_disabled_tts_sends_silent_payload_without_dispatch(monkeypatch) -> None:
    settings = XnneHangLabSettings()
    manager = TTSTaskManager(turn_id="turn", lab_setting=settings)

    async def fail_dispatch(*_args, **_kwargs) -> None:
        raise AssertionError("disabled TTS must not dispatch")

    monkeypatch.setattr(manager, "_process_tts", fail_dispatch)
    payloads: list[dict[str, object]] = []

    async def websocket_send(payload: str) -> None:
        payloads.append(json.loads(payload))

    await manager.speak(
        tts_text="hello",
        display_text=DisplayText("hello"),
        actions=None,
        live2d_model=None,
        websocket_send=websocket_send,
    )
    await manager.wait_until_all_payloads_sent()

    assert payloads == [
        {
            "type": "audio",
            "audio": None,
            "volumes": [0.0],
            "slice_length": 20,
            "display_text": {"text": "hello", "name": "AI", "avatar": None},
            "actions": None,
            "forwarded": False,
            "turn_id": "turn",
            "tts_error": False,
        }
    ]
