from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Annotated, Any, Literal, Protocol, TypeAlias, TypeGuard, TypeVar, cast

from openai import APIError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonLike: TypeAlias = JsonPrimitive | dict[str, "JsonLike"] | list["JsonLike"]
_T = TypeVar("_T")


def _is_jsonlike(value: object) -> TypeGuard[JsonLike]:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        items = cast("list[object]", value)
        return all(_is_jsonlike(item) for item in items)
    if isinstance(value, dict):
        items = cast("dict[object, object]", value)
        return all(isinstance(key, str) and _is_jsonlike(item) for key, item in items.items())
    return False


def _normalize_mapping(mapping: Mapping[object, object]) -> dict[str, JsonLike]:
    return {str(k): cast("JsonLike", normalize_jsonlike(v)) for k, v in mapping.items()}


def dump_openai_msg(obj: object) -> dict[str, object]:
    if hasattr(obj, "model_dump"):
        d = cast("Any", obj).model_dump(exclude_none=True)
        return dict(d)
    if hasattr(obj, "to_dict"):
        d = cast("Any", obj).to_dict()
        return dict(d)
    raise TypeError(f"Unknown message type: {type(obj)}")


def prompt_result_to_text(prompt_result: object) -> str:
    msgs = getattr(prompt_result, "messages", None) or []
    lines: list[str] = []
    for m in msgs:
        role = getattr(m, "role", "unknown")
        content = getattr(m, "content", "")
        text = getattr(content, "text", None)
        if text is None:
            text = str(content)
        lines.append(f"{role}: {text}")
    return "\n".join(lines).strip()


async def call_with_short_retry(
    awaitable_factory: Callable[[], Awaitable[_T]],
    *,
    max_retries: int = 2,
) -> _T:
    last: Exception | None = None
    for i in range(max_retries + 1):
        try:
            return await awaitable_factory()
        except (RateLimitError, APIError) as e:
            last = e
            msg = str(e)
            if "429" not in msg or "queue_exceeded" not in msg:
                raise
            if i == max_retries:
                raise
            sleep_s = (0.25 * (2**i)) + random.uniform(0.0, 0.2)
            await asyncio.sleep(sleep_s)
    if last is not None:
        raise last  # pragma: no cover
    raise RuntimeError("call_with_short_retry exited without result or captured exception")


def normalize_jsonlike(x: object, strict: bool = False) -> JsonLike | object:
    if x is None or isinstance(x, (str, int, float, bool)):
        return x

    if isinstance(x, Mapping):
        mapping = cast("Mapping[object, object]", x)
        if set(mapping.keys()) == {"_url"}:
            return str(mapping["_url"])

    if isinstance(x, Mapping):
        mapping = cast("Mapping[object, object]", x)
        return _normalize_mapping(mapping)

    if isinstance(x, Sequence) and not isinstance(x, (str, bytes, bytearray)):
        seq = cast("Sequence[object]", x)
        return [cast("JsonLike", normalize_jsonlike(v)) for v in seq]

    md = getattr(x, "model_dump", None)
    if callable(md):
        try:
            dumped = md(exclude_none=True, mode="json")
        except TypeError:
            dumped = md()
        return normalize_jsonlike(dumped)

    root = getattr(x, "root", None)
    if root is not None:
        return normalize_jsonlike(root)

    d3 = getattr(x, "__dict__", None)
    if isinstance(d3, Mapping) and d3:
        return _normalize_mapping(cast("Mapping[object, object]", d3))

    if strict:
        return x
    return str(x)


class _FnLike(Protocol):
    name: str
    arguments: str | None


class ToolCallLike(Protocol):
    id: str
    function: _FnLike


class TextPart(BaseModel):
    type: Literal["text"]
    text: str
    model_config = ConfigDict(extra="forbid")


class ImageURL(BaseModel):
    url: str
    detail: Literal["auto", "low", "high"] = "auto"
    model_config = ConfigDict(extra="forbid")


class ImagePart(BaseModel):
    type: Literal["image_url"]
    image_url: ImageURL
    model_config = ConfigDict(extra="forbid")


class InputAudio(BaseModel):
    data: str
    format: Literal["wav", "mp3"]
    model_config = ConfigDict(extra="forbid")


class AudioPart(BaseModel):
    type: Literal["input_audio"]
    input_audio: InputAudio
    model_config = ConfigDict(extra="forbid")


class FileObj(BaseModel):
    file_data: str | None = None
    file_id: str | None = None
    filename: str | None = None
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _check(self):
        if not (self.file_data or self.file_id):
            raise ValueError("file must include file_data or file_id")
        return self


class FilePart(BaseModel):
    type: Literal["file"]
    file: FileObj
    model_config = ConfigDict(extra="forbid")


ContentPart = Annotated[
    TextPart | ImagePart | AudioPart | FilePart,
    Field(discriminator="type"),
]

OpenAIContent = str | list[ContentPart]


