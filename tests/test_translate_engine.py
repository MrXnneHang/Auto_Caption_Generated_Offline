from __future__ import annotations

from typing import TYPE_CHECKING, cast

from lab.translate.engine import LLMTranslateEngine

if TYPE_CHECKING:
    from collections.abc import Callable


def test_build_system_prompt_for_japanese_forbids_simplified_chinese() -> None:
    build_system_prompt = LLMTranslateEngine._build_system_prompt
    prompt = cast("Callable[[str], str]", build_system_prompt)("JA")

    assert "natural Japanese" in prompt
    assert "Do not include Simplified Chinese characters" in prompt
    assert "Output translation only." in prompt


def test_build_system_prompt_for_non_japanese_stays_minimal() -> None:
    build_system_prompt = LLMTranslateEngine._build_system_prompt
    prompt = cast("Callable[[str], str]", build_system_prompt)("ZH")

    assert prompt == "Translate to Chinese. Output translation only."
