from __future__ import annotations

from lab.agent.stateless_llm.openai_compatible_llm import AsyncLLM, build_thinking_extra_body


def test_build_thinking_extra_body_supports_three_modes() -> None:
    assert build_thinking_extra_body("default") is None
    assert build_thinking_extra_body("enabled") == {"thinking": {"type": "enabled"}}
    assert build_thinking_extra_body("disabled") == {"thinking": {"type": "disabled"}}


def test_request_kwargs_omit_provider_extension_by_default() -> None:
    llm = AsyncLLM(
        model="text-model",
        base_url="http://127.0.0.1:8000/v1",
        llm_api_key="sk-test",
    )

    kwargs = llm._build_request_kwargs(messages=[{"role": "user", "content": "hi"}], stream=True, temperature=1.0)

    assert "extra_body" not in kwargs


def test_request_kwargs_include_disabled_thinking_for_chat_and_tools() -> None:
    llm = AsyncLLM(
        model="deepseek-v4-flash-vision-exp",
        base_url="http://127.0.0.1:8000/v1",
        llm_api_key="sk-test",
        thinking_mode="disabled",
    )
    tools = [{"type": "function", "function": {"name": "screen_shot", "parameters": {"type": "object"}}}]

    kwargs = llm._build_request_kwargs(
        messages=[{"role": "user", "content": "what is on screen?"}],
        stream=True,
        temperature=1.0,
        tools=tools,
    )

    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert kwargs["tools"] == tools
    assert kwargs["tool_choice"] == "auto"


def test_request_kwargs_return_independent_thinking_payloads() -> None:
    llm = AsyncLLM(
        model="deepseek-v4-flash-vision-exp",
        base_url="http://127.0.0.1:8000/v1",
        llm_api_key="sk-test",
        thinking_mode="enabled",
    )

    first = llm._build_request_kwargs(messages=[], stream=False, temperature=1.0)
    first["extra_body"]["thinking"]["type"] = "mutated"
    second = llm._build_request_kwargs(messages=[], stream=False, temperature=1.0)

    assert second["extra_body"] == {"thinking": {"type": "enabled"}}