class SystemMsg(BaseModel):
    role: Literal["system"]
    content: OpenAIContent
    tool_call_id: None = None
    model_config = ConfigDict(extra="forbid")


class UserMsg(BaseModel):
    role: Literal["user"]
    content: OpenAIContent
    tool_call_id: None = None
    model_config = ConfigDict(extra="forbid")


class AssistantMsg(BaseModel):
    role: Literal["assistant"]
    content: OpenAIContent | None = None
    tool_call_id: None = None
    model_config = ConfigDict(extra="forbid")


class ToolMsg(BaseModel):
    role: Literal["tool"]
    content: str
    tool_call_id: str
    model_config = ConfigDict(extra="forbid")


class ToolFunction(BaseModel):
    name: str
    arguments: str
    model_config = ConfigDict(extra="forbid")


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: ToolFunction
    model_config = ConfigDict(extra="forbid")


class OpenAIMessage(BaseModel):
    role: Literal["developer", "system", "user", "assistant", "tool"]
    content: OpenAIContent | None = None
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    annotations: list[Any] | None = None
    reasoning_content: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _check(self):
        if self.role == "tool":
            if not self.tool_call_id:
                raise ValueError("tool message must include tool_call_id")
            if not isinstance(self.content, str):
                raise ValueError("tool message content must be str")
            if self.tool_calls is not None:
                raise ValueError("tool message must not include tool_calls")
            return self

        if self.tool_call_id is not None:
            raise ValueError("tool_call_id is only allowed for role='tool'")

        if self.role == "assistant":
            if (self.content is None or (isinstance(self.content, str) and not self.content)) and not self.tool_calls:
                raise ValueError("assistant message must include content or tool_calls")
            return self

        if self.role in ("system", "user", "developer") and self.content is None:
            raise ValueError(f"{self.role} message must include content")

        if self.tool_calls is not None:
            raise ValueError("tool_calls is only allowed for role='assistant'")

        return self

    def to_openai_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role}
        if self.content is None:
            d["content"] = None
        elif isinstance(self.content, str):
            d["content"] = self.content
        else:
            d["content"] = [p.model_dump(mode="json") for p in self.content]

        if self.role == "tool":
            d["tool_call_id"] = self.tool_call_id

        if self.role == "assistant" and self.tool_calls:
            d["tool_calls"] = [tc.model_dump(mode="json") for tc in self.tool_calls]

        if self.role == "assistant" and self.reasoning_content:
            d["reasoning_content"] = self.reasoning_content

        return d


class ToolTraceItem(BaseModel):
    server: str
    name: str
    args: dict[str, object] = Field(default_factory=dict)
    raw_result: dict[str, object] = Field(default_factory=dict)
    ok: bool = True
    error: str | None = None


class ImageRefResult(BaseModel):
    kind: Literal["image_ref"] = "image_ref"
    image_ref: str = Field(..., min_length=1)
    mime: str = Field(default="image/jpeg", min_length=3)
    b64_len: int = Field(..., ge=0)


class ScreenShotResult(BaseModel):
    image_b64: str = Field(..., description="Current screenshot image data encoded as base64.")
    mime: str = Field(default="image/jpeg", min_length=3)


class UnknownArgs(RootModel[dict[str, object]]):
    pass


class UnknownResult(BaseModel):
    data: object | None = Field(default=None)

    @field_validator("data", mode="before")
    @classmethod
    def _normalize(cls, v: object) -> object:
        nv = normalize_jsonlike(v)
        if _is_jsonlike(nv):
            return nv
        return repr(nv)


Role = Literal["system", "user", "assistant", "tool"]


class TolerantOpenAIChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Role
    content: Any = ""


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_prefs: dict[str, Any] = Field(default_factory=dict)
    active_task: str | None = None
    refs: dict[str, Any] = Field(default_factory=dict)
    slots: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""

    @field_validator("summary")
    @classmethod
    def _summary_not_too_long(cls, v: str) -> str:
        return (v or "").strip()[:4000]

    def to_tool_pinned_json(self) -> dict[str, JsonLike]:
        return {
            "user_prefs": cast("dict[str, JsonLike]", normalize_jsonlike(self.user_prefs)),
            "active_task": self.active_task,
            "refs": cast("dict[str, JsonLike]", normalize_jsonlike(self.refs)),
            "slots": cast("dict[str, JsonLike]", normalize_jsonlike(self.slots)),
            "summary": (self.summary or "")[:1000],
        }


__all__ = [
    "AudioPart",
    "ContentPart",
    "ConversationState",
    "FilePart",
    "ImagePart",
    "ImageRefResult",
    "ImageURL",
    "OpenAIContent",
    "OpenAIMessage",
    "ScreenShotResult",
    "TextPart",
    "ToolCallLike",
    "ToolTraceItem",
    "call_with_short_retry",
    "dump_openai_msg",
    "normalize_jsonlike",
    "prompt_result_to_text",
]
