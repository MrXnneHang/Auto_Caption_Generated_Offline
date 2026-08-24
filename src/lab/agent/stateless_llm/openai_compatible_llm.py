"""OpenAI-compatible async LLM wrapper (no extra interface layer).

- chat_completion: stream tokens for final chat output
- stream_with_tools: stream raw chunks with native tool-calling support

This module intentionally does NOT depend on any MemoryManager abstraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import httpx
from loguru import logger
from openai import APIConnectionError, APIError, AsyncOpenAI, AsyncStream, RateLimitError

from lab.agent.types import OpenAIMessage, call_with_short_retry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from openai.types.chat import ChatCompletion, ChatCompletionChunk

    from lab.config_manager.agent import ThinkingMode


def build_thinking_extra_body(thinking_mode: ThinkingMode) -> dict[str, dict[str, str]] | None:
    if thinking_mode == "default":
        return None
    return {"thinking": {"type": thinking_mode}}


def normalize_messages(
    messages: Sequence[OpenAIMessage | dict[str, Any]],
    *,
    system: str | None = None,
) -> list[dict[str, Any]]:
    # 1) pydantic 校验/解析
    parsed: list[OpenAIMessage] = [
        m if isinstance(m, OpenAIMessage) else OpenAIMessage.model_validate(m) for m in messages
    ]

    # 2) 注入 system/developer
    if system:
        parsed = [OpenAIMessage(role="system", content=system), *parsed]

    # 3) 转成 OpenAI API dict
    return [m.to_openai_dict() for m in parsed]


class AsyncLLM:
    """A thin wrapper around `AsyncOpenAI` (OpenAI-compatible endpoints)."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        llm_api_key: str,
        organization_id: str = "z",
        project_id: str = "z",
        temperature: float = 1.0,
        thinking_mode: ThinkingMode = "default",
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.thinking_extra_body = build_thinking_extra_body(thinking_mode)

        # localhost/127.0.0.1 绕过系统代理（Clash 等会拦截本地请求导致 502）
        # trust_env=False 阻止 httpx 读取 HTTP_PROXY/HTTPS_PROXY 等环境变量
        _no_proxy = "localhost" in base_url or "127.0.0.1" in base_url
        if _no_proxy:
            logger.info(f"AsyncLLM: {base_url} is local, bypassing system proxy")
            _http_client: httpx.AsyncClient | None = httpx.AsyncClient(trust_env=False)
        else:
            _http_client = None

        self.client = AsyncOpenAI(
            base_url=base_url,
            organization=organization_id,
            project=project_id,
            api_key=llm_api_key,
            http_client=_http_client,
        )
        logger.info(f"Initialized AsyncLLM: base_url={self.base_url}, model={self.model}")

    def _build_request_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        stream: bool,
        temperature: float,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "messages": messages,
            "model": self.model,
            "stream": stream,
            "temperature": temperature,
        }
        if self.thinking_extra_body is not None:
            kwargs["extra_body"] = {key: dict(value) for key, value in self.thinking_extra_body.items()}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
        return kwargs

    async def chat_completion(
        self,
        messages: list[OpenAIMessage],
        system: str | None = None,
        *,
        stream_: bool = True,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Generate a chat completion.

        - When `stream_` is True, yields token chunks.
        - When `stream_` is False, yields a single full string.
        """
        stream: AsyncStream[ChatCompletionChunk] | None = None

        try:
            messages_with_system = normalize_messages(messages, system=system)

            temp = self.temperature if temperature is None else temperature

            if stream_:
                stream = await self.client.chat.completions.create(
                    **self._build_request_kwargs(
                        messages=messages_with_system,
                        stream=True,
                        temperature=temp,
                    )
                )

                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content is None:
                        delta.content = ""
                    yield delta.content
            else:
                response = await self.client.chat.completions.create(
                    **self._build_request_kwargs(
                        messages=messages_with_system,
                        stream=False,
                        temperature=temp,
                    )
                )

                assistant_msg = response.choices[0].message
                yield assistant_msg.content or ""

        except APIConnectionError as e:
            logger.error(
                "Connection error calling chat endpoint. Check base_url/api_key and LLM backend reachability. "
                f"{e.__cause__}"
            )
            yield "Error calling the chat endpoint: Connection error. Failed to connect to the LLM API."

        except RateLimitError as e:
            logger.error(f"Rate limit exceeded: {e.response}")
            yield "Error calling the chat endpoint: Rate limit exceeded. Please try again later."

        except APIError as e:
            logger.error(f"LLM API error: {e}")
            logger.info(f"base_url={self.base_url} model={self.model} temperature={self.temperature}")
            yield "Error calling the chat endpoint: Error occurred while generating response."

        finally:
            if stream is not None:
                try:
                    await stream.close()
                except Exception:
                    pass

    async def stream_with_tools(
        self,
        messages: list[OpenAIMessage],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float | None = None,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Stream raw chunks with tool call support."""
        messages_with_system = normalize_messages(messages, system=system)
        temp = self.temperature if temperature is None else temperature
        kwargs = self._build_request_kwargs(
            messages=messages_with_system,
            stream=True,
            temperature=temp,
            tools=tools,
            tool_choice=tool_choice,
        )

        stream: AsyncStream[ChatCompletionChunk] | None = None
        try:
            stream = cast(
                "AsyncStream[ChatCompletionChunk]",
                await self.client.chat.completions.create(**kwargs),
            )
            async for chunk in stream:
                yield chunk

        except APIConnectionError as e:
            logger.opt(exception=e).error(
                "Connection error calling chat endpoint (stream_with_tools). "
                "Check base_url/api_key and LLM backend reachability."
            )
            raise

        except RateLimitError as e:
            logger.error(f"Rate limit exceeded (stream_with_tools): {e.response}")
            raise

        except APIError as e:
            logger.error(f"LLM API error (stream_with_tools): {e}")
            logger.info(f"base_url={self.base_url} model={self.model} temperature={self.temperature}")
            raise

        finally:
            if stream is not None:
                try:
                    await stream.close()
                except Exception:
                    pass

    async def vision_completion_once(
        self,
        messages: list[OpenAIMessage],
        system: str | None = None,
        *,
        temperature: float | None = None,
    ) -> str:
        messages_with_system = normalize_messages(messages, system=system)
        temp = self.temperature if temperature is None else temperature

        resp = cast(
            "ChatCompletion",
            await call_with_short_retry(
                lambda: self.client.chat.completions.create(
                    **self._build_request_kwargs(
                        messages=messages_with_system,
                        stream=False,
                        temperature=temp,
                    )
                ),
                max_retries=2,
            ),
        )
        return (resp.choices[0].message.content or "").strip()
