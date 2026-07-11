from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

import numpy as np

import lab.api.logic.gsv_lite as gsv_lite_logic

if TYPE_CHECKING:
    from pytest import MonkeyPatch


class _FakeClip:
    def __init__(self) -> None:
        self.audio_data = np.zeros(320, dtype=np.float32)
        self.samplerate = 32000


def test_repair_japanese_word2ph_balances_small_mismatch() -> None:
    repaired = gsv_lite_logic._repair_japanese_word2ph(
        {"word": ["a", "b", "c"], "ph": [2, 2, 2]},
        7,
    )

    assert repaired == {"word": ["a", "b", "c"], "ph": [2, 2, 3]}


def test_apply_gsv_lite_monkey_patch_repairs_japanese_g2p(monkeypatch: MonkeyPatch) -> None:
    class FakeJapaneseG2P:
        def g2p(self, norm_text: str, with_prosody: bool = True):
            del norm_text, with_prosody
            return ["a", "b", "c"], {"word": ["x", "y"], "ph": [1, 1]}

    monkeypatch.setattr(gsv_lite_logic, "_gsv_lite_monkey_patch_applied", False)

    gsv_tts_module = ModuleType("gsv_tts")
    gpt_sovits_module = ModuleType("gsv_tts.GPT_SoVITS")
    g2p_module = ModuleType("gsv_tts.GPT_SoVITS.G2P")
    japanese_module = ModuleType("gsv_tts.GPT_SoVITS.G2P.Japanese")
    japanese_impl_module = ModuleType("gsv_tts.GPT_SoVITS.G2P.Japanese.japanese")
    cast("Any", japanese_impl_module).JapaneseG2P = FakeJapaneseG2P

    monkeypatch.setitem(sys.modules, "gsv_tts", gsv_tts_module)
    monkeypatch.setitem(sys.modules, "gsv_tts.GPT_SoVITS", gpt_sovits_module)
    monkeypatch.setitem(sys.modules, "gsv_tts.GPT_SoVITS.G2P", g2p_module)
    monkeypatch.setitem(sys.modules, "gsv_tts.GPT_SoVITS.G2P.Japanese", japanese_module)
    monkeypatch.setitem(sys.modules, "gsv_tts.GPT_SoVITS.G2P.Japanese.japanese", japanese_impl_module)

    gsv_lite_logic._apply_gsv_lite_monkey_patch()

    phones, word2ph = FakeJapaneseG2P().g2p("test")

    assert phones == ["a", "b", "c"]
    assert word2ph == {"word": ["x", "y"], "ph": [1, 2]}


def test_synthesize_once_retries_with_normalized_japanese_text(monkeypatch: MonkeyPatch) -> None:
    captured_texts: list[str] = []
    source_text = "\u5149\u304c\u30ad\u30fc\u30dc\u30fc\u30c9\u306b\u6d12\u308c\u308b\u306e\u3092\u8a66\u3057\u3066\u307f\u307e\u305b\u3093\u304b\uff1f"
    normalized_text = "\u5149\u304c\u30ad\u30fc\u30dc\u30fc\u30c9\u306b\u3053\u307c\u308c\u308b\u306e\u3092\u8a66\u3057\u3066\u307f\u307e\u305b\u3093\u304b\uff1f"

    class FakeModel:
        async def infer_async(self, **kwargs: Any) -> _FakeClip:
            captured_texts.append(kwargs["text"])
            if len(captured_texts) == 1:
                raise AssertionError("length mismatch: The length of phones is 52, while the total of word2ph is 51")
            return _FakeClip()

    monkeypatch.setattr(gsv_lite_logic, "get_gsv_lite_model", lambda: FakeModel())

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ref_audio = tmp_path / "ref.wav"
        speaker_audio = tmp_path / "speaker.wav"
        ref_audio.write_bytes(b"RIFF")
        speaker_audio.write_bytes(b"RIFF")

        wav_bytes = asyncio.run(
            gsv_lite_logic.synthesize_once(
                text=source_text,
                ref_audio=ref_audio,
                ref_text="ref text",
                speaker_audio=speaker_audio,
            )
        )

    assert wav_bytes
    assert captured_texts == [source_text, normalized_text]


def test_synthesize_once_retries_by_splitting_long_text(monkeypatch: MonkeyPatch) -> None:
    captured_texts: list[str] = []
    long_text = "\u3042\u3089\u3001" + ("\u5f85\u3063\u3066\u3044\u308b\u306e\u3092" * 20)

    async def fake_infer_clip(*_args: Any, text: str, **_kwargs: Any) -> _FakeClip:
        captured_texts.append(text)
        if text == long_text:
            raise RuntimeError(
                "The expanded size of the tensor (1024) must match the existing size (1704) "
                "at non-singleton dimension 2."
            )
        return _FakeClip()

    monkeypatch.setattr(gsv_lite_logic, "get_gsv_lite_model", lambda: object())
    monkeypatch.setattr(gsv_lite_logic, "_infer_clip", fake_infer_clip)

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ref_audio = tmp_path / "ref.wav"
        speaker_audio = tmp_path / "speaker.wav"
        ref_audio.write_bytes(b"RIFF")
        speaker_audio.write_bytes(b"RIFF")

        wav_bytes = asyncio.run(
            gsv_lite_logic.synthesize_once(
                text=long_text,
                ref_audio=ref_audio,
                ref_text="ref text",
                speaker_audio=speaker_audio,
            )
        )

    assert wav_bytes
    assert captured_texts[0] == long_text
    assert len(captured_texts) > 1
    assert all(len(chunk) <= gsv_lite_logic._GSV_LITE_SEGMENT_MAX_CHARS for chunk in captured_texts[1:])
