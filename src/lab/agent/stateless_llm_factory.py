from __future__ import annotations

from typing import TYPE_CHECKING

from lab.agent.stateless_llm.openai_compatible_llm import AsyncLLM

if TYPE_CHECKING:
    from lab.config_manager.agent import ThinkingMode

"""LLM factory (OpenAI-compatible only).

You said you only keep OpenAI now, so the factory no longer branches by provider.
It returns `AsyncLLM` directly (no extra stateless interface layer).
"""


class LLMFactory:
    @staticmethod
    def create_llm(
        *,
        model: str,
        base_url: str,
        llm_api_key: str,
        thinking_mode: ThinkingMode = "default",
    ) -> AsyncLLM:
        return AsyncLLM(
            model=model,
            base_url=base_url,
            llm_api_key=llm_api_key,
            thinking_mode=thinking_mode,
        )
